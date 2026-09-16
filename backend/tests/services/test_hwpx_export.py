import io
import zipfile
import xml.etree.ElementTree as ET

from app.services.hwpx_export import export_hwpx


def test_export_hwpx_is_valid_zip_with_required_parts():
    meeting = {"title": "보건복지위원회 회의", "meeting_date": "2026-06-08"}
    grouped = [
        {"speaker": "김영수 위원", "start_time": 0.0, "end_time": 5.0, "texts": ["안녕하세요."]},
        {"speaker": "이민정 위원", "start_time": 5.0, "end_time": 9.0, "texts": ["회의를 시작합니다."]},
    ]
    data = export_hwpx(meeting, grouped)
    assert isinstance(data, (bytes, bytearray))

    zf = zipfile.ZipFile(io.BytesIO(data))
    names = zf.namelist()
    assert "mimetype" in names
    assert "Contents/section0.xml" in names
    assert "Contents/header.xml" in names
    assert "META-INF/manifest.xml" in names
    assert zf.read("mimetype").decode("utf-8").strip() == "application/hwp+zip"
    section = zf.read("Contents/section0.xml").decode("utf-8")
    ET.fromstring(section)
    assert "안녕하세요." in section
    assert "김영수 위원" in section


def test_export_hwpx_empty_subtitles():
    data = export_hwpx({"title": "빈 회의"}, [])
    zf = zipfile.ZipFile(io.BytesIO(data))
    ET.fromstring(zf.read("Contents/section0.xml").decode("utf-8"))


def test_export_hwpx_structure_matches_hancom_layout():
    """한컴 호환 필수 구조 회귀(pyhwpxlib 출력): mimetype 첫 엔트리·비압축,
    content.hpf 위치, header의 완전한 fontface/charPr/paraPr/style 정의, section
    첫 문단의 secPr. 모바일 한컴오피스가 거부했던 '최소 header'를 회귀 방지한다."""
    data = export_hwpx({"title": "구조 검증", "meeting_date": "2026-06-11"}, [])
    zf = zipfile.ZipFile(io.BytesIO(data))
    infos = zf.infolist()

    # mimetype: 첫 엔트리 + STORED(비압축)
    assert infos[0].filename == "mimetype"
    assert infos[0].compress_type == zipfile.ZIP_STORED

    names = zf.namelist()
    assert "Contents/content.hpf" in names
    assert "META-INF/container.xml" in names
    assert "META-INF/container.rdf" in names
    assert "Preview/PrvText.txt" in names

    container = zf.read("META-INF/container.xml").decode("utf-8")
    assert 'full-path="Contents/content.hpf"' in container

    header = zf.read("Contents/header.xml").decode("utf-8")
    ET.fromstring(header)
    # 완전한 정의가 들어 있어야 함(손수 만든 최소 header가 모바일에서 거부됐던 회귀 방지)
    assert "fontface" in header
    assert "charPr" in header and "paraPr" in header
    assert "<hh:style" in header
    assert len(header) > 20000  # 완전한 정의 = 큰 header(이전 최소 7KB가 문제였음)

    section = zf.read("Contents/section0.xml").decode("utf-8")
    ET.fromstring(section)
    assert "<hp:secPr" in section  # 용지/여백 정의
    assert "<hp:pagePr" in section


def test_export_hwpx_official_format_header_and_agenda():
    """KMS 공식 전자회의록 양식: 머리글(제N회 경기도의회/위원회 회의록/제N호/사무처),
    일시·장소, 의사일정·심사된 안건, ○발언자 본문."""
    meeting = {
        "title": "제391회 제3차 경제노동위원회 [2026-06-16]",
        "meeting_date": "2026-06-16",
    }
    grouped = [
        {"speaker": "허원 위원장", "start_time": 2.0, "end_time": 40.0,
         "texts": ["회의를 개의하겠습니다."]},
        {"speaker": "건설국장", "start_time": 41.0, "end_time": 120.0,
         "texts": ["제안설명 드리겠습니다."]},
    ]
    agendas = [{"order_num": 1, "title": "2026년도 제1회 경기도 추가경정예산안"}]
    data = export_hwpx(meeting, grouped, agendas)
    zf = zipfile.ZipFile(io.BytesIO(data))
    section = zf.read("Contents/section0.xml").decode("utf-8")
    ET.fromstring(section)

    assert "제391회 경기도의회" in section
    assert "경제노동위원회 회의록" in section
    assert "제 3 호" in section
    assert "경기도의회사무처" in section
    assert "일  시: 2026년 6월 16일(화)" in section
    assert "장  소: 경제노동위원회 회의실" in section
    assert "의사일정" in section
    assert "심사된 안건" in section
    assert "2026년도 제1회 경기도 추가경정예산안" in section
    assert "○ 허원 위원장" in section
    assert "○ 건설국장" in section
    # 출석위원/출석공무원 말미 명단
    assert "출석위원" in section
    assert "출석공무원" in section

    # 가운데 정렬 paraPr가 header에 정의돼야 함
    header = zf.read("Contents/header.xml").decode("utf-8")
    assert 'horizontal="CENTER"' in header


def test_export_hwpx_kind_fallback_from_subtitles():
    """제목에 회의종류가 없으면 자막 개의 멘트에서 정례회/임시회를 보강 추출해 머리글에 반영."""
    meeting = {
        "title": "제391회 제2차 교육행정위원회 [2026-06-12]",  # (정례회) 표기 없음
        "meeting_date": "2026-06-12",
    }
    grouped = [
        {"speaker": "화자 1", "start_time": 0.0, "end_time": 30.0,
         "texts": ["성원이 되었으므로 제391회 경기도의회 정례회 제2차 교육행정위원회 "
                   "회의를 개의하겠습니다."]},
    ]
    data = export_hwpx(meeting, grouped)
    zf = zipfile.ZipFile(io.BytesIO(data))
    section = zf.read("Contents/section0.xml").decode("utf-8")
    assert "제391회 경기도의회(정례회)" in section


def test_kind_from_grouped_helper():
    from app.services.hwpx_export import _kind_from_grouped

    assert _kind_from_grouped(
        [{"texts": ["제391회 경기도의회 정례회 제1차 회의를 개의합니다."]}]
    ) == "정례회"
    assert _kind_from_grouped(
        [{"texts": ["제389회 임시회 제2차 회의를 개의하겠습니다."]}]
    ) == "임시회"
    assert _kind_from_grouped([{"texts": ["안녕하십니까."]}]) is None
    assert _kind_from_grouped([]) is None


def test_export_hwpx_title_parsing_with_kind_bracket():
    """[임시회] 같은 대괄호 종류 표기를 파싱하고 위원회명에서 제거한다."""
    from app.services.hwpx_export import _parse_meeting_title

    info = _parse_meeting_title(
        {"title": "제389회 [임시회] 제2차 건설교통위원회 [2026-04-24]"}
    )
    assert info["session"] == "389"
    assert info["round"] == "2"
    assert info["kind"] == "임시회"
    assert info["committee"] == "건설교통위원회"


def test_export_hwpx_suppresses_repeated_speaker_heading():
    """같은 발언자가 연속되면 '○ 발언자' 머리표를 반복하지 않는다(사용자 요구)."""
    meeting = {"title": "제391회 제1차 건설교통위원회 [2026-06-16]", "meeting_date": "2026-06-16"}
    grouped = [
        {"speaker": "허원 위원장", "start_time": 0.0, "end_time": 150.0, "texts": ["앞부분 발언."]},
        {"speaker": "허원 위원장", "start_time": 150.0, "end_time": 300.0, "texts": ["이어지는 발언."]},
        {"speaker": "김선영 위원", "start_time": 300.0, "end_time": 360.0, "texts": ["질의입니다."]},
    ]
    data = export_hwpx(meeting, grouped)
    zf = zipfile.ZipFile(io.BytesIO(data))
    section = zf.read("Contents/section0.xml").decode("utf-8")
    # '○ 허원 위원장' 머리표는 연속 그룹에서 1번만 등장해야 한다
    assert section.count("○ 허원 위원장") == 1
    assert section.count("○ 김선영 위원") == 1
    # 두 발언 텍스트는 모두 보존
    assert "앞부분 발언." in section
    assert "이어지는 발언." in section


def test_prefer_ai_subtitles_filters_out_live():
    """live(화자없음)+ai(화자있음) 혼재 시 ai만 남겨 '발언자 미확인'·중복을 제거한다."""
    from app.api.exports import _prefer_ai_subtitles

    mixed = [
        {"kind": "live", "speaker": None, "text": "성원이 되었으므로", "start_time": 0.0},
        {"kind": "ai", "speaker": "허원 위원장", "text": "의석을 정돈해 주시기", "start_time": 1.0},
        {"kind": "ai", "speaker": "허원 위원장", "text": "성원이 되었으므로", "start_time": 5.0},
        {"kind": "live", "speaker": None, "text": "존경하는 위원님", "start_time": 10.0},
    ]
    out = _prefer_ai_subtitles(mixed)
    assert len(out) == 2
    assert all(s["kind"] == "ai" for s in out)
    assert all(s.get("speaker") for s in out)

    # ai가 없으면 live라도 폴백
    only_live = [{"kind": "live", "speaker": None, "text": "x", "start_time": 0.0}]
    assert _prefer_ai_subtitles(only_live) == only_live
    # kind 없는 레거시 자막은 그대로
    legacy = [{"speaker": "화자1", "text": "y", "start_time": 0.0}]
    assert _prefer_ai_subtitles(legacy) == legacy


def test_export_docx_opens_as_valid_ooxml():
    from app.services.docx_export import export_docx

    grouped = [
        {"speaker": "김영수 위원", "start_time": 0.0, "end_time": 5.0, "texts": ["안녕하세요."]},
    ]
    data = export_docx({"title": "워드 회의록", "meeting_date": "2026-06-11"}, grouped)
    zf = zipfile.ZipFile(io.BytesIO(data))
    names = zf.namelist()
    assert "[Content_Types].xml" in names
    assert "_rels/.rels" in names
    doc = zf.read("word/document.xml").decode("utf-8")
    ET.fromstring(doc)
    assert "안녕하세요." in doc
    assert "김영수 위원" in doc
    assert "<w:sectPr>" in doc
