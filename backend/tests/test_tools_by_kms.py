# -*- coding: utf-8 -*-
"""exe 데이터 연계 API 테스트 — GET /api/tools/extractor/meetings/by-kms/{midx}/segments

# @TASK C2-by-kms - exe 가 KMS midx 만으로 의원별 발언구간을 조회 (공개, 무인증)

exe 는 로그인이 없으므로 인증 헤더 없이 호출한다.
- 미등록 midx → 404 (웹서비스에 먼저 VOD 등록 안내)
- 의원 구간을 세울 수 없음 → 409 (인덱스 경고 문구 그대로)
- 성공 → meeting 메타 + total_duration + speakers(발언구간)

★2026-09-10: 이 API 는 웹 /clips 와 **같은** build_clip_index 를 쓴다.
예전에는 여기만 build_speaker_segments(같은 화자 라벨의 연속 자막 병합)를 써서
설치형과 웹이 서로 다른 구간을 보여 줬다. 그 회귀를 막는 것이 이 파일의 목적이다.
KMS 호출은 전부 스텁이다 — 테스트가 실제 kms.ggc.go.kr 로 나가면 남의 서버 상태에
따라 결과가 흔들린다(실제로 그래서 옛 테스트가 깨졌다).
"""

import uuid
from typing import Generator

import pytest
from fastapi.testclient import TestClient

from app.api.tools import clip_index_to_speakers, speaker_label
from app.core.database import get_supabase
from app.main import app
from app.services import kms_angun_service as kms
from tests.conftest import MockSupabaseClient

MEETING_ID = str(uuid.uuid4())
KMS_MIDX = 138176
MEETING_ROW = {
    "id": MEETING_ID,
    "title": "제391회 테스트 위원회",
    "meeting_date": "2026-06-15",
    "kms_midx": str(KMS_MIDX),  # kms_midx 는 문자열 컬럼
    "vod_url": "https://kms.ggc.go.kr/mp4/test.mp4",
    "duration_seconds": 3600,
}


def _sub(start: float, end: float, text: str, speaker: str | None,
         kind: str = "ai") -> dict:
    """Supabase 응답 형태의 자막 dict를 생성합니다."""
    return {
        "id": str(uuid.uuid4()),
        "meeting_id": MEETING_ID,
        "start_time": start,
        "end_time": end,
        "text": text,
        "speaker": speaker,
        "kind": kind,
    }


def _angun(pos: float, title: str, code: str = "", mbr: str = "M") -> dict:
    """KMS 공식 인덱스 항목 (parse_angun 출력 형태)."""
    return {"pos": pos, "time": "00:00:00", "title": title, "code": code, "mbr": mbr}


@pytest.fixture(autouse=True)
def _no_kms_network(monkeypatch) -> Generator[list, None, None]:
    """KMS 공식 인덱스를 스텁한다. 테스트가 리스트에 넣은 항목이 응답이 된다."""
    items: list = []

    async def fake_fetch_angun(midx, *, client=None):
        return list(items)

    async def fake_fetch_member_name(mcode, *, client=None):
        return None

    monkeypatch.setattr(kms, "fetch_angun", fake_fetch_angun)
    monkeypatch.setattr(kms, "fetch_member_name", fake_fetch_member_name)
    yield items


def _make_client(meetings: list[dict], subtitles: list[dict]) -> TestClient:
    """meetings/subtitles 데이터를 가진 모킹 클라이언트를 만듭니다."""
    mock = MockSupabaseClient(
        table_data={"meetings": meetings, "subtitles": subtitles}
    )
    app.dependency_overrides[get_supabase] = lambda: mock
    return TestClient(app)


class TestToolsByKms:
    """GET /api/tools/extractor/meetings/by-kms/{midx}/segments 테스트"""

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_official_index_is_returned(self, _no_kms_network):
        """공식 KMS 인덱스가 있으면 그것으로 의원 구간을 낸다 (웹 /clips 와 같은 원천)."""
        _no_kms_network.extend([
            _angun(0, "제391회 임시회 제1차 테스트 위원회 회의 개의", mbr="C"),
            _angun(100, "질의답변(김지호 위원)", code="12057"),
            _angun(400, "질의답변(전자영 위원)", code="11032"),
        ])
        client = _make_client([MEETING_ROW], [])

        # 인증 헤더 없음 — exe 는 로그인하지 않는다
        response = client.get(
            f"/api/tools/extractor/meetings/by-kms/{KMS_MIDX}/segments"
        )

        assert response.status_code == 200
        data = response.json()
        assert data["source"] == "official"

        meeting = data["meeting"]
        assert meeting["id"] == MEETING_ID
        assert meeting["kms_midx"] == str(KMS_MIDX)

        speakers = {s["speaker"]: s for s in data["speakers"]}
        # exe(applyAiSpeakers)가 "이름 직책" 을 정규식으로 가른다 — 라벨 형태가 계약이다
        assert "김지호 위원" in speakers
        assert "전자영 위원" in speakers
        seg = speakers["김지호 위원"]["segments"][0]
        assert seg["start_time"] == 100
        assert seg["end_time"] == 400          # 끝 = 다음 항목의 시작
        assert seg["duration"] == 300
        assert "김지호" in seg["text_preview"]

    def test_matches_web_clip_index(self, _no_kms_network):
        """웹 /clips 가 쓰는 build_clip_index 결과와 구간이 정확히 같다.

        두 화면이 갈라지지 않게 하는 것이 이 API 변경의 목적이므로 직접 대조한다.
        """
        import asyncio

        from app.services.clip_draft_index import build_clip_index

        _no_kms_network.extend([
            _angun(0, "회의 개의", mbr="C"),
            _angun(60, "질의답변(김지호 위원)", code="12057"),
            _angun(500, "질의답변(전자영 위원)", code="11032"),
        ])
        mock = MockSupabaseClient(table_data={"meetings": [MEETING_ROW], "subtitles": []})
        app.dependency_overrides[get_supabase] = lambda: mock
        client = TestClient(app)

        api_speakers = client.get(
            f"/api/tools/extractor/meetings/by-kms/{KMS_MIDX}/segments"
        ).json()["speakers"]
        web_index = asyncio.run(build_clip_index(mock, MEETING_ROW))

        assert api_speakers == clip_index_to_speakers(web_index)
        assert [s["speaker"] for s in api_speakers] == [
            speaker_label(g) for g in web_index["speakers"] if g["segments"]
        ]

    def test_prefers_the_record_that_has_a_vod(self, _no_kms_network):
        """같은 midx 에 회의 레코드가 둘이면 영상이 붙은 쪽을 고른다.

        일정 선등록본(VOD 없음)과 KMS 동기화본이 갈라진 실제 사례가 있다
        (2026-09-04 393회 1차 본회의). 웹에서 담당자가 고를 수 있는 것은 영상이 있는 쪽이다.
        """
        stub = {**MEETING_ROW, "id": str(uuid.uuid4()), "vod_url": None}
        _no_kms_network.append(_angun(10, "질의답변(김지호 위원)", code="12057"))
        client = _make_client([stub, MEETING_ROW], [])

        response = client.get(
            f"/api/tools/extractor/meetings/by-kms/{KMS_MIDX}/segments"
        )

        assert response.status_code == 200
        assert response.json()["meeting"]["id"] == MEETING_ID

    def test_unknown_midx_404(self):
        """미등록 midx 는 404 + 'VOD 등록' 안내 메시지를 반환한다."""
        client = _make_client([], [])

        response = client.get(
            "/api/tools/extractor/meetings/by-kms/999999/segments"
        )

        assert response.status_code == 404
        assert "웹서비스에 먼저 VOD 등록" in response.json()["detail"]

    def test_live_subtitles_only_409(self, _no_kms_network):
        """공식 인덱스도 AI 자막도 없으면 409 — 사유는 인덱스 경고 문구 그대로.

        실시간 자막은 시각이 STT 시계라 VOD 와 어긋나 의원 구간에 쓰지 않는다.
        """
        live_only = [
            _sub(0, 5, "라이브 자막 1", None, kind="live"),
            _sub(5, 10, "라이브 자막 2", None, kind="live"),
        ]
        client = _make_client([MEETING_ROW], live_only)

        response = client.get(
            f"/api/tools/extractor/meetings/by-kms/{KMS_MIDX}/segments"
        )

        assert response.status_code == 409
        assert "AI 자막" in response.json()["detail"]


class TestSpeakerLabel:
    """exe 계약 — speakers[].speaker 는 exe 정규식이 가르는 '이름 직책' 이어야 한다."""

    def test_known_roles_are_appended(self):
        assert speaker_label({"name": "김지호", "role": "위원"}) == "김지호 위원"
        assert speaker_label({"name": "유종상", "role": "위원장"}) == "유종상 위원장"

    def test_unknown_role_is_dropped(self):
        """'인권담당관' 같은 꼬리말을 붙이면 exe 가 라벨 전체를 이름으로 읽어 폴더명이 깨진다."""
        assert speaker_label({"name": "최현정", "role": "인권담당관"}) == "최현정"

    def test_missing_name(self):
        assert speaker_label({"name": "", "role": "위원"}) == "(미지정)"


class TestClipIndexToSpeakers:
    """clip-index → exe 계약 변환 (키 이름이 계약이다 — 옛 설치본도 이 키를 읽는다)."""

    def test_maps_keys_and_skips_empty_groups(self):
        index = {
            "speakers": [
                {"name": "김지호", "role": "위원", "total_seconds": 300.0,
                 "segments": [{"start": 100.0, "end": 400.0, "seconds": 300.0,
                               "title": "질의답변(김지호 위원)"}]},
                {"name": "구간없음", "role": "위원", "total_seconds": 0.0, "segments": []},
            ]
        }
        out = clip_index_to_speakers(index)
        assert len(out) == 1
        assert out[0] == {
            "speaker": "김지호 위원",
            "total_time": 300.0,
            "segment_count": 1,
            "segments": [{"start_time": 100.0, "end_time": 400.0,
                          "duration": 300.0, "text_preview": "질의답변(김지호 위원)",
                          "named": True}],
        }

    def test_duration_falls_back_to_end_minus_start(self):
        index = {"speakers": [{"name": "김지호", "role": "위원", "total_seconds": 0.0,
                               "segments": [{"start": 10.0, "end": 25.0, "title": ""}]}]}
        assert clip_index_to_speakers(index)[0]["segments"][0]["duration"] == 15.0

    def test_named_flag_survives_the_conversion(self):
        """의사진행·안건 항목(named=False)은 웹 /clips 처럼 기본 선택에서 빠져야 한다.

        v1.11 설치형이 이 값으로 기본 선택을 정한다 — 빠지면 안건 공지까지 잘린다.
        """
        index = {"speakers": [{"name": "김지호", "role": "위원", "total_seconds": 20.0,
                               "segments": [
                                   {"start": 0.0, "end": 10.0, "seconds": 10.0,
                                    "title": "의사일정 제1항", "named": False},
                                   {"start": 10.0, "end": 20.0, "seconds": 10.0,
                                    "title": "질의답변(김지호 위원)", "named": True},
                               ]}]}
        segs = clip_index_to_speakers(index)[0]["segments"]
        assert [s["named"] for s in segs] == [False, True]

    def test_named_defaults_to_true_when_absent(self):
        """AI 초안 경로는 named 를 항상 True 로 넣지만, 없더라도 발언으로 본다."""
        index = {"speakers": [{"name": "김지호", "role": "위원", "total_seconds": 10.0,
                               "segments": [{"start": 0.0, "end": 10.0, "title": "t"}]}]}
        assert clip_index_to_speakers(index)[0]["segments"][0]["named"] is True
