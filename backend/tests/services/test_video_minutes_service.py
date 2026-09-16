# -*- coding: utf-8 -*-
"""영상회의록(KMS) 챕터 도출 + HTML 생성 테스트 (LLM 미호출 경로)."""

import re

from app.services.video_minutes_service import (
    _hms,
    derive_chapters,
    export_video_minutes_html,
)


def _subs(rows):
    """(start, speaker, text) → subtitle dict 목록."""
    return [
        {"start_time": s, "end_time": s + 5, "speaker": spk, "text": txt}
        for s, spk, txt in rows
    ]


def test_hms_formats_seconds():
    assert _hms(0) == "00:00:00"
    assert _hms(674) == "00:11:14"
    assert _hms(3661) == "01:01:01"


def test_derive_chapters_heuristic_basic_flow():
    """개의 → 안건 상정 → 제안설명 → 검토보고 → 질의답변 흐름을 챕터로 도출."""
    meeting = {"title": "제391회 제1차 건설교통위원회 [2026-06-16]"}
    subs = _subs([
        (2, "허원 위원장", "성원이 되었으므로 회의를 개의하겠습니다."),
        (60, "허원 위원장", "의사일정 제1항 2026년도 추가경정예산안을 상정합니다."),
        (120, "건설국장", "건설국장입니다. 추경예산안에 대하여 제안설명 드리겠습니다 " * 3),
        (300, "수석전문위원", "수석전문위원입니다. 검토보고 드리겠습니다 " * 3),
        (500, "김선영 위원", "질의하겠습니다. 이 예산의 근거는 무엇입니까 " * 3),
        (560, "건설국장", "네 그렇습니다."),
        (620, "남경순 위원", "다른 질의를 드리겠습니다. 집행 계획은 어떻게 됩니까 " * 3),
    ])
    chapters = derive_chapters(meeting, subs)
    labels = [c["label"] for c in chapters]

    # 개의 챕터 존재
    assert any("개의" in lb for lb in labels)
    # 제안설명/검토보고/질의답변이 도출됨
    assert any("제안설명" in lb for lb in labels)
    assert any("검토보고" in lb for lb in labels)
    assert any("질의답변(김선영 위원)" in lb for lb in labels)
    assert any("질의답변(남경순 위원)" in lb for lb in labels)
    # seconds 단조 증가
    secs = [c["seconds"] for c in chapters]
    assert secs == sorted(secs)


def test_derive_chapters_empty():
    assert derive_chapters({"title": "x"}, []) == []


def test_export_video_minutes_html_has_startps_seconds():
    """KMS 등록용 HTML — 시:분:초 + 초(startPS) 열을 포함하고 data-seconds를 단다."""
    meeting = {"title": "제391회 제1차 건설교통위원회", "meeting_date": "2026-06-16"}
    chapters = [
        {"label": "회의 개의", "seconds": 4, "hms": _hms(4)},
        {"label": "1. 추가경정예산안", "seconds": 404, "hms": _hms(404)},
        {"label": "질의답변(김선영 위원)", "seconds": 1083, "hms": _hms(1083)},
    ]
    html_doc = export_video_minutes_html(meeting, chapters)
    assert "<!DOCTYPE html>" in html_doc
    assert "초(startPS)" in html_doc
    assert 'data-seconds="404"' in html_doc
    assert "질의답변(김선영 위원)" in html_doc
    # 초 값이 본문에 노출(관리자가 KMS에 직접 입력)
    assert re.search(r">1083<", html_doc)
    assert "00:18:03" in html_doc  # 1083초 = 00:18:03
    # vod_url 없으면 영상 미임베드(표만)
    assert "<video" not in html_doc


def test_export_video_minutes_html_embeds_clickable_player_with_vod():
    """vod_url이 있으면 영상을 임베드하고 챕터를 클릭→시킹·재생하도록 한다."""
    meeting = {
        "title": "제391회 제1차 건설교통위원회",
        "meeting_date": "2026-06-16",
        "vod_url": "https://kms.ggc.go.kr/mp4/sample.mp4",
    }
    chapters = [
        {"label": "회의 개의", "seconds": 4, "hms": _hms(4)},
        {"label": "질의답변(김선영 위원)", "seconds": 1083, "hms": _hms(1083)},
    ]
    html_doc = export_video_minutes_html(meeting, chapters)
    # 영상 임베드 + src
    assert '<video id="vodPlayer"' in html_doc
    assert "https://kms.ggc.go.kr/mp4/sample.mp4" in html_doc
    # 클릭→시킹 + 재생중 강조 스크립트
    assert "currentTime" in html_doc
    assert "timeupdate" in html_doc
    assert "data-seconds" in html_doc
    # 클릭 시각으로 이동한다는 안내
    assert "클릭하면" in html_doc


def test_export_video_minutes_js_autofill_script():
    """KMS 편집기 콘솔 자동입력 JS — dynaTableAddRecord 호출 + m_angun/hms 채움 + 가드."""
    from app.services.video_minutes_service import export_video_minutes_js

    chapters = [
        {"label": "개회식", "seconds": 0, "hms": "00:00:00"},
        {"label": "5분자유발언(정동혁 의원)", "seconds": 637, "hms": "00:10:37"},
        {"label": "1. 회기 결정의 건", "seconds": 2750, "hms": "00:45:50"},
    ]
    js = export_video_minutes_js({"title": "제391회 제1차 본회의"}, chapters)
    # KMS 편집기 전역/요소 사용
    assert "dynaTableAddRecord(CH.length)" in js
    assert "getElementById('dynamictable')" in js
    assert "m_angun" in js and "m_hour" in js and "m_min" in js and "m_sec" in js
    # 챕터 데이터 베이크인 (라벨 전체가 안건 칸 값 a로)
    assert '"a": "5분자유발언(정동혁 의원)"' in js
    assert '"pos": 2750' in js and '"m": "45"' in js
    # 잘못된 페이지 가드
    assert "편집기 페이지에서 실행" in js
    # 빈 챕터도 안전
    assert "CH = []" in export_video_minutes_js({"title": "x"}, [])


def test_is_plenary_detection():
    from app.services.video_minutes_service import _is_plenary

    assert _is_plenary({"title": "제391회 제1차 본회의 [2026-06-09]"}) is True
    assert _is_plenary({"committee": "본회의"}) is True
    assert _is_plenary({"title": "제391회 제3차 경제노동위원회"}) is False


def test_anchor_to_speaker_shifts_off_chair():
    """발언자 챕터는 위원장 호명 그룹이 아니라 실제 발언자 그룹으로 당겨진다."""
    from app.services.video_minutes_service import _anchor_to_speaker

    groups = [
        {"speaker": "허원 위원장", "start_time": 3400.0},   # 위원장 호명
        {"speaker": "수석전문위원", "start_time": 3420.0},   # 실제 검토보고 시작
        {"speaker": "건설국장", "start_time": 3500.0},
    ]
    # 검토보고: 위원장(0) → 수석전문위원(1)로 이동
    ch = [{"label": "수석전문위원 검토보고", "seconds": 3400.0, "_gi": 0}]
    _anchor_to_speaker(ch, groups)
    assert ch[0]["seconds"] == 3420.0 and ch[0]["_gi"] == 1
    # 안건 상정(진행자 본인 발언)은 그대로
    ch2 = [{"label": "1. 추가경정예산안", "seconds": 3400.0, "_gi": 0}]
    _anchor_to_speaker(ch2, groups)
    assert ch2[0]["seconds"] == 3400.0
    # 이미 발언자(비진행자) 그룹이면 유지
    ch3 = [{"label": "질의답변(김동영 위원)", "seconds": 3500.0, "_gi": 2}]
    _anchor_to_speaker(ch3, groups)
    assert ch3[0]["seconds"] == 3500.0


def test_anchor_agendas_matches_titles_and_proposer():
    """공식 안건명을 '상정' 발언 자막에 결정적 매칭 + 발의 위원 제안설명까지 도출.

    LLM이 못 내던 '<번호>. <안건명>' 안건 챕터를 안건명 긴 연속덩어리로 앵커링하고,
    위원 발의 조례안은 상정 직후 첫 비위원장 발언자를 발의 위원으로 본다.
    """
    from app.services.video_minutes_service import _anchor_agendas

    # ★제안설명자는 화자 라벨이 아니라 '내용'(발의하신 OOO 의원 / OOO 의원입니다)으로 잡는다
    #   — 실제로 diarize가 발의자 발언을 위원장으로 오배정하는 경우가 많아서다.
    subs = [
        {"speaker": "허원 위원장", "start_time": 60.0,
         "text": "의사일정 제1항 경기도 낚시 등의 금지지역 지정 및 관리 조례 일부개정조례안을 상정합니다."},
        {"speaker": "허원 위원장", "start_time": 90.0,
         "text": "조례안을 대표발의하신 박명숙 의원님께서는 발언대로 나오셔서 제안설명해 주시기 바랍니다."},
        {"speaker": "허원 위원장", "start_time": 100.0, "text": "박명숙 의원입니다. 제안설명 드리겠습니다."},
        {"speaker": "허원 위원장", "start_time": 400.0,
         "text": "의사일정 제2항 2025회계연도 경기도 결산 및 예비비 승인의 건을 상정합니다."},
    ]
    agendas = [
        {"order_num": 1, "title": "경기도 낚시 등의 금지지역 지정 및 관리 조례 일부개정조례안"},
        {"order_num": 2, "title": "2025회계연도 경기도 결산 및 예비비 승인의 건"},
    ]
    out = _anchor_agendas(agendas, subs)
    labels = [c["label"] for c in out]
    # 안건 챕터(번호+공식제목)가 상정 자막 시각에 앵커링
    assert "1. 경기도 낚시 등의 금지지역 지정 및 관리 조례 일부개정조례안" in labels
    assert "2. 2025회계연도 경기도 결산 및 예비비 승인의 건" in labels
    a1 = next(c for c in out if c["label"].startswith("1."))
    assert a1["seconds"] == 60.0
    # 조례안 → 발의 위원 제안설명(상정 직후 첫 비위원장 발언자), '의원' 표기
    assert "제안설명(박명숙 의원)" in labels
    prop = next(c for c in out if "제안설명" in c["label"])
    assert prop["seconds"] == 100.0
    # 결산(집행부 다수 제안설명)은 결정적 제안설명을 만들지 않음(LLM에 위임)
    assert not any("제안설명" in lb and c["seconds"] >= 400.0 for lb, c in zip(labels, out))


def test_is_chair_speaker_both_name_orders():
    from app.services.video_minutes_service import _is_chair_speaker

    assert _is_chair_speaker("허원 위원장") is True   # 이름-먼저
    assert _is_chair_speaker("위원장 허원") is True   # 직책-먼저
    assert _is_chair_speaker("의장 김진경") is True
    assert _is_chair_speaker("문병근 부위원장") is False
    assert _is_chair_speaker("건설국장") is False
    assert _is_chair_speaker("수석전문위원") is False


# ─── 업무보고형 회의 결정론 (제392회 1차 상임위 실측 패턴 기반) ──────────────


def _sub(t, spk, text):
    return {"start_time": float(t), "speaker": spk, "text": text}


def test_det_open_label_fuzzy_session_kind():
    """개의 풀타이틀 — 제목에 회기종류가 없으면 개의 멘트에서 추출(STT '임실' 오인식 견딤)."""
    from app.services.video_minutes_service import _det_open_label

    meeting = {"title": "제392회 제1차 미래과학협력위원회 [2026-07-20]"}
    subs = [_sub(10, "김태형 위원장", "성원이 되었으므로 제392회 임실 제1차 미래과학협력위원회 회의를 개회하겠습니다.")]
    assert _det_open_label(meeting, subs) == "제392회 임시회 제1차 미래과학협력위원회 회의 개의"
    subs2 = [_sub(6, "김창식 위원장", "성원이 됐으므로 제392회 경기도의회 임시회 제1차 기획재정위원회 회의를 개의하겠습니다")]
    meeting2 = {"title": "제392회 제1차 기획재정위원회 [2026-07-20]"}
    assert _det_open_label(meeting2, subs2) == "제392회 임시회 제1차 기획재정위원회 회의 개의"


def test_det_greetings_and_vice_chair():
    """개의 직후 인사 라운드 + 부위원장 선임 뒤 부위원장 인사(위원 턴 첫 등장 기준)."""
    from app.services.video_minutes_service import _det_greetings

    subs = [
        _sub(112, "김태형 위원장", "간략하게 의원님들 여러분 소개와 인사의 시간을 갖도록 하겠습니다."),
        _sub(135, "박상현 위원", "부천 출신 박상현입니다."),
        _sub(200, "박근철 위원", "안녕하십니까 박근철입니다."),
        _sub(262, "이영봉 위원", "의정부 이영봉입니다."),
        _sub(700, "김태형 위원장", "부위원장 선임의 건을 상정하겠습니다."),
        _sub(757, "박상현 위원", "부위원장을 맡게 된 박상현입니다."),
        _sub(870, "오남석 위원", "부위원장을 맡게 된 오남석입니다."),
        _sub(918, "김태형 위원장", "의석배정의 건을 상정합니다."),
    ]
    agendas = [
        {"label": "1. 부위원장 선임의 건", "seconds": 669.0},
        {"label": "2. 의석배정의 건", "seconds": 918.0},
    ]
    out = _det_greetings(subs, agendas)
    labels = [c["label"] for c in out]
    assert labels[:3] == ["인사(박상현 위원)", "인사(박근철 위원)", "인사(이영봉 위원)"]
    assert "부위원장 인사(박상현 위원)" in labels
    assert "부위원장 인사(오남석 위원)" in labels


def test_det_exec_reports_summon_and_intro():
    """간부소개 및 업무보고 — 호명(짧은 직책)과 자기소개(풀 직책·시각) 결합, 숫자 오인식 보정."""
    from app.services.video_minutes_service import _det_exec_reports

    subs = [
        _sub(985, "김태형 위원장", "김기병 AI국장님은 발원대로 나오셔서 간부소개와 함께 업무보고를 해주시기 바랍니다."),
        _sub(1007, "김기병 AI국장", "안녕하십니까. AI국장 김기병입니다."),
        _sub(1243, "김창식 위원장", "정두석 기획조정실장님 나오셔서 보고해 주시기 바랍니다."),
        _sub(1260, "정두석 기획조정실장", "안녕하십니까. 기획조정실장 정두석입니다."),
        _sub(3824, "김창식 위원장", "다음은 강선천 경기연9원장님 나오셔서 간부 소개와 함께 업무 보고해 주시기 바랍니다."),
        _sub(3838, "위원장", "안녕하십니까. 경기연9원장 강선천입니다."),
    ]
    out = _det_exec_reports(subs)
    labels = {c["label"]: c["seconds"] for c in out}
    assert labels.get("간부소개 및 업무보고(AI국장 김기병)") == 1007.0
    # '나오셔서 보고해'(간부/업무 단서 없음) → '보고' 라벨
    assert labels.get("보고(기획조정실장 정두석)") == 1260.0
    # STT '경기연9원장' → '경기연구원장' 숫자 보정 + 화자 라벨 오배정 무관(텍스트 기반)
    assert labels.get("간부소개 및 업무보고(경기연구원장 강선천)") == 3838.0


def test_datareq_window_and_motion():
    """자료요구 라운드 창(안내→질의답변 안내)과 의사진행발언(STT '의사질의' 변형 포함)."""
    from app.services.video_minutes_service import _det_motions, _det_round_windows

    subs = [
        _sub(1944, "김태형 위원장", "다음에 질의 순서인데 질의에 앞서서 먼저 자료가 필요하신 의원님들"),
        _sub(1949, "김태형 위원장", "자료 요구하는 시간을 갖도록 하겠습니다."),
        _sub(2628, "김태형 위원장", "그러면 다음 질의 답변 시간을 갖도록 하겠습니다."),
        _sub(9053, "김태형 위원장", "유호준 의원님의 질의는 아니고 의사진행 발언 요청이 들어왔거든요."),
        _sub(9062, "유호준 위원", "안녕하세요. 남양주의 유호준입니다."),
    ]
    windows = _det_round_windows(subs)
    assert windows and windows[0][0] == 1944.0 and windows[0][1] == 2628.0
    motions = _det_motions(subs)
    assert motions == [("유호준", 9062.0)]


def test_apply_roster_names_dueum_and_chair_format():
    """명부 교정 — 두음법칙 오인식(유기준→류기준, 퍼지 동점이라 두음 규칙만 가능) +
    위원장 표기를 KMS 양식 '(위원장 이름)'으로 재배열."""
    from app.services.video_minutes_service import _apply_roster_names

    chapters = [
        {"label": "질의답변(유기준 위원)", "seconds": 100, "hms": "00:01:40"},
        {"label": "질의답변(김태형 위원장)", "seconds": 200, "hms": "00:03:20"},
    ]
    roster = ["류기준", "유호준", "김태형", "박상현"]
    _apply_roster_names(chapters, roster)
    assert chapters[0]["label"] == "질의답변(류기준 위원)"
    assert chapters[1]["label"] == "질의답변(위원장 김태형)"


def test_backfill_missing_turns_from_end_cue():
    """diarize 라벨이 턴 경계에서 안 바뀌어 소실된 위원 턴을 '수고하셨습니다' 종료 멘트로 복원.

    앵커 우선순위: 자기소개(STT 오타 퍼지) > 직전 턴 '이상입니다' 마커. 기존 챕터가
    근처(18분 내)에 있으면 중복 삽입하지 않는다. (미래위 2차 실측 패턴)
    """
    from app.services.video_minutes_service import _backfill_missing_turns

    subs = [
        _sub(9281, "윤도희 위원", "질의 시작하겠습니다."),
        _sub(9859, "윤도희 위원", "지표까지 포함해서 부탁드립니다."),
        # 박상현 턴 전체가 '윤도희'로 오라벨된 구간 — 자기소개만 단서(STT 오타 박상윤)
        _sub(9923, "윤도희 위원", "부천 오정 아들 박상윤입니다."),
        _sub(10100, "윤도희 위원", "전략적 고민을 부탁드립니다."),
        _sub(10326, "박상현 위원", "박상현 부위원장님 고생하셨습니다."),
        # 방성환 턴 전체가 '박상현'으로 오라벨 — 직전 턴 종료 마커('이상입니다')가 단서
        _sub(16595, "박상현 위원", "치열하게 고민을 했으면 좋겠습니다. 예 이상입니다."),
        _sub(16655, "박상현 위원", "제가 이제 조직도의 4페이지를 보면"),
        _sub(17351, "박상현 위원", "진행 과정 공유하겠습니다. 네, 이상입니다."),
        _sub(17357, "김태형 위원장", "네, 방성환 의원님 수고하셨습니다."),
    ]
    roster = ["박상현", "방성환", "윤도희", "김태형"]
    chapters = [
        {"label": "질의답변(윤도희 위원)", "seconds": 9281.0},
        {"label": "질의답변(박상현 위원)", "seconds": 15972.0},
    ]
    _backfill_missing_turns(chapters, subs, roster)
    labels = {(c["label"], int(c["seconds"])) for c in chapters}
    assert ("질의답변(박상현 위원)", 9923) in labels     # 자기소개 앵커(박상윤→박상현)
    assert ("질의답변(방성환 위원)", 16603) in labels    # '이상입니다'(16595)+8초 앵커
    # 윤도희는 기존 챕터가 있으므로 중복 삽입 없음
    assert sum(1 for lb, _ in labels if "윤도희" in lb) == 1
