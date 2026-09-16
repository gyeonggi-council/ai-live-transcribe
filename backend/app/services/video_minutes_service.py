# -*- coding: utf-8 -*-
"""영상회의록(KMS) 챕터/안건시간 도출 + HTML 생성.

KMS 영상회의록은 영상 위에 '챕터(안건시간)'를 올린다 — 회의 개의, 안건 상정,
제안설명(국장 OOO), 수석전문위원 검토보고, 질의답변(OO 위원)… 각 구간의 '시작 시각'.
이 서비스는 자막(화자+시각)에서 그 챕터를 도출하고, KMS 등록용 HTML로 만든다.

도출 규칙(상임위 회의 구조):
  - 첫 발언 = 회의 개의.
  - 위원장이 '의사일정 제N항/상정' → 안건 상정 챕터.
  - 질의응답 시작 전 집행부(국장/실장/과장) 발언 = 제안설명 / 검토보고.
  - 질의응답 단계: 새로운 '위원'이 질의를 시작하면 질의답변(그 위원) 챕터
    (그 사이 집행부 답변은 같은 챕터에 포함 — 새 챕터 X).
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from html import escape

from app.services.transcript_export import _group_by_speaker

_EXEC_SUFFIX = re.compile(r"(실장|국장|과장|본부장|단장|처장|차관|센터장|소장|원장|차장)$")
# 안건 '상정'만(가결/선포/종결은 제외 — 그건 안건 종료지 시작이 아님).
_AGENDA_CUE = re.compile(r"(의사일정\s*제\s*\d|상정합니다|상정하겠)")
_AGENDA_CLOSE = re.compile(r"(선포|가결|가게\s*되|종결|이의\s*없)")
_REVIEW_CUE = re.compile(r"(검토\s*보고|수석전문위원)")
# 질의답변 챕터로 인정할 최소 발언 길이(짧은 의사진행 발언이 챕터되는 것 방지).
_MIN_QA_CHARS = 40


def _hms(seconds: float) -> str:
    s = int(seconds or 0)
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def _is_member(speaker: str) -> bool:
    """'OO 위원' (위원장/부위원장 제외)."""
    s = (speaker or "").strip()
    return s.endswith("위원") and not s.endswith("부위원") and "위원장" not in s


def _is_chair(speaker: str) -> bool:
    return "위원장" in (speaker or "")


def _is_exec(speaker: str) -> bool:
    return bool(_EXEC_SUFFIX.search((speaker or "").strip()))


def _agenda_label(text: str, agendas: list[dict] | None) -> str:
    """안건 상정 발언에서 안건 제목 추출(없으면 일반 라벨)."""
    if agendas:
        for a in agendas:
            t = (a.get("title") or "").strip()
            if t and t[:8] in text:
                return f"안건: {t}"
    m = re.search(r"(제\s*\d+\s*항[^.]{0,40})", text)
    if m:
        return "안건 상정 — " + re.sub(r"\s+", " ", m.group(1)).strip()
    return "안건 상정"


def derive_chapters(
    meeting: dict, subtitles: list[dict], agendas: list[dict] | None = None
) -> list[dict]:
    """자막에서 영상회의록 챕터 목록을 도출. 반환: [{label, seconds, hms}]."""
    subs = [s for s in subtitles if s.get("start_time") is not None]
    subs.sort(key=lambda s: s["start_time"])
    groups = _group_by_speaker(subs)
    if not groups:
        return []

    title = (meeting.get("title") or "회의").split("[")[0].strip()
    chapters: list[dict] = [{"label": f"{title} 개의", "seconds": groups[0]["start_time"]}]

    in_qa = False           # 현재 안건의 질의답변 단계 진입 여부
    last_member = None       # 현재 질의 중인 위원(같은 위원 연속은 1챕터)
    proposed: set[str] = set()  # 이 안건에서 제안설명한 집행부(중복 방지)

    for g in groups:
        spk = (g.get("speaker") or "").strip()
        text = " ".join(g.get("texts", []))
        start = g["start_time"]

        # 안건 상정(가결/선포 제외) → 새 안건이므로 제안설명/질의 단계 리셋
        if _is_chair(spk) and _AGENDA_CUE.search(text) and not _AGENDA_CLOSE.search(text):
            chapters.append({"label": _agenda_label(text, agendas), "seconds": start})
            in_qa = False
            last_member = None
            proposed = set()
            continue
        # 질의 시작 전: 검토보고(전문위원) / 제안설명(집행부)
        if not in_qa and len(text) >= _MIN_QA_CHARS:
            is_reviewer = ("전문위원" in spk) or (
                bool(_REVIEW_CUE.search(text)) and not _is_member(spk) and not _is_chair(spk)
            )
            if is_reviewer:
                chapters.append({"label": "수석전문위원 검토보고", "seconds": start})
                continue
            if _is_exec(spk):
                if spk not in proposed:
                    proposed.add(spk)
                    chapters.append({"label": f"제안설명({spk})", "seconds": start})
                continue
        # 질의답변 — 새 위원이 '충분한 길이로' 질의 시작하면 새 챕터
        if _is_member(spk) and len(text) >= _MIN_QA_CHARS:
            if spk != last_member:
                in_qa = True
                last_member = spk
                chapters.append({"label": f"질의답변({spk})", "seconds": start})
            continue

    # 시작 시각 단조 + 너무 가까운(15초 미만) 챕터 병합
    dedup: list[dict] = []
    for c in chapters:
        if dedup and c["seconds"] - dedup[-1]["seconds"] < 15:
            continue
        c["hms"] = _hms(c["seconds"])
        dedup.append(c)
    return dedup


_CHAPTER_PROMPT = """당신은 경기도의회 상임위원회 회의의 영상회의록 '챕터(안건시간)'를 만드는 전문가입니다.
아래는 회의 발언 흐름(그룹 단위: 인덱스 i, 시각 t, 화자 spk, 발언앞부분 txt)입니다.
KMS 영상회의록에 등록할 '주요 구간의 시작 그룹'을 골라 라벨을 다세요.

★다음 챕터는 시스템이 따로 결정적으로 처리하니 당신은 만들지 마세요:
 '<번호>. <안건명>' 안건 상정 / '수석전문위원 검토보고' / '회의 개의' /
 '인사(<이름> 위원)'(개의 직후 위원 인사 라운드) / '부위원장 인사' /
 '간부소개 및 업무보고'·'보고'(국·실 단위 업무·결과보고 시작).
 당신은 각 안건의 '제안설명 / 자료요구 / 질의답변 / 의사진행발언'만 만듭니다
 (특히 위원 질의답변을 빠짐없이).

★라벨 형식은 KMS 실제 양식과 '완전히' 일치해야 합니다(반드시 이 형식):
- 안건을 발의한 의원의 제안설명 → "제안설명(<이름> 의원)"  예: "제안설명(박옥분 의원)"
  ★조례안·건의안은 대개 위원(의원)이 발의하므로, 그 안건 상정 직후 처음 설명하는
   사람이 발의 의원이면 "제안설명(<이름> 의원)" 입니다(이때는 '의원'으로 표기).
- 집행부(국장 등)의 제안설명 → "제안설명(<직책> <이름>)"  예: "제안설명(건설국장 배성호)"
  ★결산·예산 등 집행부 제출 안건은 각 국(局)의 직책자가 설명합니다(이름 모르면 "제안설명(<직책>)").
  ★업무보고·결과보고 안건에서 국장/실장이 보고하는 것은 제안설명이 아니라 시스템이 처리하는
   '간부소개 및 업무보고'이므로 만들지 마세요. 위원장은 제안설명을 하지 않습니다.
- 위원이 질의 시작 → "질의답변(<이름> 위원)"  예: "질의답변(김동영 위원)"
  ★위원회에서 질의하는 사람은 '위원'으로 표기합니다('의원' 아님).
- 위원의 자료 요구 → "자료요구(<이름> 위원)"
  ★위원장이 '자료 요구 시간/자료가 필요하신 의원님' 안내를 한 뒤 이어지는 위원들의 짧은
   자료요청 발언 라운드입니다. 이 라운드의 위원 발언은 질의답변이 아니라 자료요구입니다.
- 위원장이 직접 질의 → "질의답변(위원장 <이름>)"  예: "질의답변(위원장 김태형)"
  ★'저도 한 가지', '잠깐 저도' 등 위원장이 사회 진행이 아니라 실제 질의할 때만.
   짧은 사회·정리·안내 멘트는 챕터가 아닙니다. 직책 '위원장'이 이름 앞입니다.
- 의사진행발언 → "의사진행발언(<이름> 위원)"
  ★위원장이 '의사진행 발언' 요청을 안내한 다음에 하는 그 위원의 발언.

규칙:
- 각 안건마다 순서: (상정-시스템처리) → 제안설명/보고 → (자료요구 라운드) → 질의답변(위원들).
- 질의답변은 '질의하는 위원'이 바뀔 때마다 1개. 그 사이 집행부 답변은 같은 챕터(새 챕터 X).
  같은 위원이 나중에 다시 질의하면 그때마다 또 1개(KMS는 재질의도 별도 챕터로 등록).
- ★질의답변/자료요구 챕터의 위원 이름은 화자(spk) 라벨보다 위원장의 직전 호명
  ("다음은 OOO 위원님", "OOO 의원님 질의/자료 요구해 주시기 바랍니다")을 우선하세요
  — 화자 라벨은 오인식이 있습니다.
- 가결/선포/종결/정회/산회/표결 멘트는 챕터가 아님(건너뜀).
- ★제안설명/질의답변/자료요구의 챕터 시각(i)은 위원장이 "OO 나오셔서 …해 주시기 바랍니다"라고
  호명하는 그룹이 아니라, 그 발언자(위원/집행부/전문위원)가 실제로 말을 시작하는 그룹의 i입니다.

입력: [{"i":0,"t":"00:00:01","spk":"...","txt":"..."}, ...]
출력: [{"i":정수,"label":"..."}, ...]  (시간 순서, 유효한 JSON 배열만)"""


_CHAPTER_PROMPT_PLENARY = """당신은 경기도의회 '본회의'의 영상회의록 '챕터(안건시간)'를 만드는 전문가입니다.
아래는 본회의 발언 흐름(그룹 단위: 인덱스 i, 시각 t, 화자 spk, 발언앞부분 txt)입니다.
KMS 영상회의록에 등록할 '주요 구간의 시작 그룹'을 골라 라벨을 다세요.

★라벨 형식은 KMS 본회의 실제 양식과 '완전히' 일치해야 합니다(반드시 이 형식):
- 개회식 시작(사회자가 "개회식을 시작하겠습니다", 국기에 대한 경례 등) → "개회식"
- 의장 개회사 → "개회사"
- 의장이 본회의 개의("성원이 되었으므로 ... 본회의를 개의하겠습니다") → "회의 개의"
- 신임 간부공무원 소개(도지사/교육감이 소개) → "간부공무원 소개(<직책 이름>)"  예: "간부공무원 소개(도지사 김동연)"
- 의원 5분자유발언 시작(의장이 "OOO 의원 나오셔서 발언" 다음 그 의원 발언) → "5분자유발언(<OOO 의원>)"
  예: "5분자유발언(정동혁 의원)"  (각 의원마다 1개)
- 의장이 안건 상정("의사일정 제N항 ... 상정합니다", 일괄상정 포함) → "<번호>. <안건명>"
  예: "1. 제391회 경기도의회 정례회 회기 결정의 건". 여러 건 일괄상정이면 첫 안건 기준 "5. <안건명>".
- 집행부 제안설명(교육감/도지사 등) → "제안설명(<직책 이름>)"  예: "제안설명(교육감 임태희)"
- 예결위 심사보고(부위원장 등) → "심사보고(<직책 이름>)"  예: "심사보고(예결위 부위원장 김선영)"

규칙:
- 시간 순서대로. 표결/투표/가결 선포/산회/휴회 멘트는 챕터가 아님(직전 안건 챕터에 흡수, 건너뜀).
- "투표해 주시기 바랍니다", "투표를 종료", "재석의원 N명 중 ..." 류는 챕터 X.
- 너무 짧은 의사진행 안내는 챕터로 만들지 마세요. 본회의는 안건이 많으니 '상정 시점'만 챕터로.
- ★간부공무원 소개/5분자유발언/제안설명의 챕터 시각(i)은 의장이 "OOO 나오셔서 …"라고 호명하는
  그룹이 아니라, 그 발언자(도지사/교육감/의원 등)가 실제로 말을 시작하는 그룹의 i입니다.

입력: [{"i":0,"t":"00:00:01","spk":"...","txt":"..."}, ...]
출력: [{"i":정수,"label":"..."}, ...]  (시간 순서, 유효한 JSON 배열만)"""


def _is_plenary(meeting: dict) -> bool:
    """본회의 여부 — 제목/위원회/채널에 '본회의' 단서가 있으면 True."""
    blob = " ".join(
        str(meeting.get(k) or "") for k in ("title", "committee", "channel_id")
    )
    return "본회의" in blob


def _reference_block(agendas: list[dict] | None, glossary: list[str] | None) -> str:
    """챕터 LLM 프롬프트에 붙일 '정확표기 참조' 블록(텍스트 전용, 저비용 캡).

    사람 이름(의원/의장 등)·안건명을 자막 STT 오타가 아니라 공식 표기로 맞추게 한다.
    """
    parts: list[str] = []
    if agendas:
        ag = "; ".join(
            f"{a.get('order_num', i + 1)}. {(a.get('title') or '').strip()}"
            for i, a in enumerate(agendas)
            if (a.get("title") or "").strip()
        )
        if ag:
            parts.append("의사일정(안건명은 이 표기와 정확히 일치): " + ag)
    if glossary:
        from app.services.glossary_service import format_glossary_prompt

        # max_chars로 토큰 비용 캡(의원명이 앞에 있어 절단돼도 이름은 보존됨)
        g = format_glossary_prompt(glossary, max_chars=1200)
        if g:
            parts.append(g)
    if not parts:
        return ""
    return "\n\n★참고(사람 이름·안건명은 반드시 아래 표기와 일치시키세요):\n" + "\n".join(parts)


# 위원장/의장의 '○○ 나오셔서…' 호명 그룹이 아니라 실제 발언자 시점으로 당길 챕터 라벨.
_SPEAKER_ANCHOR_LABELS = ("제안설명", "검토보고", "질의답변", "5분자유발언", "심사보고", "간부공무원")


def _is_chair_speaker(spk: str) -> bool:
    """진행자(위원장/의장) 여부. '허원 위원장'·'위원장 허원' 둘 다 인식, 부위원장은 제외."""
    s = (spk or "").strip()
    return ("의장" in s) or ("위원장" in s and "부위원장" not in s)


def _anchor_to_speaker(chapters: list[dict], groups: list[dict], window: int = 6) -> None:
    """발언자 챕터(제안설명/검토보고/질의답변/5분자유발언 등)의 시각을 보정(in-place).

    위원장/의장이 'OO 나오셔서 …해 주시기 바랍니다'라고 호명하는 그룹이 아니라,
    그 다음 실제 발언자(집행부/전문위원/위원/의원)가 말을 시작하는 그룹으로 당긴다.
    안건 상정·회의 개의·개회사 등 진행자 본인 발언 챕터는 그대로 둔다.
    """
    for c in chapters:
        gi = c.get("_gi")
        if gi is None or not any(k in c.get("label", "") for k in _SPEAKER_ANCHOR_LABELS):
            continue
        if not _is_chair_speaker(groups[gi].get("speaker", "")):
            continue  # 이미 발언자 그룹이면 유지
        for j in range(gi + 1, min(gi + 1 + window, len(groups))):
            if not _is_chair_speaker(groups[j].get("speaker", "")):
                c["seconds"] = groups[j]["start_time"]
                c["_gi"] = j
                break


def _anchor_agendas(agendas: list[dict] | None, subs: list[dict]) -> list[dict]:
    """각 안건을 '상정' 발언 자막에 결정적으로 매칭해 '<번호>. <안건명>' 챕터를 만든다.

    LLM은 안건 상정 챕터를 신뢰성 있게 못 낸다(실측 0/6). 우리는 공식 안건명을
    이미 알므로, 안건 제목의 '긴 연속 문자열'이 들어있는 첫 상정 자막(시간순)에
    결정적으로 앵커링한다 — 그룹이 아닌 개별 자막을 봐 위원장의 긴 개의 발언에
    안건별 상정 시각이 묻히는 문제를 피한다(실측 6/6, 정답 대비 ±12초).
    """
    from difflib import SequenceMatcher

    if not agendas:
        return []
    # '상장'은 '상정'의 잦은 STT 오인식('…의 건을 상장합니다') — 제목 50% 연속매칭이 가드.
    cand = [
        (i, re.sub(r"\s+", "", s.get("text") or ""), s["start_time"])
        for i, s in enumerate(subs)
        if ("상정" in (s.get("text") or "") or "상장" in (s.get("text") or ""))
        and s.get("start_time") is not None
    ]
    out: list[dict] = []
    last_i = -1
    for idx, a in enumerate(agendas):
        title = (a.get("title") or "").strip()
        tnorm = re.sub(r"\s+", "", title)
        if len(tnorm) < 6:
            continue
        for i, ntext, sec in cand:
            if i < last_i:  # i == last_i 허용: 일괄상정(여러 안건이 한 발언에) 대응
                continue
            mb = SequenceMatcher(None, tnorm, ntext).find_longest_match(0, len(tnorm), 0, len(ntext))
            if mb.size / len(tnorm) >= 0.5:  # 제목의 절반 이상이 연속으로 등장 = 상정 순간
                last_i = i
                num = a.get("order_num", idx + 1)
                out.append({"label": f"{num}. {title}", "seconds": float(sec)})
                # 위원 발의 조례안/건의안은 상정 직후 발의 위원이 제안설명을 한다 →
                # 상정 다음 첫 비(非)위원장 발언자를 발의 위원으로 보고 제안설명 챕터를
                # 결정적으로 추가(LLM이 자주 놓치는 부분). 결산/예산(집행부 다수 제안설명)과
                # 부위원장 선임·의석 배정·업무/결과보고(발의 없음 — 뒤 발언은 인사/보고)는 제외.
                if not any(
                    k in title
                    for k in ("결산", "예산", "예비비", "기금", "부위원장", "의석", "보고")
                ):
                    prop = _first_proposer_after(subs, i)
                    if prop:
                        out.append(prop)
                break
    return out


# 검토보고 '실제 시작' 발언 = 전문위원이 보고를 시작하는 문장. 위원장 호명("나오셔서 …
# 주시기 바랍니다")은 제외한다. 화자 라벨에 '전문위원'이 안 붙어(diarize 한계) 내용으로 잡는다.
_REVIEW_OPENER = re.compile(r"검토\s*결과를?\s*보고|검토보고\s*드리|소관.{0,10}검토보고")
_REVIEW_SUMMON = re.compile(r"나오셔서|주시기\s*바랍")


def _anchor_reviews(subs: list[dict]) -> list[dict]:
    """'수석전문위원 검토보고' 챕터를 내용 패턴으로 결정적 도출(전문위원 보고 시작 시각).

    LLM은 검토보고를 적게/위원장 호명 시각으로 잘못 잡는다(실측 3/10). 보고 시작 문장
    ('…검토 결과를 보고 드리겠습니다', '소관 결산 검토보고 드리겠습니다')은 화자 무관하게
    내용으로 정확히 잡힌다(실측 9/10, 정답 대비 ±수초). 호명 문장은 제외.
    """
    out: list[dict] = []
    for s in subs:
        t = s.get("text") or ""
        if s.get("start_time") is None:
            continue
        if _REVIEW_OPENER.search(t) and not _REVIEW_SUMMON.search(t):
            out.append({"label": "수석전문위원 검토보고", "seconds": float(s["start_time"]), "_det": True})
    return out


# 발의 위원 제안설명 — 화자(diarize)가 위원장으로 오배정되는 경우가 많아(실측) 내용으로 잡는다.
#   위원장 호명: "…(대표)발의하신 <이름> 의원님께서는 … 제안설명 … 주시기 바랍니다"
#   발의자 자기소개: "… <이름> 의원입니다"
_PROPOSER_SUMMON = re.compile(r"발의하신\s+([가-힣]{2,4})\s*의원")
_PROPOSER_INTRO = re.compile(r"(?:^|\s)([가-힣]{2,4})\s*의원입니다")


def _first_proposer_after(subs: list[dict], sangjeong_i: int, window: int = 30) -> dict | None:
    """상정 이후 발의 위원의 제안설명 챕터를 '내용'으로 결정적 도출(화자 라벨 무관).

    호명 문장에서 발의자 이름을, 그 다음 줄(발의자 인사)에서 제안설명 시작 시각을 잡는다.
    호명이 없으면 '<이름> 의원입니다' 자기소개로 보강. 못 찾으면 None.
    """
    name = None
    start_sec = None
    end = min(sangjeong_i + 1 + window, len(subs))
    for j in range(sangjeong_i + 1, end):
        t = subs[j].get("text") or ""
        if subs[j].get("start_time") is None:
            continue
        m = _PROPOSER_SUMMON.search(t)
        if m:
            name = m.group(1)
            # 제안설명 시작 = 호명 다음 줄(발의자 인사말)
            if j + 1 < len(subs) and subs[j + 1].get("start_time") is not None:
                start_sec = subs[j + 1]["start_time"]
            else:
                start_sec = subs[j]["start_time"]
            break
        m2 = _PROPOSER_INTRO.search(t)
        if m2:
            name = m2.group(1)
            start_sec = subs[j]["start_time"]
            break
    if name and start_sec is not None:
        return {"label": f"제안설명({name} 의원)", "seconds": float(start_sec)}
    return None


# ─── 업무보고형 회의 결정론 (개의 풀라벨/인사/간부소개·보고/자료요구/의사진행발언) ───
# 회기 첫 회의·업무보고 회의는 KMS 인간 등록본이 인사/자료요구/간부소개 챕터를 쓴다
# (실측: 미래위·기재위 제392회 1차). LLM 어휘만으로는 시각·이름 신뢰성이 낮아,
# 위원장 진행 멘트(호명·안내)와 화자 라벨을 결정론으로 잡고 LLM은 질의답변에 집중시킨다.

_MEMBER_SPK_RE = re.compile(r"^([가-힣]{2,4})\s*(?:부위원장|위원|의원)$")
# 직책 접두는 탐욕 매칭 — '국제협력국장'이 '국장'으로 잘리지 않게(이름과는 공백으로 구분됨).
_EXEC_TITLE_CORE = r"(?:[가-힣A-Za-z0-9]{0,8})(?:국장|실장|원장|본부장|단장|처장|센터장|소장|이사장|사장|차관)"
# 위원장 호명: "김기병 AI국장님은 … 나오셔서 간부소개와 함께 …보고…" (이름+직책님+나오셔서+보고류)
_EXEC_SUMMON_RE = re.compile(rf"([가-힣]{{2,4}})\s*({_EXEC_TITLE_CORE})님")
# 기관장 호명: "김현곤 경기도경제과학진흥원 원장님", "정진수 경기테크노파크 원장님"
# — 기관명이 길고 공백 포함이라 위 패턴으로 못 잡는다. 라벨은 기관명+직책 결합("경기연구원장" 양식).
_INST_SUMMON_RE = re.compile(
    r"([가-힣]{2,4})\s+((?:[가-힣A-Za-z0-9.]{2,12}\s*){1,3}?)(원장|이사장|대표이사|대표)님"
)
# 호명 문두의 진행 필러 — 기관장 호명에서 이름 자리로 오인되는 어절.
_SUMMON_STOPWORDS = {"그럼", "먼저", "다음은", "다음으로", "이어서", "그러면", "계속해서", "다음"}
# 보고자 자기소개: "안녕하십니까. AI국장 김기병입니다." / "네, 기획조정실장 정두석입니다."
_EXEC_INTRO_RE = re.compile(rf"({_EXEC_TITLE_CORE})\s*([가-힣]{{2,4}})입니다")
# 인사 라운드 안내: "여러분 소개와 인사의 시간을 갖도록 하겠습니다"
_GREET_CUE_RE = re.compile(r"소개와\s*인사|인사의?\s*시간|인사\s*나누|상견례")
# 자료요구 라운드 안내: "자료가 필요하신 의원님들 … 자료 요구하는 시간을 갖도록"
_DATAREQ_CUE_RE = re.compile(r"자료\s*(?:를|가)?\s*(?:요구|요청|필요하신)")
# 질의답변 라운드 안내: "다음 질의 답변 시간을 갖도록 하겠습니다" / "질의하실 의원님께서"
_QA_ROUND_CUE_RE = re.compile(r"질의\s*답변?\s*시간|질의하실\s*(?:의원|위원)|질의\s*순서")
_MOTION_CUE_RE = re.compile(r"의사(?:진행|질의)\s*발언")  # '의사질의 발언' = STT 오인식 변형
_SUMMON_NAME_RE = re.compile(r"([가-힣]{2,4})\s*(?:의원|위원)님")


def _fix_stt_digits(text: str) -> str:
    """직책 등 한글 사이에 낀 STT 숫자 오인식 보정(예: '경기연9원장'→'경기연구원장')."""
    return re.sub(r"(?<=[가-힣])9(?=[가-힣])", "구", text or "")


def _member_name_of(spk: str) -> str | None:
    m = _MEMBER_SPK_RE.match((spk or "").strip())
    return m.group(1) if m else None


def _det_open_label(meeting: dict, subs: list[dict]) -> str | None:
    """개의 챕터 풀타이틀: '제N회 (임시회|정례회) 제M차 <위원회> 회의 개의'.

    회의종류는 제목에 없으면 위원장 개의 멘트에서 퍼지 추출(STT '임실'→임시회 견딤).
    """
    from app.services.hwpx_export import _parse_meeting_title

    info = _parse_meeting_title(meeting)
    kind = info.get("kind")
    if not kind:
        for s in subs[:30]:
            t = s.get("text") or ""
            if "개의" not in t and "개회" not in t:
                continue
            if "정례회" in t:
                kind = "정례회"
            elif "임시회" in t:
                kind = "임시회"
            else:  # STT 오인식('임실' 등) — '제N회' 바로 뒤 단어의 첫 글자로 퍼지 판정
                m = re.search(r"제\s*\d+\s*회\s*(임|정)[가-힣]{1,2}\s*제\s*\d+\s*차", t)
                if m:
                    kind = "임시회" if m.group(1) == "임" else "정례회"
            if kind:
                break
    parts = [
        f"제{info['session']}회" if info.get("session") else None,
        kind,
        f"제{info['round']}차" if info.get("round") else None,
        (info.get("committee") or "").strip() or None,
    ]
    core = " ".join(p for p in parts if p)
    return f"{core} 회의 개의" if core else None


def _member_turns_in(subs: list[dict], lo: float, hi: float) -> list[tuple[str, float]]:
    """(lo,hi) 구간에서 위원 화자의 '첫 등장' 턴 [(이름, 시각)] — 인사류 라운드용."""
    turns: list[tuple[str, float]] = []
    seen: set[str] = set()
    for s in subs:
        st = s.get("start_time")
        if st is None or st < lo or st >= hi:
            continue
        name = _member_name_of(s.get("speaker") or "")
        if name and name not in seen:
            seen.add(name)
            turns.append((name, float(st)))
    return turns


def _det_greetings(subs: list[dict], agenda_chaps: list[dict]) -> list[dict]:
    """개의 직후 위원 '인사' 라운드 + 부위원장 선임 뒤 '부위원장 인사' 챕터(결정론).

    인사 라운드 = 위원장 안내 멘트(소개와 인사…)부터 첫 안건 상정까지의 위원 턴들.
    위원 3명 미만이면 인사 라운드가 아닌 회의로 보고 만들지 않는다(오탐 방지).
    """
    out: list[dict] = []
    ag = sorted(
        [c for c in agenda_chaps if re.match(r"^\s*\d+\.", c.get("label", ""))],
        key=lambda c: c["seconds"],
    )
    first_ag = ag[0]["seconds"] if ag else None

    if first_ag:
        cue = None
        for s in subs:
            st = s.get("start_time")
            if st is None or st >= first_ag:
                break
            if _is_chair_speaker(s.get("speaker") or "") and _GREET_CUE_RE.search(s.get("text") or ""):
                cue = float(st)
                break
        if cue is not None:
            turns = _member_turns_in(subs, cue, first_ag)
            if len(turns) >= 3:
                out.extend(
                    {"label": f"인사({n} 위원)", "seconds": sec, "_det": True} for n, sec in turns
                )

    # 부위원장 선임/선출 안건 직후 → 다음 안건 전까지의 위원 턴 = 부위원장 인사
    for i, c in enumerate(ag):
        title = c.get("label", "")
        if "부위원장" in title and ("선임" in title or "선출" in title):
            lo = c["seconds"]
            hi = ag[i + 1]["seconds"] if i + 1 < len(ag) else lo + 900
            for n, sec in _member_turns_in(subs, lo, hi)[:4]:
                out.append({"label": f"부위원장 인사({n} 위원)", "seconds": sec, "_det": True})
            break
    return out


def _det_exec_reports(subs: list[dict]) -> list[dict]:
    """'간부소개 및 업무보고(<직책> <이름>)' / '보고(<직책> <이름>)' 챕터(결정론).

    위원장 호명("OOO <직책>님 … 나오셔서 … [간부소개/업무]보고 …")에서 직책·이름을,
    이어지는 보고자 자기소개("<직책> <이름>입니다")에서 시작 시각을 잡는다.
    화자 라벨은 diarize 오배정이 있어 텍스트 패턴으로만 판단한다(실측 정확).
    """
    out: list[dict] = []
    last_by_name: dict[str, float] = {}
    for i, s in enumerate(subs):
        t = s.get("text") or ""
        st = s.get("start_time")
        if st is None or not _is_chair_speaker(s.get("speaker") or ""):
            continue
        if "나오" not in t:
            continue
        # 기관장 호명(이름+기관명+원장님)을 우선 — 일반 직책 패턴은 긴 기관명을 오분리한다.
        # '그럼/먼저/다음으로' 같은 진행 필러가 이름 자리에 잡히면 그 뒤부터 재탐색.
        mi, pos = None, 0
        while True:
            cand = _INST_SUMMON_RE.search(t, pos)
            if cand is None:
                break
            if cand.group(1) in _SUMMON_STOPWORDS:
                pos = cand.start(1) + len(cand.group(1))  # 필러 어절 전체를 건너뛰고 재탐색
                continue
            mi = cand
            break
        m = _EXEC_SUMMON_RE.search(t)
        if mi and (not m or mi.start() <= m.start()):
            name = mi.group(1)
            inst = re.sub(r"\s+", "", mi.group(2))
            suffix = mi.group(3)
            # '경기연구원'+'원장' → '경기연구원장' (KMS 인간 등록 표기 — 겹치는 '원' 축약)
            if suffix == "원장" and inst.endswith("원"):
                inst = inst[:-1]
            title = inst + suffix
        elif m:
            name, title = m.group(1), m.group(2)
        else:
            continue
        title = _fix_stt_digits(title)
        # 호명 주변(같은 발언 + 60초 내 다음 위원장 발언 1개)에 보고류 단서가 있어야 함
        ctx = t
        for j in range(i + 1, min(i + 4, len(subs))):
            st2 = subs[j].get("start_time")
            if st2 is not None and float(st2) - float(st) > 60:
                break
            if _is_chair_speaker(subs[j].get("speaker") or ""):
                ctx += " " + (subs[j].get("text") or "")
                break
        if not re.search(r"보고|간부", ctx):
            continue
        if name in last_by_name and float(st) - last_by_name[name] < 300:
            continue
        last_by_name[name] = float(st)
        label_kind = "간부소개 및 업무보고" if re.search(r"간부|업무\s*보", ctx) else "보고"
        # 시작 시각 = 보고자 자기소개 자막(없으면 호명 뒤 첫 비위원장 발언, 그마저 없으면 호명+8초)
        start = None
        for j in range(i + 1, len(subs)):
            st2 = subs[j].get("start_time")
            if st2 is None:
                continue
            if float(st2) - float(st) > 240:
                break
            m2 = _EXEC_INTRO_RE.search(subs[j].get("text") or "")
            if m2:
                start = float(st2)
                # 호명은 직책을 줄여 부르는 경우가 많다("박근균 국장님") — 자기소개의
                # 풀 직책("국제협력국장 박근균입니다")이 더 길고 이름이 맞으면 그쪽을 쓴다.
                intro_title = _fix_stt_digits(m2.group(1))
                if (
                    len(intro_title) > len(title)
                    and SequenceMatcher(None, name, m2.group(2)).ratio() >= 0.5
                ):
                    title = intro_title
                break
        if start is None:
            for j in range(i + 1, min(i + 12, len(subs))):
                st2 = subs[j].get("start_time")
                if st2 is not None and not _is_chair_speaker(subs[j].get("speaker") or ""):
                    start = float(st2)
                    break
        if start is None:
            start = float(st) + 8
        out.append({"label": f"{label_kind}({title} {name})", "seconds": start, "_det": True,
                    "_exec": (title, name)})

    # 같은 직책의 보고자 이름이 STT 오인식으로 갈리면(정두석/정주석) 코퍼스 다수결로 통일.
    by_title: dict[str, list[dict]] = {}
    for c in out:
        by_title.setdefault(c["_exec"][0], []).append(c)
    for title, group in by_title.items():
        names = {c["_exec"][1] for c in group}
        if len(names) < 2:
            continue
        sim = [
            (a, b) for a in names for b in names
            if a < b and SequenceMatcher(None, a, b).ratio() >= 0.5
        ]
        if not sim:
            continue
        corpus = " ".join(
            f"{s.get('text') or ''} {s.get('speaker') or ''}" for s in subs
        )
        best = max(names, key=lambda n: corpus.count(n))
        for c in group:
            c["label"] = re.sub(rf"\s{re.escape(c['_exec'][1])}\)$", f" {best})", c["label"])
    for c in out:
        c.pop("_exec", None)
    return out


def _det_round_windows(subs: list[dict]) -> list[tuple[float, float]]:
    """위원장 안내 멘트로 '자료요구 라운드' 시간 창 [(lo, hi)]을 도출.

    자료요구 안내부터 질의답변 안내(또는 최대 20분)까지. 같은 발언에 둘 다 있으면
    자료요구가 우선('질의에 앞서서 자료…' 형태가 일반적).
    """
    events: list[tuple[float, str]] = []
    for s in subs:
        st = s.get("start_time")
        if st is None or not _is_chair_speaker(s.get("speaker") or ""):
            continue
        t = s.get("text") or ""
        if _DATAREQ_CUE_RE.search(t) and re.search(r"시간|(?:의원|위원)님들|하실\s*(?:의원|위원)", t):
            events.append((float(st), "datareq"))
        elif _QA_ROUND_CUE_RE.search(t):
            events.append((float(st), "qa"))
    events.sort()
    windows: list[tuple[float, float]] = []
    open_lo: float | None = None
    for sec, kind in events:
        if kind == "datareq":
            if open_lo is None:
                open_lo = sec
        else:  # qa
            if open_lo is not None:
                windows.append((open_lo, sec))
                open_lo = None
    if open_lo is not None:
        windows.append((open_lo, open_lo + 1200))
    return [(lo, min(hi, lo + 1200)) for lo, hi in windows]


def _det_motions(subs: list[dict]) -> list[tuple[str, float]]:
    """의사진행발언 [(위원 이름, 시작 시각)] — 위원장 안내('의사진행 발언') 기반 결정론."""
    out: list[tuple[str, float]] = []
    for i, s in enumerate(subs):
        st = s.get("start_time")
        t = s.get("text") or ""
        if st is None or not _is_chair_speaker(s.get("speaker") or ""):
            continue
        if not _MOTION_CUE_RE.search(t):
            continue
        if out and float(st) - out[-1][1] < 120:
            continue
        name = None
        m = _SUMMON_NAME_RE.search(t)
        if m:
            name = m.group(1)
        start = None
        for j in range(i + 1, min(i + 10, len(subs))):
            st2 = subs[j].get("start_time")
            if st2 is None:
                continue
            n2 = _member_name_of(subs[j].get("speaker") or "")
            if n2:
                name = name or n2
                start = float(st2)
                break
        if name and start is not None:
            out.append((name, start))
    return out


# 위원장의 턴 종료 멘트: "박상현 부위원장님 고생하셨습니다", "방성환 의원님 수고하셨습니다"
# — 화자 라벨은 오배정이 있어 텍스트만 본다. 이 멘트는 그 위원의 턴이 '방금 끝났음'을 뜻한다.
_TURN_END_RE = re.compile(
    r"([가-힣]{2,4})\s*(?:의원|위원|부위원장)님[,.\s]*(?:정말\s*)?(?:수고|고생)\s*(?:많이\s*)?하셨"
)
_TURN_END_STOPWORDS = {"여러", "우리", "모든", "모두", "다른", "오늘", "위원", "의원"}
# 한 위원의 발언 턴은 실측 ~12분 이내(사용자 확인) — 종료 멘트 역추적 창.
_TURN_MAX_SEC = 780


def _chair_name(subs: list[dict]) -> str | None:
    """화자 라벨에서 위원장 이름 추출(최빈값)."""
    from collections import Counter

    cnt: Counter = Counter()
    for s in subs:
        m = re.match(r"^([가-힣]{2,4})\s*위원장$", (s.get("speaker") or "").strip())
        if m:
            cnt[m.group(1)] += 1
    return cnt.most_common(1)[0][0] if cnt else None


def _backfill_missing_turns(
    chapters: list[dict], subs: list[dict], roster_names: list[str] | None
) -> None:
    """턴 종료 멘트로 누락 질의답변 챕터를 백필(in-place).

    ① 자막 전사 공백(청크 버그)으로 턴 전체가 소실돼도 위원장의 '수고하셨습니다' 멘트가
    살아 있으면, 직전 12분 내 그 위원 챕터가 없을 때 공백 시작점에 턴을 복원한다.
    ② 종료 멘트 뒤 다음 챕터까지 3분 이상 위원장 발언만 이어지면(실질 답변·의견)
    '질의답변(위원장 <이름>)' 챕터를 세운다 — KMS 인간 등록본과 같은 양식.
    """
    if not subs:
        return
    norm_roster = None
    if roster_names:
        from app.services.name_corrector import _match_unique, _norm_roster

        norm_roster = _norm_roster(roster_names)

    def _valid_member(name: str) -> str | None:
        if name in _TURN_END_STOPWORDS:
            return None
        if norm_roster is None:
            return name
        from app.services.name_corrector import _match_unique

        hit = _match_unique(name, norm_roster, 0.5)
        return hit

    cues: list[tuple[str, float]] = []
    for s in subs:
        m = _TURN_END_RE.search(s.get("text") or "")
        if not m or s.get("start_time") is None:
            continue
        name = _valid_member(m.group(1))
        if not name:
            continue
        if cues and cues[-1][0] == name and float(s["start_time"]) - cues[-1][1] < 60:
            continue
        cues.append((name, float(s["start_time"])))

    chair = _chair_name(subs)
    backbone = _hyb_det_qa(subs)  # 위원장 호명("OOO 위원님 질의해 …") — 있으면 가장 정확한 앵커
    for name, t_cue in cues:
        lo = t_cue - _TURN_MAX_SEC
        # ① 이 위원의 챕터가 직전 ~18분 내에 있으면 정상(턴이 12분을 다소 넘기도 함) — 백필 불필요
        if any(
            t_cue - 1080 <= c["seconds"] <= t_cue and f"({name} " in c.get("label", "")
            for c in chapters
        ):
            continue
        window = [s for s in subs if lo <= float(s["start_time"]) <= t_cue]
        insert_at = None
        # 앵커 1순위: 위원장 호명 백본(이름 일치)
        for q in backbone:
            nm = re.search(r"\(([가-힣]{2,4})", q["label"])
            if nm and lo <= q["seconds"] <= t_cue and SequenceMatcher(None, nm.group(1), name).ratio() >= 0.6:
                insert_at = q["seconds"]
                break
        # 2순위: 그 위원의 자기소개("… 박상현입니다" — STT 오타는 퍼지 매칭)
        if insert_at is None:
            for s in window:
                for m2 in re.finditer(r"([가-힣]{2,4})\s*(?:의원|위원)?입니다", s.get("text") or ""):
                    if SequenceMatcher(None, m2.group(1), name).ratio() >= 0.6:
                        insert_at = float(s["start_time"])
                        break
                if insert_at is not None:
                    break
        # 3순위: 직전 턴의 종료 마커('이상입니다/질의 마치…') 직후 — 종료 멘트 근처(자기 턴 종료)는 제외
        if insert_at is None:
            closes = [
                float(s["start_time"])
                for s in window
                if re.search(r"이상입니다|질의\s*를?\s*마치|마치겠습니다", s.get("text") or "")
                and t_cue - float(s["start_time"]) > 60
            ]
            if closes:
                insert_at = max(closes) + 8
        # 4순위: 전사 공백(≥120초) 시작점
        if insert_at is None:
            for a, b in zip(window, window[1:]):
                if float(b["start_time"]) - float(a["start_time"]) >= 120:
                    insert_at = float(a["start_time"]) + 8
                    break
        if insert_at is None:
            continue
        # 같은 이름 챕터가 삽입점 ±300초 내에 있으면 중복 — 삽입하지 않음
        if any(
            abs(c["seconds"] - insert_at) <= 300 and f"({name} " in c.get("label", "")
            for c in chapters
        ):
            continue
        prev = [c["seconds"] for c in chapters if c["seconds"] < t_cue]
        if prev and insert_at <= max(prev) + 30:  # 직전 챕터와 겹침 방지
            continue
        chapters.append({"label": f"질의답변({name} 위원)", "seconds": insert_at, "_det": True})

    # ② 종료 멘트 후 위원장 장발언(다음 챕터까지 3분+, 사이 챕터 없음) → 위원장 챕터.
    #    단순 안내·정회 멘트와 구분하기 위해 직후 3분간 위원장 발언 분량(400자+)을 요구.
    if chair:
        for _name, t_cue in cues:
            nexts = [c["seconds"] for c in chapters if c["seconds"] > t_cue + 5]
            t_next = min(nexts) if nexts else None
            if t_next is None or t_next - t_cue < 180:
                continue
            chair_chars = sum(
                len(s.get("text") or "")
                for s in subs
                if t_cue <= float(s["start_time"]) <= min(t_cue + 180, t_next)
                and _is_chair_speaker(s.get("speaker") or "")
            )
            if chair_chars < 400:
                continue
            chapters.append(
                {"label": f"질의답변(위원장 {chair})", "seconds": t_cue, "_det": True}
            )


def _apply_roster_names(chapters: list[dict], roster_names: list[str] | None) -> None:
    """챕터 라벨의 위원 이름을 위원회 명부로 교정(in-place). 명부 없으면 no-op.

    '질의답변(유기준 위원)'처럼 명부에 없는 오인식 이름을 명부 이름(류기준)으로.
    '(OOO 위원장)' 표기는 KMS 양식 '(위원장 OOO)'로 재배열 후 교정.
    """
    if not chapters:
        return
    for c in chapters:
        lab = c.get("label") or ""
        # KMS 양식: 위원장은 직책이 이름 앞 — "(김태형 위원장)" → "(위원장 김태형)"
        lab = re.sub(r"\(([가-힣]{2,4})\s*위원장\)", r"(위원장 \1)", lab)
        lab = _fix_stt_digits(lab) if ("간부소개" in lab or lab.startswith("보고(") or "제안설명" in lab) else lab
        c["label"] = lab
    if not roster_names:
        return
    from app.services.name_corrector import _match_unique, _norm_roster, correct_member_names

    norm_roster = _norm_roster(roster_names)
    roster_exact = {n for n, _ in norm_roster}

    # 두음법칙 STT 오인식(류기준→'유기준'): 첫 글자 복원 시 명부와 '정확히' 일치할 때만 교체.
    # (퍼지매칭은 유기준↔{류기준,유호준} 동점이라 no-invention 원칙상 교정 불가 — 이 규칙이 유일 경로)
    _DUEUM = {"유": "류", "이": "리", "임": "림", "나": "라", "노": "로", "누": "루", "양": "량", "연": "련", "예": "례"}

    def _dueum_fix(m: "re.Match[str]") -> str:
        name = m.group(1)
        if name not in roster_exact and name[0] in _DUEUM:
            variant = _DUEUM[name[0]] + name[1:]
            if variant in roster_exact:
                return f"({variant} {m.group(2)})"
        return m.group(0)

    def _fix_chair(m: "re.Match[str]") -> str:
        hit = _match_unique(m.group(1), norm_roster, 0.5)
        return f"(위원장 {hit or m.group(1)})"

    for c in chapters:
        lab = re.sub(r"\(([가-힣]{2,4})\s*(위원|의원)\)", _dueum_fix, c["label"])
        lab = correct_member_names(lab, roster_names)
        lab = re.sub(r"\(위원장\s*([가-힣]{2,4})\)", _fix_chair, lab)
        c["label"] = lab


async def derive_chapters_llm(
    meeting: dict,
    subtitles: list[dict],
    agendas: list[dict] | None = None,
    glossary: list[str] | None = None,
    roster_names: list[str] | None = None,
) -> list[dict]:
    """LLM(텍스트 전용)으로 영상회의록 챕터를 도출(회의 흐름 이해 → 제안설명/검토보고까지 정확).

    glossary(회의 의원명·의안명·용어)를 주면 이름/안건명을 공식 표기로 맞춘다(저비용 캡).
    실패하면 휴리스틱(derive_chapters)으로 폴백.
    """
    import json
    from app.services.text_speaker_service import _call_llm

    subs = [s for s in subtitles if s.get("start_time") is not None]
    subs.sort(key=lambda s: s["start_time"])
    groups = _group_by_speaker(subs)
    if not groups:
        return []

    items = [
        {"i": idx, "t": _hms(g["start_time"]),
         "spk": (g.get("speaker") or "").strip(),
         "txt": " ".join(g.get("texts", []))[:70]}
        for idx, g in enumerate(groups)
    ]
    base = _CHAPTER_PROMPT_PLENARY if _is_plenary(meeting) else _CHAPTER_PROMPT
    prompt = base + _reference_block(agendas, glossary)
    try:
        result = await _call_llm(prompt, json.dumps(items, ensure_ascii=False))
    except Exception:
        return derive_chapters(meeting, subtitles, agendas)

    chapters: list[dict] = []
    for item in result:
        if not isinstance(item, dict):
            continue
        i = item.get("i")
        label = (item.get("label") or "").strip()
        if not isinstance(i, int) or not (0 <= i < len(groups)) or not label:
            continue
        chapters.append({"label": label, "seconds": groups[i]["start_time"], "_gi": i})
    if not chapters:
        return derive_chapters(meeting, subtitles, agendas)

    # 발언자 챕터를 위원장 호명 시점 → 실제 발언자 시점으로 보정
    _anchor_to_speaker(chapters, groups)

    # 안건 상정 챕터는 결정적으로 앵커링한다(상임위 한정 — 본회의는 프롬프트가 직접 처리).
    # LLM은 안건 상정 챕터를 신뢰성 있게 못 내므로(실측 0/6), LLM이 낸 안건성 챕터는
    # 버리고 공식 안건명 기반 결정적 챕터로 대체한다.
    if not _is_plenary(meeting):
        # LLM이 자주 틀리는(또는 결정론이 소유한) 챕터는 버리고 결정적 도출로 대체한다.
        def _llm_keep(label: str) -> bool:
            lab = label.strip()
            if re.match(r"^\s*\d+\.", lab) or "검토보고" in lab or "개의" in lab:
                return False
            if lab.startswith(("인사", "부위원장", "간부소개", "보고(")):
                return False
            if "제안설명" in lab and "위원장" in lab:  # 위원장은 제안설명을 하지 않음(오분류)
                return False
            return True

        chapters = [c for c in chapters if _llm_keep(c.get("label", ""))]
        det = _anchor_agendas(agendas, subs)  # 안건 + 발의 위원 제안설명(_det 표시)
        for c in det:
            c["_det"] = True
        det.extend(_anchor_reviews(subs))  # 수석전문위원 검토보고(_det 표시)
        det.extend(_det_exec_reports(subs))  # 간부소개 및 업무보고/보고(_det)
        det.extend(_det_greetings(subs, det))  # 인사/부위원장 인사(_det)
        open_label = _det_open_label(meeting, subs) or "회의 개의"
        det.append({"label": open_label, "seconds": float(subs[0]["start_time"]), "_det": True})
        chapters.extend(det)

        # 턴 종료 멘트 기반 백필: 전사 공백으로 소실된 위원 턴 + 위원장 실질 답변 챕터
        _backfill_missing_turns(chapters, subs, roster_names)

        # 자료요구 라운드 창 안의 위원 질의답변은 자료요구로 재라벨(위원장 안내 기반)
        windows = _det_round_windows(subs)
        for c in chapters:
            lab = c.get("label", "")
            if (
                lab.startswith("질의답변(")
                and "위원장" not in lab
                and any(lo <= c["seconds"] < hi for lo, hi in windows)
            ):
                c["label"] = "자료요구(" + lab[len("질의답변("):]

        # 의사진행발언: 근접한 같은 위원 챕터를 재라벨(없으면 삽입).
        # 위원장 안내 큐(결정론)가 없는 LLM 단독 의사진행발언은 과잉 생성이라 제거.
        motions = _det_motions(subs)
        chapters = [
            c for c in chapters
            if not c.get("label", "").startswith("의사진행발언(")
            or any(abs(c["seconds"] - sec) <= 150 for _, sec in motions)
        ]
        for name, sec in motions:
            # LLM이 이미 같은 의사진행발언을 냈으면 시각만 결정론 값으로 보정(중복 삽입 방지)
            existing = [
                c for c in chapters
                if c.get("label", "").startswith("의사진행발언(") and abs(c["seconds"] - sec) <= 150
            ]
            if existing:
                for c in existing:
                    if name in c["label"]:
                        c["seconds"] = sec
                continue
            target = None
            for c in chapters:
                lab = c.get("label", "")
                if not lab.startswith(("질의답변(", "자료요구(")):
                    continue
                if abs(c["seconds"] - sec) <= 75 and name in lab:
                    target = c
                    break
            if target is None:
                near = [
                    c for c in chapters
                    if c.get("label", "").startswith(("질의답변(", "자료요구("))
                    and abs(c["seconds"] - sec) <= 40
                ]
                target = near[0] if near else None
            if target is not None:
                target["label"] = f"의사진행발언({name} 위원)"
                target["seconds"] = sec
            else:
                chapters.append({"label": f"의사진행발언({name} 위원)", "seconds": sec, "_det": True})

    # 동시각 충돌 시 결정적 챕터가 이기도록 정렬(LLM 검토보고가 제안설명 시각을 오라벨하는 경우 대비)
    chapters.sort(key=lambda c: (c["seconds"], 0 if c.get("_det") else 1))
    dedup: list[dict] = []
    for c in chapters:
        is_agenda = bool(re.match(r"^\s*\d+\.", c.get("label", "")))
        # 안건 챕터는 일괄상정(동시각)도 모두 보존. 그 외 근접(<10초) 중복만 제거.
        if dedup and not is_agenda and c["seconds"] - dedup[-1]["seconds"] < 10:
            continue
        c["hms"] = _hms(c["seconds"])
        c.pop("_gi", None)
        c.pop("_det", None)
        dedup.append(c)
    # 위원 이름을 위원회 명부로 교정 + 위원장 표기(위원장 <이름>) 정규화
    _apply_roster_names(dedup, roster_names)
    return dedup


# ─── 속기록+결정론 하이브리드 (임시속기록 라벨 + AI자막 시각) ──────────────
# 결정론 시간 백본용 보조 패턴(집행부 제안설명/회의 개의/질의 호명).
_HYB_EXEC_TITLE = r"[가-힣]*(?:실장|국장|본부장|단장|처장|과장|센터장|소장|원장|차장|팀장|부장|담당관|차관)"
_HYB_EXEC_SUMMON = re.compile(r"(?:[가-힣]{2,4}\s+)?" + _HYB_EXEC_TITLE + r"[^.]*제안\s*설명[^.]*(?:주시|바랍)")
_HYB_EXEC_INTRO = re.compile(_HYB_EXEC_TITLE + r"\s+[가-힣]{2,4}입니다")
_HYB_OPEN = re.compile(r"개의(?:하겠|를 선포)")
# 이름 + 의원/위원님 + '질의(해/하…)' — 질의가 호칭 뒤에 와야 하므로 일반호출('질의하실
# 의원님께서는')은 자연 제외. 위원회별 어미 차이(질의해 주십시오/하시겠/하시기) 포괄.
_HYB_QA = re.compile(r"([가-힣]{2,4})\s*(?:의원|위원)님[,.]?\s*질의(?:해|하)")
_HYB_QA2 = re.compile(r"질의하실래요\?\s*([가-힣]{2,4})\s*(?:의원|위원)님")
_HYB_QA_INTRO = re.compile(r"(?:^|\s)([가-힣]{2,4})\s*(?:의원|위원)입니다[.,]\s*[^.]{0,40}질의")
# 검토보고 위원장 호명(내용 시작 패턴이 위원회마다 달라 호명으로도 검출).
_HYB_REVIEW_SUMMON = re.compile(r"수석전문위원.{0,15}검토보고|검토보고\s*순서")
_HYB_REVIEW_START = re.compile(r"전문위원\s*[가-힣]{2,4}입니다|지금부터.{0,30}(?:보고|검토)")

_STENO_CHAPTER_PROMPT = """다음은 경기도의회 상임위원회 회의의 속기록(임시회의록)입니다.
이를 바탕으로 KMS 영상회의록에 등록할 '챕터' 목록을 시간 순서대로 만드세요.
각 챕터는 {"label":..., "anchor":...}:
- label(KMS 양식): 회의 개의 / "<번호>. <안건 공식 제목>"(속기록 표기 그대로) /
  제안설명(<이름> 의원) / 제안설명(<직책> <이름>) / 수석전문위원 검토보고 /
  질의답변(<이름> 위원)(질의 위원이 바뀔 때마다 빠짐없이) / 수정제안(<이름> 위원) / 인사(<이름> 위원)
- anchor: 그 챕터 시작 발언의 처음 15~25자를 속기록에서 그대로 복사(시간 정렬용 닻).
규칙: 시간순. 각 안건은 상정→제안설명→검토보고→질의답변(위원들). 표결/가결/선포/정회/산회/질의종결은 제외.
집행부 제안설명은 결산에서 국(局)마다. 이름·직책·안건명은 속기록 표기 그대로(정확).
출력: [{"label":...,"anchor":...}, ...] 유효한 JSON 배열만."""


def _hyb_ctype(label: str) -> str:
    if re.match(r"^\s*\d+\.", label):
        return "agenda"
    if "개의" in label:
        return "open"
    if "제안설명" in label:
        return "propose"
    if "검토보고" in label:
        return "review"
    if "질의" in label:
        return "qa"
    return "other"


def _hyb_backbone_times(subs: list[dict], agendas: list[dict] | None) -> dict:
    """결정론으로 백본(open/agenda/propose/review/qa) 시각만 추출 — AI자막 실시각이라 정확.

    qa도 위원장 호명(자막)으로 결정론 검출해 정확한 시각을 쓴다(속기 anchor 정렬의
    '들쑥날쑥' 회피). 같은 위원 재질의로 중복 시각은 제거.
    """
    # propose/qa는 (이름, 시각) — 라벨을 '순서'가 아니라 '이름'으로 매칭(백본 누락 시 라벨
    # 밀림 방지). open/agenda/review는 시각 리스트(순서 매칭).
    times = {"open": [], "agenda": [], "propose": [], "review": [], "qa": []}
    for s in subs:
        if _HYB_OPEN.search(s.get("text") or ""):
            times["open"].append(float(s["start_time"]))
            break
    for c in _anchor_agendas(agendas, subs):  # 안건 + 의원 발의 제안설명
        if re.match(r"^\s*\d+\.", c["label"]):
            times["agenda"].append(c["seconds"])
        else:
            nm = re.search(r"\(([^)]+)\)", c["label"])
            name = re.sub(r"\s*(의원|위원)\s*$", "", nm.group(1)).strip() if nm else ""
            times["propose"].append((name, c["seconds"]))
    for i, s in enumerate(subs):  # 집행부 제안설명(직책)
        t = s.get("text") or ""
        if _HYB_EXEC_SUMMON.search(t):
            anc = float(s["start_time"])
            tm = re.search(_HYB_EXEC_TITLE, t)
            name = tm.group(0) if tm else ""
            for j in range(i + 1, min(i + 6, len(subs))):
                m2 = _HYB_EXEC_INTRO.search(subs[j].get("text") or "")
                if m2:
                    name = re.search(_HYB_EXEC_TITLE, m2.group(0)).group(0)
                    anc = float(subs[j]["start_time"])
                    break
            times["propose"].append((name, anc))
    rev = [c["seconds"] for c in _anchor_reviews(subs)]  # 내용 시작 패턴
    for i, s in enumerate(subs):  # 위원장 호명 → 다음 전문위원 시작에 앵커(위원회 무관)
        if _HYB_REVIEW_SUMMON.search(s.get("text") or ""):
            for j in range(i + 1, min(i + 8, len(subs))):
                if _HYB_REVIEW_START.search(subs[j].get("text") or ""):
                    rev.append(float(subs[j]["start_time"]))
                    break
    for sec in sorted(rev):  # 근접(<30s) 중복 제거
        if not times["review"] or sec - times["review"][-1] > 30:
            times["review"].append(sec)
    for q in _hyb_det_qa(subs):
        nm = re.search(r"\(([^)]+)\)", q["label"])
        name = re.sub(r"\s*(의원|위원)\s*$", "", nm.group(1)).strip() if nm else ""
        if not times["qa"] or q["seconds"] - times["qa"][-1][1] > 5:
            times["qa"].append((name, q["seconds"]))
    times["open"].sort()
    times["agenda"].sort()
    times["review"].sort()
    times["propose"].sort(key=lambda x: x[1])
    times["qa"].sort(key=lambda x: x[1])
    return times


def _hyb_name_match(steno_label: str, pool: list[tuple], used: list[bool]) -> int:
    """속기 라벨의 이름을 결정론 (이름,시각) 풀에 매칭 → 인덱스(없으면 -1)."""
    nm = re.search(r"\(([^)]+)\)", steno_label)
    sname = re.sub(r"\s*(의원|위원|위원장)\s*$", "", nm.group(1)).strip() if nm else ""
    if not sname:
        return -1
    best_j, best = -1, 0.45
    for j, (dname, _t) in enumerate(pool):
        if used[j] or not dname:
            continue
        sc = SequenceMatcher(None, sname, dname).ratio()
        if sname in dname or dname in sname or any(w and w in dname for w in sname.split()):
            sc = max(sc, 0.9)
        if sc > best:
            best, best_j = sc, j
    return best_j


def _hyb_det_qa(subs: list[dict]) -> list[dict]:
    out = []
    for s in subs:
        t = s.get("text") or ""
        m = _HYB_QA.search(t) or _HYB_QA2.search(t) or _HYB_QA_INTRO.search(t)
        if m:
            out.append({"label": f"질의답변({m.group(1)} 위원)", "seconds": float(s["start_time"])})
    return out


async def _hyb_steno_extract(steno_text: str) -> list[dict]:
    """속기록을 LLM(텍스트)으로 읽어 정확한 라벨/순서의 챕터 추출."""
    import json as _json

    import httpx

    from app.core.config import settings

    async with httpx.AsyncClient(timeout=120.0) as cli:
        r = await cli.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {settings.openai_api_key}", "Content-Type": "application/json"},
            json={"model": settings.openai_model,
                  "messages": [{"role": "system", "content": _STENO_CHAPTER_PROMPT},
                               {"role": "user", "content": steno_text[:130000]}],
                  "max_completion_tokens": 8000},
        )
    r.raise_for_status()
    c = r.json()["choices"][0]["message"]["content"].strip()
    a, b = c.find("["), c.rfind("]")
    if a >= 0 and b > a:
        c = c[a:b + 1]
    try:
        return _json.loads(c)
    except _json.JSONDecodeError:
        return [_json.loads(m.group(0)) for m in re.finditer(r"\{[^{}]*\}", c)]


def _hyb_align(anchor: str, subs: list[dict], lo: float, hi: float) -> float | None:
    an = re.sub(r"\s+", "", anchor or "")
    if len(an) < 6:
        return None
    best, best_sec = 0.6, None  # 높은 임계값 — 자신 있는 매칭만(불확실하면 None→드롭)
    for s in subs:
        st = s.get("start_time")
        if st is None or st < lo or st > hi:
            continue
        nt = re.sub(r"\s+", "", s.get("text") or "")
        if not nt:
            continue
        mb = SequenceMatcher(None, an, nt).find_longest_match(0, len(an), 0, len(nt))
        sc = mb.size / len(an)
        if sc > best:
            best, best_sec = sc, float(st)
    return best_sec


async def derive_chapters_hybrid(
    meeting: dict, subtitles: list[dict], agendas: list[dict] | None, steno_text: str
) -> list[dict]:
    """임시속기록(정확 라벨) + AI자막(정확 시각) 하이브리드 챕터 도출.

    백본(안건/제안설명/검토보고)은 속기 라벨 + 결정론 시각. 그 사이 질의답변/인사는
    속기 순서를 백본 시각 구간에 정렬 + 결정론 질의답변 보강. 실패 시 derive_chapters_llm 폴백.
    """
    from difflib import SequenceMatcher  # noqa: F811 (지역 보장)

    subs = sorted([s for s in subtitles if s.get("start_time") is not None], key=lambda s: s["start_time"])
    if not subs:
        return []
    try:
        items = await _hyb_steno_extract(steno_text)
    except Exception:
        return await derive_chapters_llm(meeting, subtitles, agendas)
    if not items:
        return await derive_chapters_llm(meeting, subtitles, agendas)

    backbone = _hyb_backbone_times(subs, agendas)
    ptr = {"open": 0, "agenda": 0, "review": 0}
    used_prop = [False] * len(backbone["propose"])
    used_qa = [False] * len(backbone["qa"])
    for it in items:
        label = (it.get("label") or "").strip()
        ty = _hyb_ctype(label)
        it["_t"] = ty
        if ty in ("open", "agenda", "review") and ptr[ty] < len(backbone[ty]):
            it["_sec"] = backbone[ty][ptr[ty]]  # 순서 매칭(이름 없는 유형)
            ptr[ty] += 1
        elif ty == "propose":
            j = _hyb_name_match(label, backbone["propose"], used_prop)  # 이름 매칭
            if j >= 0:
                used_prop[j] = True
                it["_sec"] = backbone["propose"][j][1]
            else:
                it["_sec"] = None
        elif ty == "qa":
            j = _hyb_name_match(label, backbone["qa"], used_qa)
            if j >= 0:
                used_qa[j] = True
                it["_sec"] = backbone["qa"][j][1]
            else:
                it["_sec"] = None
        else:
            it["_sec"] = None
    n = len(items)
    last_end = float(subs[-1]["start_time"])
    for idx, it in enumerate(items):
        if it["_sec"] is not None:
            continue
        lo = max((items[j]["_sec"] for j in range(idx - 1, -1, -1) if items[j]["_sec"] is not None), default=0.0)
        hi = min((items[j]["_sec"] for j in range(idx + 1, n) if items[j]["_sec"] is not None), default=last_end)
        # 백본/det-qa로 시각을 못 받은 항목(재질의·인사 등)은 앵커를 자막에 정렬.
        # 자신 있게 매칭되면 그 시각, 아니면 앞뒤 확정 챕터 사이 중간점에 둔다.
        # (드롭하면 '누락'이 많아진다는 피드백 반영 — 확정 이웃 사이라 시각도 합리적.)
        aligned = _hyb_align(it.get("anchor") or it.get("label"), subs, lo + 1, hi)
        it["_sec"] = aligned if aligned is not None else (lo + (hi - lo) * 0.5)

    chapters = [
        {"label": it["label"].strip(), "seconds": it["_sec"]}
        for it in items
        if (it.get("label") or "").strip()
    ]
    # 속기 LLM이 놓친 질의답변은 결정론 검출(AI자막 실시각)로 보강 — 시각 정확.
    for j, (name, sec) in enumerate(backbone["qa"]):
        if used_qa[j] or not name:
            continue
        if any("질의" in c["label"] and name in c["label"] and abs(c["seconds"] - sec) < 90 for c in chapters):
            continue
        chapters.append({"label": f"질의답변({name} 위원)", "seconds": sec})
    chapters.sort(key=lambda c: c["seconds"])
    out: list[dict] = []
    seen_open = False
    for c in chapters:
        is_ag = bool(re.match(r"^\s*\d+\.", c["label"]))
        if "회의 개의" in c["label"]:  # 개의/속개 오라벨 중복 — 첫 1개만
            if seen_open:
                continue
            seen_open = True
        if out and not is_ag and c["seconds"] - out[-1]["seconds"] < 8 and out[-1]["label"] == c["label"]:
            continue
        # 동시각/역순 클러스터(간부 일괄소개 등)는 1초씩 벌려 등록 순서 유지(안건 일괄상정은 보존)
        if out and not is_ag and c["seconds"] <= out[-1]["seconds"]:
            c["seconds"] = out[-1]["seconds"] + 1
        c["hms"] = _hms(c["seconds"])
        out.append(c)
    return out


def export_video_minutes_html(meeting: dict, chapters: list[dict]) -> str:
    """챕터 목록을 KMS '영상회의록' 뷰어 HTML로 생성.

    회의 vod_url이 있으면 영상을 임베드하고, 각 챕터를 클릭하면 그 시각으로 이동·재생한다
    (KMS 영상회의록과 동일 동작). 재생 중인 챕터는 강조된다. vod_url이 없으면 표만 출력.
    표에는 '초(startPS)' 열을 두어 관리자가 KMS '안건 시간 등록'에 그대로 입력할 수 있게 한다.
    """
    title = escape(meeting.get("title") or "회의")
    date = escape(str(meeting.get("meeting_date") or ""))
    vod_url = (meeting.get("vod_url") or "").strip()
    has_video = bool(vod_url)

    rows = "\n".join(
        f'      <tr data-seconds="{int(c["seconds"])}">'
        f'<td class="no">{i + 1}</td>'
        f'<td class="label">{escape(c["label"])}</td>'
        f'<td class="time">{c["hms"]}</td>'
        f'<td class="sec">{int(c["seconds"])}</td></tr>'
        for i, c in enumerate(chapters)
    )

    css = (
        "  body{font-family:'맑은 고딕',sans-serif;margin:0;color:#222;background:#fafafa;}\n"
        "  .wrap{max-width:900px;margin:0 auto;padding:20px;}\n"
        "  h1{font-size:18px;margin:0 0 4px;} .meta{color:#666;margin-bottom:14px;font-size:13px;}\n"
        "  .player{position:sticky;top:0;background:#000;z-index:5;}\n"
        "  video{width:100%;max-height:56vh;display:block;background:#000;}\n"
        "  table{border-collapse:collapse;width:100%;margin-top:14px;}\n"
        "  th,td{border:1px solid #ddd;padding:7px 10px;font-size:14px;}\n"
        "  th{background:#f0f4f8;}\n"
        "  td.no{text-align:center;width:44px;color:#888;}\n"
        "  td.time{text-align:center;width:96px;font-variant-numeric:tabular-nums;color:#1d4ed8;}\n"
        "  td.sec{text-align:right;width:84px;font-variant-numeric:tabular-nums;color:#666;}\n"
        "  tr[data-seconds].clickable{cursor:pointer;}\n"
        "  tr[data-seconds].clickable:hover{background:#eef4ff;}\n"
        "  tr[data-seconds].active{background:#dbeafe;}\n"
        "  tr[data-seconds].active td.label{font-weight:700;}\n"
        "  .hint{color:#888;font-size:12px;margin-top:10px;line-height:1.6;}\n"
        "  @media print{.player,.hint{display:none;}}\n"
    )

    if has_video:
        video_block = (
            f'  <div class="player"><video id="vodPlayer" src="{escape(vod_url)}" '
            'controls preload="metadata" playsinline></video></div>\n'
        )
        head_hint = "각 행을 클릭하면 영상이 그 시각으로 이동·재생됩니다. "
    else:
        video_block = '  <p class="hint">※ 이 회의에 등록된 영상(vod_url)이 없어 표만 표시합니다.</p>\n'
        head_hint = ""

    # 클릭→시킹 + 재생중 챕터 강조 (media 요소는 재생에 CORS 불필요 → 로컬 파일에서도 동작)
    script = (
        "  <script>\n"
        "  (function () {\n"
        "    var v = document.getElementById('vodPlayer');\n"
        "    var rows = Array.prototype.slice.call(document.querySelectorAll('tr[data-seconds]'));\n"
        "    if (!v) return;\n"
        "    rows.forEach(function (r) {\n"
        "      r.classList.add('clickable');\n"
        "      r.addEventListener('click', function () {\n"
        "        var s = parseFloat(r.getAttribute('data-seconds')) || 0;\n"
        "        v.currentTime = s; v.play().catch(function () {});\n"
        "        if (v.scrollIntoView) v.scrollIntoView({ behavior: 'smooth', block: 'start' });\n"
        "      });\n"
        "    });\n"
        "    v.addEventListener('timeupdate', function () {\n"
        "      var t = v.currentTime, active = -1, i;\n"
        "      for (i = 0; i < rows.length; i++) {\n"
        "        if ((parseFloat(rows[i].getAttribute('data-seconds')) || 0) <= t + 0.25) active = i;\n"
        "      }\n"
        "      for (i = 0; i < rows.length; i++) rows[i].classList.toggle('active', i === active);\n"
        "    });\n"
        "  })();\n"
        "  </script>\n"
    )

    return (
        '<!DOCTYPE html>\n<html lang="ko"><head><meta charset="utf-8">\n'
        f"<title>{title} — 영상회의록</title>\n<style>\n{css}</style></head><body>\n"
        '<div class="wrap">\n'
        f"  <h1>{title} — 영상회의록</h1>\n"
        f'  <div class="meta">일시: {date} · 안건/발언 구간 {len(chapters)}개 · KMS 등록용</div>\n'
        f"{video_block}"
        "  <table>\n"
        "    <thead><tr><th>순서</th><th>구분 / 안건 / 발언</th><th>시:분:초</th>"
        "<th>초(startPS)</th></tr></thead>\n"
        f"    <tbody>\n{rows}\n    </tbody>\n"
        "  </table>\n"
        f'  <p class="hint">{head_hint}KMS 영상회의록 \'안건 시간 등록\'에는 각 행의 '
        "'구분/안건/발언'(제목)과 '초(startPS)'(또는 시:분:초)를 입력하세요.</p>\n"
        "</div>\n"
        f"{script}"
        "</body></html>"
    )


def export_video_minutes_js(meeting: dict, chapters: list[dict]) -> str:
    """KMS '영상회의록 편집기' 콘솔에 붙여넣어 챕터 테이블을 자동입력하는 JS 스크립트 생성.

    KMS 편집기는 `dynaTableAddRecord(N)`으로 빈 챕터 행을 추가하고, 각 행 td 안에
    name=m_angun(안건 텍스트)/m_hour/m_min/m_sec/m_pos input이 있다. 저장 시 checkfrm이
    hms로 m_pos(총초)를 재계산한다. 본 스크립트는 그 행들을 챕터 데이터로 채운다.
    (사용자 결정: 라벨 전체를 m_angun에, 발언자 칸은 비움.)
    """
    import json

    payload = []
    for c in chapters:
        sec = int(c.get("seconds") or 0)
        payload.append(
            {
                "a": (c.get("label") or "").strip(),
                "h": f"{sec // 3600:02d}",
                "m": f"{(sec % 3600) // 60:02d}",
                "s": f"{sec % 60:02d}",
                "pos": sec,
            }
        )
    data = json.dumps(payload, ensure_ascii=False)
    title = (meeting.get("title") or "회의").strip().replace("*/", "* /")

    return (
        "/* 경기도의회 영상회의록 KMS 자동입력 스크립트\n"
        f" * 회의: {title}\n"
        f" * 챕터(안건시간) {len(payload)}개 — AI 자막에서 자동 도출\n"
        " * 사용법: KMS '관리자 _ 영상회의록 편집기'에서 해당 영상을 연 뒤,\n"
        " *   브라우저 콘솔(F12 > Console)에 이 스크립트 전체를 붙여넣고 Enter.\n"
        " *   안건 텍스트와 시:분:초가 자동 입력됩니다. 검토 후 KMS에서 저장하세요. */\n"
        "(function () {\n"
        f"  var CH = {data};\n"
        "  if (typeof dynaTableAddRecord !== 'function' || !document.getElementById('dynamictable')) {\n"
        "    alert('이 스크립트는 KMS 영상회의록 편집기 페이지에서 실행하세요.\\n"
        "(#dynamictable / dynaTableAddRecord 를 찾을 수 없습니다.)');\n"
        "    return;\n"
        "  }\n"
        "  function setVal(td, name, val) {\n"
        "    var el = td.querySelector(\"input[name='\" + name + \"']\");\n"
        "    if (el) { el.value = val; }\n"
        "  }\n"
        "  var tbl = document.getElementById('dynamictable');\n"
        "  // 이미 등록된 행과 '라벨+시각(±15초)'이 같은 챕터는 건너뛴다(재실행/기본행 중복 방지).\n"
        "  // 라벨만 보면 같은 위원의 재질의(동일 라벨, 다른 시각)까지 걸러버린다 — 2026-08-04 실편집기 검증.\n"
        "  var existing = Array.prototype.map.call(\n"
        "    tbl.querySelectorAll('tr'),\n"
        "    function (r) {\n"
        "      var a = r.querySelector(\"input[name='m_angun']\");\n"
        "      if (!a) { return null; }\n"
        "      var g = function (n) { var el = r.querySelector(\"input[name='\" + n + \"']\"); return parseInt((el && el.value) || '0', 10) || 0; };\n"
        "      return { lab: (a.value || '').replace(/\\s+/g, ''), t: g('m_hour') * 3600 + g('m_min') * 60 + g('m_sec') };\n"
        "    }\n"
        "  ).filter(Boolean);\n"
        "  CH = CH.filter(function (c) {\n"
        "    var lab = c.a.replace(/\\s+/g, '');\n"
        "    return !existing.some(function (e) { return e.lab === lab && Math.abs(e.t - c.pos) <= 15; });\n"
        "  });\n"
        "  dynaTableAddRecord(CH.length);\n"
        "  var tds = tbl.querySelectorAll('td');\n"
        "  var startIdx = Math.max(0, tds.length - CH.length);\n"
        "  var filled = 0;\n"
        "  for (var i = 0; i < CH.length; i++) {\n"
        "    var td = tds[startIdx + i];\n"
        "    if (!td) { continue; }\n"
        "    var c = CH[i];\n"
        "    setVal(td, 'm_angun', c.a);\n"
        "    setVal(td, 'm_hour', c.h);\n"
        "    setVal(td, 'm_min', c.m);\n"
        "    setVal(td, 'm_sec', c.s);\n"
        "    setVal(td, 'm_pos', c.pos);\n"
        "    filled++;\n"
        "  }\n"
        "  alert(filled + '개 안건시간을 입력했습니다. 검토 후 KMS에서 저장하세요.');\n"
        "})();\n"
    )
