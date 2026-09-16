"""회의록 내보내기 서비스

STT 자막 데이터를 구조화된 회의록 형식으로 변환합니다.
지원 형식: Markdown (회의록), SRT (자막), JSON (연계용), Official (공식 회의록)
"""

from datetime import datetime, timedelta


def _format_time_hms(seconds: float) -> str:
    """초를 HH:MM:SS 형식으로 변환합니다."""
    td = timedelta(seconds=int(seconds))
    total_seconds = int(td.total_seconds())
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def _format_time_srt(seconds: float) -> str:
    """초를 SRT 타임코드 형식 (HH:MM:SS,mmm)으로 변환합니다."""
    total_ms = int(seconds * 1000)
    hours, remainder = divmod(total_ms, 3600000)
    minutes, remainder = divmod(remainder, 60000)
    secs, ms = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


MAX_GROUP_DURATION = 150  # 2.5분 — 긴 발언을 가독성 있게 분할


def _group_by_speaker(
    subtitles: list[dict],
    max_group_duration: int | None = MAX_GROUP_DURATION,
) -> list[dict]:
    """연속된 같은 화자의 발언을 하나로 병합합니다.

    같은 화자라도 그룹 시작으로부터 max_group_duration초(기본 2.5분) 이상 경과하면
    새 그룹으로 분할합니다. None이면 강제 분할 없이 연속 발언 전체를 유지합니다.
    """
    if not subtitles:
        return []

    grouped = []
    current = {
        "speaker": subtitles[0].get("speaker") or "발언자 미확인",
        "start_time": subtitles[0]["start_time"],
        "end_time": subtitles[0]["end_time"],
        "texts": [subtitles[0]["text"]],
    }

    for sub in subtitles[1:]:
        speaker = sub.get("speaker") or "발언자 미확인"
        should_split = (
            speaker == current["speaker"]
            and max_group_duration is not None
            and (sub["start_time"] - current["start_time"]) >= max_group_duration
        )
        if speaker == current["speaker"] and not should_split:
            current["end_time"] = sub["end_time"]
            current["texts"].append(sub["text"])
        else:
            grouped.append(current)
            current = {
                "speaker": speaker,
                "start_time": sub["start_time"],
                "end_time": sub["end_time"],
                "texts": [sub["text"]],
            }

    grouped.append(current)
    return grouped


# @TASK P5-T5.1 - 공식 회의록 포맷 헬퍼 함수
# @SPEC docs/planning/02-trd.md#회의록-내보내기


def _format_date_korean(date_str: str) -> str:
    """날짜 문자열을 한국어 형식으로 변환합니다.

    '2026-02-11' -> '2026년 02월 11일'
    파싱 실패 시 원본 문자열을 그대로 반환합니다.
    """
    parts = date_str.split("-")
    if len(parts) == 3:
        return f"{parts[0]}년 {parts[1]}월 {parts[2]}일"
    return date_str


def _format_duration_korean(seconds: int) -> str:
    """초 단위 시간을 한국어 형식으로 변환합니다.

    3661 -> '1시간 1분'
    300  -> '5분'
    """
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    if hours > 0:
        return f"{hours}시간 {minutes}분"
    return f"{minutes}분"


# @TASK P5-T5.1 - 경기도의회 공식 회의록 포맷 생성
def export_official(meeting: dict, subtitles: list[dict], summary: dict | None = None) -> str:
    """경기도의회 공식 회의록 형식으로 내보냅니다.

    형식:
    - 헤더: 이중선 구분선, 회의 제목, 일시, 영상 길이
    - AI 요약 (있는 경우)
    - 본문: 화자별 발언 블록 (동일 화자 연속 발언 병합)
    - 푸터: 면책 조항, 생성 일시
    """
    title = meeting.get("title", "무제")
    meeting_date = meeting.get("meeting_date", "미정")
    duration = meeting.get("duration_seconds")

    date_korean = _format_date_korean(meeting_date)
    duration_str = _format_duration_korean(duration) if duration else "미정"

    border_double = "\u2550" * 39  # ═ 이중선
    border_single = "\u2500" * 39  # ─ 단선

    # --- 헤더 ---
    lines = [
        border_double,
        f" {title}",
        f" 일시: {date_korean}",
    ]
    if duration:
        lines.append(f" 영상 길이: {duration_str}")
    lines.append(border_double)
    lines.append("")

    # --- AI 요약 (있는 경우) ---
    if summary:
        lines.append("【 AI 요약 】")
        lines.append("")
        if summary.get("summary_text"):
            lines.append(f"  {summary['summary_text']}")
            lines.append("")
        if summary.get("key_decisions"):
            lines.append("  ■ 핵심 결정사항")
            for decision in summary["key_decisions"]:
                lines.append(f"    - {decision}")
            lines.append("")
        if summary.get("action_items"):
            lines.append("  ■ 후속 조치")
            for item in summary["action_items"]:
                lines.append(f"    - {item}")
            lines.append("")
        lines.append(border_single)
        lines.append("")

    # --- 본문 ---
    grouped = _group_by_speaker(subtitles)

    if not grouped:
        lines.append("(자막 데이터가 없습니다.)")
        lines.append("")
    else:
        for entry in grouped:
            speaker = entry["speaker"]
            time_str = _format_time_hms(entry["start_time"])
            text = " ".join(entry["texts"])

            lines.append(f"\u25CB {speaker}")
            lines.append(f"  {text} ({time_str})")
            lines.append("")

    # --- 푸터 ---
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines.append(border_single)
    lines.append("\u203B 본 회의록은 AI 음성인식으로 자동 생성되었으며,")
    lines.append("   공식 회의록과 다를 수 있습니다.")
    lines.append(f"   생성 일시: {now_str}")
    lines.append(border_single)

    return "\n".join(lines)


def export_html(meeting: dict, subtitles: list[dict], summary: dict | None = None) -> str:
    """HTML 형식의 회의록을 생성합니다.

    인라인 CSS로 스타일링되며, 인쇄 최적화 스타일시트를 포함합니다.
    브라우저에서 '인쇄 → PDF 저장'으로 PDF 변환이 가능합니다.
    """
    title = meeting.get("title", "무제")
    meeting_date = meeting.get("meeting_date", "미정")
    duration = meeting.get("duration_seconds")
    date_korean = _format_date_korean(meeting_date)
    duration_str = _format_duration_korean(duration) if duration else "미정"
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    # 화자별 색상 (CSS)
    speaker_colors = [
        "#2563eb", "#16a34a", "#9333ea", "#ea580c",
        "#db2777", "#0d9488", "#4f46e5", "#dc2626",
    ]

    def _speaker_color(speaker: str) -> str:
        h = 0
        for ch in speaker:
            h = ((h << 5) - h + ord(ch)) & 0xFFFFFFFF
        return speaker_colors[h % len(speaker_colors)]

    grouped = _group_by_speaker(subtitles)

    # --- HTML 생성 ---
    parts = [
        '<!DOCTYPE html>',
        '<html lang="ko">',
        '<head>',
        '<meta charset="utf-8">',
        f'<title>{title} - 회의록</title>',
        '<style>',
        '  body { font-family: "Pretendard", "Noto Sans KR", sans-serif; max-width: 800px; margin: 0 auto; padding: 40px 20px; color: #1a1a1a; line-height: 1.7; }',
        '  h1 { font-size: 1.5em; border-bottom: 2px solid #2563eb; padding-bottom: 8px; margin-bottom: 16px; }',
        '  .meta { color: #666; font-size: 0.9em; margin-bottom: 24px; }',
        '  .meta span { margin-right: 20px; }',
        '  .summary { background: #f0f9ff; border-left: 4px solid #2563eb; padding: 16px 20px; margin-bottom: 24px; border-radius: 0 4px 4px 0; }',
        '  .summary h2 { font-size: 1.1em; margin: 0 0 8px 0; color: #2563eb; }',
        '  .summary ul { margin: 8px 0; padding-left: 20px; }',
        '  .entry { margin-bottom: 16px; padding-bottom: 16px; border-bottom: 1px solid #e5e7eb; }',
        '  .entry:last-child { border-bottom: none; }',
        '  .speaker-badge { display: inline-block; padding: 2px 10px; border-radius: 12px; font-size: 0.85em; font-weight: 600; color: white; margin-right: 8px; }',
        '  .timestamp { font-family: monospace; font-size: 0.8em; color: #6b7280; }',
        '  .text { margin-top: 4px; }',
        '  .footer { margin-top: 32px; padding-top: 16px; border-top: 1px solid #d1d5db; font-size: 0.8em; color: #9ca3af; }',
        '  @media print {',
        '    body { padding: 20px; font-size: 11pt; }',
        '    .entry { page-break-inside: avoid; }',
        '    .no-print { display: none; }',
        '  }',
        '</style>',
        '</head>',
        '<body>',
        f'<h1>{title}</h1>',
        '<div class="meta">',
        f'  <span>일시: {date_korean}</span>',
    ]

    if duration:
        parts.append(f'  <span>영상 길이: {duration_str}</span>')
    parts.append(f'  <span>자막: {len(subtitles)}건</span>')
    parts.append('</div>')

    # AI 요약
    if summary:
        parts.append('<div class="summary">')
        parts.append('<h2>AI 요약</h2>')
        if summary.get("summary_text"):
            parts.append(f'<p>{summary["summary_text"]}</p>')
        if summary.get("key_decisions"):
            parts.append('<strong>핵심 결정사항</strong><ul>')
            for d in summary["key_decisions"]:
                parts.append(f'<li>{d}</li>')
            parts.append('</ul>')
        if summary.get("action_items"):
            parts.append('<strong>후속 조치</strong><ul>')
            for item in summary["action_items"]:
                parts.append(f'<li>{item}</li>')
            parts.append('</ul>')
        parts.append('</div>')

    # 본문
    if not grouped:
        parts.append('<p>(자막 데이터가 없습니다.)</p>')
    else:
        for entry in grouped:
            speaker = entry["speaker"]
            time_str = _format_time_hms(entry["start_time"])
            text = " ".join(entry["texts"])
            color = _speaker_color(speaker)

            parts.append('<div class="entry">')
            parts.append(f'  <span class="speaker-badge" style="background:{color}">{speaker}</span>')
            parts.append(f'  <span class="timestamp">{time_str}</span>')
            parts.append(f'  <div class="text">{text}</div>')
            parts.append('</div>')

    # 푸터
    parts.append('<div class="footer">')
    parts.append('  <p>본 회의록은 AI 음성인식으로 자동 생성되었으며, 공식 회의록과 다를 수 있습니다.</p>')
    parts.append(f'  <p>생성 일시: {now_str}</p>')
    parts.append('  <p class="no-print">이 페이지를 인쇄(Ctrl+P)하여 PDF로 저장할 수 있습니다.</p>')
    parts.append('</div>')
    parts.append('</body>')
    parts.append('</html>')

    return "\n".join(parts)


def export_markdown(meeting: dict, subtitles: list[dict], summary: dict | None = None) -> str:
    """Markdown 형식의 회의록을 생성합니다.

    경기도의회 회의록 형식에 맞춰:
    - 회의 기본 정보 (제목, 일시, 영상 길이)
    - AI 요약 (있는 경우)
    - 발언자별 그룹화된 발언 내용
    - 타임스탬프 포함
    """
    title = meeting.get("title", "무제")
    meeting_date = meeting.get("meeting_date", "미정")
    duration = meeting.get("duration_seconds")
    duration_str = _format_time_hms(duration) if duration else "미정"

    lines = [
        f"# {title}",
        "",
        "## 회의 정보",
        "",
        f"| 항목 | 내용 |",
        f"|------|------|",
        f"| 회의명 | {title} |",
        f"| 일시 | {meeting_date} |",
        f"| 영상 길이 | {duration_str} |",
        f"| 자막 수 | {len(subtitles)}건 |",
        "",
        "---",
        "",
    ]

    # --- AI 요약 (있는 경우) ---
    if summary:
        lines.append("## AI 요약")
        lines.append("")
        if summary.get("summary_text"):
            lines.append(f"> {summary['summary_text']}")
            lines.append("")
        if summary.get("key_decisions"):
            lines.append("### 핵심 결정사항")
            lines.append("")
            for decision in summary["key_decisions"]:
                lines.append(f"- {decision}")
            lines.append("")
        if summary.get("action_items"):
            lines.append("### 후속 조치")
            lines.append("")
            for item in summary["action_items"]:
                lines.append(f"- [ ] {item}")
            lines.append("")
        lines.append("---")
        lines.append("")

    lines.append("## 회의록")
    lines.append("")

    grouped = _group_by_speaker(subtitles)

    for entry in grouped:
        time_str = _format_time_hms(entry["start_time"])
        speaker = entry["speaker"]
        text = " ".join(entry["texts"])
        lines.append(f"**{speaker}** `{time_str}`")
        lines.append("")
        lines.append(text)
        lines.append("")

    if not grouped:
        lines.append("(자막 데이터가 없습니다.)")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("*이 회의록은 AI STT(음성인식)를 통해 자동 생성되었습니다.*")

    return "\n".join(lines)


def export_srt(subtitles: list[dict]) -> str:
    """SRT 형식의 자막 파일을 생성합니다."""
    lines = []
    for i, sub in enumerate(subtitles, 1):
        start = _format_time_srt(sub["start_time"])
        end = _format_time_srt(sub["end_time"])
        speaker = sub.get("speaker")
        text = sub["text"]

        lines.append(str(i))
        lines.append(f"{start} --> {end}")
        if speaker:
            lines.append(f"[{speaker}] {text}")
        else:
            lines.append(text)
        lines.append("")

    return "\n".join(lines)


def _srt_block(index: int, start: float, end: float, speaker, text: str) -> list[str]:
    body = f"[{speaker}] {text}" if speaker else text
    return [str(index), f"{_format_time_srt(start)} --> {_format_time_srt(end)}", body, ""]


def export_srt_range(
    subtitles: list[dict],
    clip_start: float,
    clip_end: float,
    *,
    time_shift: float = 0.0,
    with_speaker: bool = True,
) -> str:
    """클립 한 구간용 SRT — 자막 시각을 클립 시작 기준으로 재배치한다.

    자막의 VOD 시각 = start_time + time_shift (실시간 자막은 STT 시계라 오프셋이 붙는다).
    [clip_start, clip_end) 와 겹치는 자막만, 경계는 클램프, 빈 텍스트 제외.
    """
    lines: list[str] = []
    n = 0
    for sub in sorted(subtitles or [], key=lambda x: float(x.get("start_time") or 0)):
        s = float(sub.get("start_time") or 0) + time_shift
        e = float(sub.get("end_time") or s) + time_shift
        if e <= clip_start or s >= clip_end:
            continue
        text = str(sub.get("text") or "").strip()
        if not text:
            continue
        s, e = max(s, clip_start), min(e, clip_end)
        n += 1
        lines += _srt_block(n, s - clip_start, e - clip_start,
                            sub.get("speaker") if with_speaker else None, text)
    return "\n".join(lines)


def export_srt_merged(
    subtitles: list[dict],
    segments: list[dict],
    *,
    time_shift: float = 0.0,
    with_speaker: bool = True,
) -> str:
    """합본 클립용 SRT — 구간들을 이어붙인 누적 타임라인으로 재배치한다."""
    lines: list[str] = []
    n = 0
    cursor = 0.0
    ordered = sorted(subtitles or [], key=lambda x: float(x.get("start_time") or 0))
    for seg in segments:
        seg_start, seg_end = float(seg["start"]), float(seg["end"])
        for sub in ordered:
            s = float(sub.get("start_time") or 0) + time_shift
            e = float(sub.get("end_time") or s) + time_shift
            if e <= seg_start or s >= seg_end:
                continue
            text = str(sub.get("text") or "").strip()
            if not text:
                continue
            s, e = max(s, seg_start), min(e, seg_end)
            n += 1
            lines += _srt_block(n, s - seg_start + cursor, e - seg_start + cursor,
                                sub.get("speaker") if with_speaker else None, text)
        cursor += seg_end - seg_start
    return "\n".join(lines)


def export_json(meeting: dict, subtitles: list[dict]) -> dict:
    """JSON 형식의 회의록 데이터를 생성합니다.

    의안관리시스템 등 외부 시스템과의 연계를 위한 구조화된 데이터.
    """
    grouped = _group_by_speaker(subtitles)

    speakers = set()
    for sub in subtitles:
        if sub.get("speaker"):
            speakers.add(sub["speaker"])

    return {
        "meeting": {
            "id": meeting.get("id"),
            "title": meeting.get("title"),
            "meeting_date": meeting.get("meeting_date"),
            "duration_seconds": meeting.get("duration_seconds"),
            "vod_url": meeting.get("vod_url"),
            "status": meeting.get("status"),
        },
        "summary": {
            "total_subtitles": len(subtitles),
            "total_speakers": len(speakers),
            "speakers": sorted(speakers),
            "total_segments": len(grouped),
        },
        "transcript": [
            {
                "speaker": entry["speaker"],
                "start_time": entry["start_time"],
                "end_time": entry["end_time"],
                "text": " ".join(entry["texts"]),
            }
            for entry in grouped
        ],
    }
