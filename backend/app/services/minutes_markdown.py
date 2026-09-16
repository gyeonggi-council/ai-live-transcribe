"""공식 전자회의록 마크다운 빌더 (kordoc 중간층).

hwpx_export._build_official_paragraphs가 만드는 공식 전자회의록(KMS)과
동일한 구조·내용을 마크다운으로 재현한다. 이 마크다운은
- 미리보기/편집(GET minutes-markdown) 중간층으로 쓰이고,
- kordoc(회의록 preset)에 넣어 공문서 서식 hwpx를 재생성한다.

동일성 보장 전략: hwpx의 문단 목록(_build_official_paragraphs)을 그대로 import해
(텍스트, bold, center) 튜플을 마크다운 문법으로 변환만 한다 — 로직을 복제하지
않으므로 hwpx와 내용이 어긋날 수 없다(수정 금지 모듈은 import만 사용).

변환 규칙:
- 제목 3줄(제N회 경기도의회(정례회) / OO위원회 회의록 / 제N호)
  → 각각 '#', '##', '###' 헤딩 (문단 목록의 고정 위치 0~2번).
- bold 문단('의사일정', '심사된 안건', '○ 화자', 출석 명단 헤더) → **굵게**.
- 나머지(본문/일시/장소/(개의)/안건 항목)는 일반 단락.
- 빈 문자열 문단(시각적 여백)은 생략 — 마크다운은 빈 줄로 단락을 구분한다.
"""

from __future__ import annotations

from app.services.hwpx_export import _build_official_paragraphs

#: _build_official_paragraphs 출력에서 제목 3줄의 고정 인덱스 → 헤딩 레벨
_HEADING_BY_INDEX = {0: "#", 1: "##", 2: "###"}


def build_official_markdown(
    meeting: dict, grouped: list, agendas: list | None = None
) -> str:
    """회의 정보/화자그룹/안건에서 공식 전자회의록 마크다운을 생성한다.

    grouped는 transcript_export._group_by_speaker() 산출 구조
    ({speaker, start_time, end_time, texts})를 그대로 받는다.
    같은 화자 연속 시 '○ 화자' 머리표 생략 등 모든 규칙은
    hwpx_export._build_official_paragraphs와 동일하다.
    """
    paras = _build_official_paragraphs(meeting, grouped, agendas)

    blocks: list[str] = []
    for idx, (text, bold, _center) in enumerate(paras):
        if not text:
            continue  # 시각적 여백 문단 — 마크다운은 빈 줄이 단락 구분
        heading = _HEADING_BY_INDEX.get(idx)
        if heading is not None:
            blocks.append(f"{heading} {text}")
        elif bold:
            blocks.append(f"**{text}**")
        else:
            blocks.append(text)

    return "\n\n".join(blocks) + "\n"
