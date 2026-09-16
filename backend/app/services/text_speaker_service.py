# -*- coding: utf-8 -*-
"""텍스트 기반 화자 귀속 — 자막 본문의 단서로 화자를 추정 (오디오 재처리 없음).

오디오 diarize(2-패스, 고비용·익명 '화자 N') 대신, 이미 만든 자막 텍스트 +
그 회의 위원회 명부를 gpt 한 번으로 읽어 '실제 의원명/집행부 직책'을 부여한다.

장점(사용자 요구: 2-패스 없이 비용 추가 없이 화자구분):
  - 비용: 오디오 재처리 0. 텍스트 LLM ~$0.01~0.05 (오디오 diarize 대비 ~1/100).
  - 실명: 위원회 명부(예: '이제영 위원장') + 집행부 직책(예: '디지털혁신과장').
  - 전역 일관성: 전체 대본 문맥으로 신원을 추적 (diarize는 호출별 상대 라벨이라
    화자번호가 뒤섞임 — 그 한계가 없음).
  - 단서: 호명("OO 위원 질의하세요"), 자기소개("OO과장 OOO입니다"),
    직책 호칭, 위원장 진행 멘트, 질의/답변 턴 교대.

안전: 위원 이름은 명부에 있는 사람만 — 없는 위원 생성 금지(프롬프트 제약 +
사후 검증). 집행부는 직책 문자열만 허용.
"""

from __future__ import annotations

import json
import logging
import re
import time

import httpx

from app.core.config import settings
from app.services.staff_roster_service import STAFF_TITLE_SUFFIXES
from app.services.staff_roster_service import staff_bindings as _staff_roster_bindings

logger = logging.getLogger(__name__)

# 한 번에 보낼 자막 수(출력 토큰 절단 방지). 배치 간 '직전 화자'를 넘겨 연속성 유지.
_BATCH = 80
# 배치 간 드리프트 완화용 — 직전 배치 마지막 N라인의 확정 (텍스트, 화자)를 다음 배치에 전달.
_OVERLAP_LINES = 5
# 집행부/사무처 직책으로 인정하는 접미사(의원 아님). ★'위원'/'위원장'은 제외 —
# 'OO 위원'은 반드시 명부 위원이어야 하므로(없는 위원 생성 금지) 이름 검증으로만 통과.
# 기존 접미사(하위호환 유지) ∪ staff_roster_service.STAFF_TITLE_SUFFIXES(파서 단일
# 원천) 병합 — 과거 이 정규식에 기획관/지사/교육감/감사관/청장/관장이 빠져 있어
# '권주성 경제기획관' 같은 유효 화자가 거부되던 결함 방지. 긴 접미사 우선 alternation.
_LEGACY_OFFICIAL_SUFFIXES = (
    "국장", "과장", "실장", "단장", "본부장", "센터장", "소장", "원장",
    "처장", "차관", "차장", "팀장", "부장", "담당관", "보좌관", "전문위원",
)
_OFFICIAL_SUFFIX = re.compile(
    "("
    + "|".join(
        sorted(
            set(_LEGACY_OFFICIAL_SUFFIXES) | set(STAFF_TITLE_SUFFIXES),
            key=len,
            reverse=True,
        )
    )
    + ")$"
)

# 자기소개 라인의 이름↔직책 결합 추출용 (양방향). 직책 = 접두어 ≥2자 + 직책 접미사.
_BINDING_TITLE = (
    r"[가-힣]{2,10}"
    r"(?:국장|과장|실장|단장|본부장|센터장|소장|원장|처장|차관|차장|팀장|부장|담당관|기획관|전문위원)"
)
# "건설국장 배성호입니다" (직책 먼저)
_TITLE_NAME_INTRO = re.compile(r"(?<![가-힣])(" + _BINDING_TITLE + r")\s+([가-힣]{2,4})입니다")
# "배성호 건설국장입니다" (이름 먼저)
_NAME_TITLE_INTRO = re.compile(r"(?<![가-힣])([가-힣]{2,4})\s+(" + _BINDING_TITLE + r")입니다")


def extract_title_bindings(subtitles: list[dict]) -> dict[str, str]:
    """자기소개("건설국장 배성호입니다"/"배성호 건설국장입니다" 양방향)에서
    이름↔직책 결합을 추출. 반환: {"배성호": "건설국장", ...}.

    staff_roster(속기록 출석명단)가 없거나 불완전할 때의 보완 원천이며,
    같은 이름이 양쪽에 있으면 자막 자기소개가 우선한다(호출측에서 union).
    """
    bindings: dict[str, str] = {}
    for s in subtitles:
        text = s.get("text") or ""
        for title, name in _TITLE_NAME_INTRO.findall(text):
            if not title.endswith("위원장"):  # '부위원장 OOO입니다'는 위원 — 집행부 아님
                bindings[name] = title
        for name, title in _NAME_TITLE_INTRO.findall(text):
            if not title.endswith("위원장"):
                bindings[name] = title
    return bindings


def extract_executive_titles(subtitles: list[dict], top: int = 6) -> list[str]:
    """자막에서 실제 등장한 집행부 직책(경제실장·미래성장산업국장 등)을 빈도순으로 추출.

    LLM에 '답변 화자 후보'로 주입해 위원 질문 다음의 답변을 그 집행부로 귀속시킨다
    (없는 부서를 지어내지 않게, 자막에 실재한 직책만). 접두어 ≥1자 + 직책 접미사라
    바라 '실장님'(접두어 없음)은 제외 → 호칭 잡음 배제.
    """
    pat = re.compile(r"([가-힣]{2,10}(?:실장|국장|과장|본부장|단장|처장|차관|센터장|소장|원장))")
    counts: dict[str, int] = {}
    for s in subtitles:
        for m in pat.findall(s.get("text") or ""):
            # 위원장/부위원장은 별도 처리 — 제외
            if m.endswith("위원장") or m in ("위원장", "부위원장"):
                continue
            counts[m] = counts.get(m, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: -kv[1])
    return [t for t, _ in ranked[:top]]


def _build_system_prompt(
    committee_name: str,
    roster: list[dict],
    exec_titles: list[str] | None = None,
    staff_bindings: dict[str, str] | None = None,
) -> str:
    by_role: dict[str, list[str]] = {}
    for m in roster:
        by_role.setdefault(m.get("role") or "위원", []).append(m["name"])
    lines = []
    for role in ("위원장", "부위원장", "간사", "위원"):
        if by_role.get(role):
            lines.append(f"- {role}: {', '.join(by_role[role])}")
    roster_block = "\n".join(lines) or "(명부 없음)"
    first_member = (roster[0]["name"] if roster else "OOO")
    exec_block = ""
    if exec_titles:
        exec_block = (
            "\n\n이 회의에 실제 등장한 집행부 직책(= 답변 화자 후보, 이 중에서만 고르세요): "
            + ", ".join(exec_titles)
        )
    staff_block = ""
    if staff_bindings:
        ex_name, ex_title = next(iter(staff_bindings.items()))
        pairs = ", ".join(f"{title}={name}" for name, title in staff_bindings.items())
        staff_block = f"""

집행부 출석 공무원(직책=실명): {pairs}
- 답변 화자는 "{ex_name} {ex_title}"처럼 '실명+직책'으로 표기하세요(위 명단의 실명만 사용).
- ★질문의 소관과 직책의 소관이 일치해야 합니다(예: 도로·건설 질문의 답변은 건설 소관 직책,
  대중교통 질문의 답변은 교통 소관 직책 — 소관이 다른 직책으로 답변을 귀속하지 마세요)."""
    return f"""당신은 경기도의회 '{committee_name}' 회의록의 화자를 식별하는 전문가입니다.

참석 위원(이 위원회 소속 — 아래 명단 외의 위원 이름을 절대 만들지 마세요):
{roster_block}{exec_block}{staff_block}

집행부(의원 아님)는 직책으로 표기하되, ★이 회의 자막에 실제로 등장한 직책만 쓰세요
(위 '답변 화자 후보' 또는 자기소개에서 확인된 것). 이 회의에 안 나온 부서·직책을 절대
지어내지 마세요(다른 위원회 소관 부서명 금지). 직책을 못 찾으면 "집행부".

★질의응답(Q&A) 턴 구분이 가장 중요합니다(이걸 틀리면 안 됩니다):
- 위원의 '질문'(의문문: "~나요?","~습니까?","~죠?","어디 있어요?","되는 건가요?")
  다음에 오는 '답변'(단정형: "~입니다","~알고 있습니다","~하겠습니다","~됐습니다",
  "~드리겠습니다")은 거의 항상 '집행부'입니다. 질문한 위원을 답변 화자로 잇지 마세요.
- 집행부 직책이 자막에 나왔으면 그 직책(예: "경제실장")으로, 못 찾으면 "집행부"로 표기.
- 답변 뒤 다시 질문/지적이 나오면 직전의 그 위원으로 돌아갑니다(위원 ↔ 집행부 교대).

회의 진행 구조와 단서:
- 위원장이 회의를 진행하고 위원을 호명하며 의결을 선포합니다.
- "OO 위원 질의하세요/질의해 주시기 바랍니다" 다음 발언의 화자는 그 위원.
- "OO실장/국장/과장 OOO입니다", "안녕하십니까 OOO입니다" 같은 자기소개 라인의 화자는 그 사람.
- 진행 멘트("다음은", "의사일정 제N항", "상정합니다", "의결", "선포", "이의 없으십니까",
  "가결되었음", "질의 종결")는 위원장.
- 제안설명/결산보고/답변은 집행부(자막에 등장한 그 실장/국장/과장, 없으면 "집행부").
- ★위원 간 교대는 반드시 위원장 호명("다음 OO 위원 질의")을 경유합니다 —
  호명 없이 위원A→위원B로 직접 전환 금지(중간에 위원장 진행 멘트가 있어야 함).
- 단서가 없으면 직전 화자 유지 — 단, 위 Q&A 교대가 우선입니다.

각 라인의 화자를 '명부 이름 + 직위'(예: "{first_member} 위원") 또는 자막에 등장한
집행부 직책으로 표기하세요. 추정이 안 되면 직전 화자를 유지.

입력: JSON 배열 [{{"i": 정수, "t": "발언"}}]  (직전 화자: {{prev}})
출력: 입력의 모든 i에 대해 [{{"i": 정수, "s": "화자"}}]. 유효한 JSON 배열만 출력."""


async def _call_llm(system_prompt: str, user_content: str) -> list[dict]:
    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY가 설정되지 않았습니다.")
    t0 = time.monotonic()
    ok = False
    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                json={
                    "model": settings.openai_model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_content},
                    ],
                    "max_completion_tokens": 4096,
                },
            )
            resp.raise_for_status()
        ok = True
    finally:
        try:
            from app.api.admin import api_tracker
            api_tracker.record("openai", (time.monotonic() - t0) * 1000, ok)
        except Exception:
            pass
    content = resp.json()["choices"][0]["message"]["content"].strip()
    if content.startswith("```"):
        content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        logger.warning("화자귀속 JSON 파싱 실패: %s", content[:200])
        return []


def _valid_speaker(
    s: str, roster_names: set[str], staff_names: frozenset[str] = frozenset()
) -> str | None:
    """화자 문자열을 검증 — 명부 위원(이름 포함), staff 명부 공무원(이름 포함),
    또는 집행부 직책만 허용. 아니면 None. (staff_names 미전달 시 기존 동작 그대로)"""
    s = (s or "").strip()
    if not s:
        return None
    # 명부 위원 이름이 포함되면 OK (예: "이제영 위원장")
    for nm in roster_names:
        if nm and nm in s:
            return s
    # 명부 밖인데 위원/위원장으로 끝나면 거부 — 없는 위원 생성 금지.
    # (★'위원장'은 '원장'으로 끝나 집행부 직책으로 오인될 수 있어 먼저 차단.
    #  staff 공무원의 '위원' 사칭도 여기서 걸러진다)
    if re.search(r"(부?위원장|위원)$", s):
        return None
    # staff 명부(출석 공무원) 이름이 포함되면 OK (예: "배성호 건설국장")
    for nm in staff_names:
        if nm and nm in s:
            return s
    # 집행부/사무처 직책 패턴이면 OK
    if _OFFICIAL_SUFFIX.search(s):
        return s
    return None


async def attribute_speakers(
    subtitles: list[dict],
    roster: list[dict],
    committee_name: str,
    staff: list[dict] | None = None,
) -> int:
    """자막에 텍스트 기반 화자를 부여(in-place). 반환: 화자 부여된 자막 수.

    subtitles: [{text, speaker, ...}] (start_time 순 정렬 권장)
    roster: [{name, role}] — 그 회의 위원회 명부
    staff: staff_roster 항목([{name, full_title, ...}]) — 집행부 실명 귀속용.
           None(기본)이면 기존 동작 그대로(하위호환).
    """
    if not subtitles:
        return 0
    exec_titles = extract_executive_titles(subtitles)
    # staff 바인딩 = staff_roster ∪ 자막 자기소개 (자기소개가 우선 — 실제 발화가 원천)
    bindings: dict[str, str] = {}
    if staff is not None:
        bindings.update(_staff_roster_bindings(staff))
        bindings.update(extract_title_bindings(subtitles))
    system_prompt = _build_system_prompt(
        committee_name, roster, exec_titles, staff_bindings=bindings or None
    )
    roster_names = {m["name"] for m in roster if m.get("name")}
    staff_name_set = frozenset(bindings)
    by_index = {i: s for i, s in enumerate(subtitles)}
    prev_speaker = "위원장"
    labeled = 0
    # 배치 간 드리프트 완화: 직전 배치 마지막 라인들의 확정 (텍스트, 화자) 컨텍스트
    overlap_context: list[dict] = []

    for start in range(0, len(subtitles), _BATCH):
        batch = list(range(start, min(start + _BATCH, len(subtitles))))
        payload = [{"i": i, "t": (by_index[i].get("text") or "")[:300]} for i in batch]
        parts = []
        if overlap_context:
            parts.append(
                "직전 배치에서 확정된 마지막 라인들 (문맥 참고용 — 재라벨 금지, 출력에 포함하지 마세요):"
            )
            parts.append(json.dumps(overlap_context, ensure_ascii=False))
            parts.append("이번 배치:")
        parts.append(json.dumps(payload, ensure_ascii=False))
        sp = system_prompt.replace("{prev}", prev_speaker)
        try:
            result = await _call_llm(sp, "\n".join(parts))
        except Exception as e:
            logger.warning("화자귀속 배치 실패(%d~): %s", start, e)
            continue
        got = {}
        for item in result:
            if isinstance(item, dict) and isinstance(item.get("i"), int):
                got[item["i"]] = item.get("s", "")
        # 적용 + 연속성(단서 없으면 직전 화자 유지)
        for i in batch:
            cand = _valid_speaker(got.get(i, ""), roster_names, staff_name_set)
            if cand:
                prev_speaker = cand
            by_index[i]["speaker"] = prev_speaker
            if prev_speaker:
                labeled += 1
        overlap_context = [
            {"t": (by_index[i].get("text") or "")[:200], "s": by_index[i].get("speaker")}
            for i in batch[-_OVERLAP_LINES:]
        ]
    return labeled
