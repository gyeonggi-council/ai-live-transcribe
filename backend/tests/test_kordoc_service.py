"""kordoc_service 테스트

kordoc(npm) CLI를 이용한 markdown ↔ hwpx 변환 서비스 검증.
subprocess 실행은 기본적으로 monkeypatch(가짜 _run)로 대체하고,
실제 npx 실행 통합 테스트 1건은 npx 미설치 환경에서 skip 한다.
"""

import asyncio
import shutil
import sys
from pathlib import Path

import pytest

from app.services import kordoc_service


@pytest.fixture(autouse=True)
def reset_npx_cache():
    """is_available() 캐시를 테스트마다 초기화한다."""
    kordoc_service._NPX_PATH_CACHE = kordoc_service._UNSET
    yield
    kordoc_service._NPX_PATH_CACHE = kordoc_service._UNSET


def _make_fake_run(captured_cmds: list, out_bytes: bytes = b"PK\x03\x04FAKEHWPX",
                   captured_inputs: list | None = None):
    """_run 대체: 명령을 기록하고 '-o' 출력 경로에 가짜 바이트를 쓴다."""

    async def _fake_run(cmd: list[str], timeout: float = 120.0) -> bytes:
        captured_cmds.append(list(cmd))
        # 입력 파일(마크다운/hwpx) 내용도 검증할 수 있게 기록
        if captured_inputs is not None:
            if "generate" in cmd:
                in_path = cmd[cmd.index("generate") + 1]
                captured_inputs.append(Path(in_path).read_text(encoding="utf-8"))
            else:
                in_path = cmd[3]  # [npx, -y, kordoc@X, <input>, -o, <out>]
                captured_inputs.append(Path(in_path).read_bytes())
        out_path = cmd[cmd.index("-o") + 1]
        Path(out_path).write_bytes(out_bytes)
        return b""

    return _fake_run


# ---------------------------------------------------------------------------
# 버전 고정 / 명령 구성
# ---------------------------------------------------------------------------

def test_version_is_pinned():
    """kordoc 버전은 3.13.0으로 고정되어야 한다."""
    assert kordoc_service.KORDOC_VERSION == "3.13.0"


async def test_markdown_to_hwpx_command_composition(monkeypatch):
    """generate 명령: [npx, -y, kordoc@3.13.0, generate, <md>, -o, <hwpx>, --preset, 회의록]."""
    cmds: list = []
    inputs: list = []
    monkeypatch.setattr(kordoc_service, "_npx_path", lambda: "npx")
    monkeypatch.setattr(kordoc_service, "_run", _make_fake_run(cmds, captured_inputs=inputs))

    data = await kordoc_service.markdown_to_hwpx("# 제목\n\n본문입니다.")

    assert data == b"PK\x03\x04FAKEHWPX"
    assert len(cmds) == 1
    cmd = cmds[0]
    assert cmd[:3] == ["npx", "-y", "kordoc@3.13.0"]
    assert cmd[3] == "generate"
    assert cmd[4].endswith(".md")
    assert cmd[cmd.index("-o") + 1].endswith(".hwpx")
    # 기본 preset은 회의록
    assert cmd[cmd.index("--preset") + 1] == "회의록"
    # 임시 md 파일에 마크다운이 UTF-8로 기록되어 전달됨
    assert inputs == ["# 제목\n\n본문입니다."]


async def test_markdown_to_hwpx_passes_custom_preset(monkeypatch):
    """preset 인자가 명령의 --preset 값으로 그대로 전달된다."""
    cmds: list = []
    monkeypatch.setattr(kordoc_service, "_npx_path", lambda: "npx")
    monkeypatch.setattr(kordoc_service, "_run", _make_fake_run(cmds))

    await kordoc_service.markdown_to_hwpx("# 제목", preset="보고서")

    cmd = cmds[0]
    assert cmd[cmd.index("--preset") + 1] == "보고서"


async def test_hwpx_to_markdown_command_composition(monkeypatch):
    """파싱 명령: [npx, -y, kordoc@3.13.0, <hwpx>, -o, <md>] (generate 서브커맨드 없음)."""
    cmds: list = []
    inputs: list = []

    async def _fake_run(cmd: list[str], timeout: float = 120.0) -> bytes:
        cmds.append(list(cmd))
        inputs.append(Path(cmd[3]).read_bytes())
        out_path = cmd[cmd.index("-o") + 1]
        Path(out_path).write_text("# 추출된 마크다운", encoding="utf-8")
        return b""

    monkeypatch.setattr(kordoc_service, "_npx_path", lambda: "npx")
    monkeypatch.setattr(kordoc_service, "_run", _fake_run)

    md = await kordoc_service.hwpx_to_markdown(b"PK\x03\x04HWPXDATA")

    assert md == "# 추출된 마크다운"
    cmd = cmds[0]
    assert cmd[:3] == ["npx", "-y", "kordoc@3.13.0"]
    assert "generate" not in cmd
    assert cmd[3].endswith(".hwpx")
    assert cmd[cmd.index("-o") + 1].endswith(".md")
    assert inputs == [b"PK\x03\x04HWPXDATA"]


# ---------------------------------------------------------------------------
# 실패 처리
# ---------------------------------------------------------------------------

async def test_run_failure_raises_runtimeerror_with_stderr():
    """비정상 종료 시 stderr 내용을 포함한 RuntimeError를 발생시킨다."""
    cmd = [sys.executable, "-c", "import sys; sys.stderr.write('boom-stderr'); sys.exit(2)"]
    with pytest.raises(RuntimeError, match="boom-stderr"):
        await kordoc_service._run(cmd)


async def test_run_timeout_raises_runtimeerror():
    """타임아웃 초과 시 프로세스를 종료하고 RuntimeError를 발생시킨다."""
    cmd = [sys.executable, "-c", "import time; time.sleep(30)"]
    with pytest.raises(RuntimeError, match="초과"):
        await kordoc_service._run(cmd, timeout=0.5)


async def test_markdown_to_hwpx_raises_when_npx_missing(monkeypatch):
    """npx가 없으면 RuntimeError."""
    monkeypatch.setattr(kordoc_service, "_npx_path", lambda: None)
    with pytest.raises(RuntimeError, match="npx"):
        await kordoc_service.markdown_to_hwpx("# 제목")


async def test_markdown_to_hwpx_raises_when_output_empty(monkeypatch):
    """kordoc이 빈 출력 파일을 남기면 RuntimeError."""
    cmds: list = []
    monkeypatch.setattr(kordoc_service, "_npx_path", lambda: "npx")
    monkeypatch.setattr(kordoc_service, "_run", _make_fake_run(cmds, out_bytes=b""))
    with pytest.raises(RuntimeError, match="출력"):
        await kordoc_service.markdown_to_hwpx("# 제목")


# ---------------------------------------------------------------------------
# is_available 캐시
# ---------------------------------------------------------------------------

def test_is_available_caches_which_result(monkeypatch):
    """shutil.which는 1번만 호출되고 이후 결과가 캐시된다."""
    calls = {"n": 0}

    def _fake_which(name):
        calls["n"] += 1
        return "C:/nodejs/npx.cmd"

    monkeypatch.setattr(kordoc_service.shutil, "which", _fake_which)
    assert kordoc_service.is_available() is True
    assert kordoc_service.is_available() is True
    assert calls["n"] == 1


def test_is_available_caches_negative_result(monkeypatch):
    """npx 미설치(None) 결과도 캐시된다."""
    calls = {"n": 0}

    def _fake_which(name):
        calls["n"] += 1
        return None

    monkeypatch.setattr(kordoc_service.shutil, "which", _fake_which)
    assert kordoc_service.is_available() is False
    assert kordoc_service.is_available() is False
    assert calls["n"] == 1


# ---------------------------------------------------------------------------
# 동시 실행 상한 (세마포어)
# ---------------------------------------------------------------------------

async def test_semaphore_limits_concurrent_kordoc_runs(monkeypatch):
    """동시 3개 호출 시 kordoc 서브프로세스는 최대 2개만 동시 진입한다.

    가짜 _run이 진입/이탈 시 활성 카운트를 기록해 최대 동시 진입 수를 캡처한다.
    모듈 세마포어는 다른 테스트의 이벤트 루프에 바인딩되지 않도록 같은 상한의
    새 세마포어로 교체한다(함수는 모듈 속성을 참조하므로 배선 자체는 검증됨).
    """
    assert kordoc_service._KORDOC_MAX_CONCURRENT == 2  # 노트북 백엔드 보호 상한
    monkeypatch.setattr(
        kordoc_service,
        "_KORDOC_SEMAPHORE",
        asyncio.Semaphore(kordoc_service._KORDOC_MAX_CONCURRENT),
    )
    monkeypatch.setattr(kordoc_service, "_npx_path", lambda: "npx")

    state = {"active": 0, "max_active": 0}

    async def _fake_run(cmd: list[str], timeout: float = 120.0) -> bytes:
        state["active"] += 1
        state["max_active"] = max(state["max_active"], state["active"])
        await asyncio.sleep(0.05)  # 동시성 겹침 창 — 세마포어 없으면 3개 동시 진입
        state["active"] -= 1
        out_path = cmd[cmd.index("-o") + 1]
        Path(out_path).write_bytes(b"PK\x03\x04FAKE")
        return b""

    monkeypatch.setattr(kordoc_service, "_run", _fake_run)

    results = await asyncio.gather(
        *[kordoc_service.markdown_to_hwpx(f"# 문서 {i}") for i in range(3)]
    )

    assert all(r == b"PK\x03\x04FAKE" for r in results)
    assert state["max_active"] == 2, (
        f"세마포어 상한 위반: 최대 동시 진입 {state['max_active']}개 (기대 2개)"
    )


# ---------------------------------------------------------------------------
# 실통합 (npx 필요 — 미설치 시 skip)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(shutil.which("npx") is None, reason="npx(Node.js) 미설치 환경")
async def test_real_kordoc_markdown_to_hwpx_produces_zip():
    """실제 npx kordoc@3.13.0 generate 실행 — ZIP 매직넘버(PK) 확인.

    네트워크 캐시된 kordoc을 사용하므로 내부 120초 타임아웃으로 충분하다.
    """
    data = await kordoc_service.markdown_to_hwpx(
        "# 제391회 경기도의회\n\n## 통합테스트위원회 회의록\n\n본문 문단입니다."
    )
    assert isinstance(data, (bytes, bytearray))
    assert data[:2] == b"PK"
