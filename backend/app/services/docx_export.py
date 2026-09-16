"""docx(OOXML) 회의록 생성기.

한글(Hancom Office)과 MS Word 모두에서 안정적으로 열리는 최소 OOXML 문서.
hwpx 네이티브 생성이 한글 버전에 따라 호환 문제를 일으킬 수 있어,
확실히 열리는 호환 포맷으로 함께 제공한다. (한글에서 열어 .hwp로 저장 가능)
"""

from __future__ import annotations

import io
import zipfile
from xml.sax.saxutils import escape

_CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/word/document.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
    '</Types>'
)

_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" '
    'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
    'Target="word/document.xml"/>'
    '</Relationships>'
)

_W_NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def _docx_para(text: str, *, bold: bool = False, size_half_pt: int = 20, center: bool = False) -> str:
    """w:p 1개. size_half_pt는 하프포인트 단위(20=10pt)."""
    safe = escape(text or "")
    bold_tag = "<w:b/>" if bold else ""
    align = '<w:jc w:val="center"/>' if center else ""
    rpr = (
        "<w:rPr>"
        '<w:rFonts w:eastAsia="맑은 고딕"/>'
        f"{bold_tag}"
        f'<w:sz w:val="{size_half_pt}"/><w:szCs w:val="{size_half_pt}"/>'
        "</w:rPr>"
    )
    ppr = f"<w:pPr>{align}{rpr}</w:pPr>" if align else ""
    return (
        f'<w:p>{ppr}<w:r>{rpr}<w:t xml:space="preserve">{safe}</w:t></w:r></w:p>'
    )


def export_docx(meeting: dict, grouped: list[dict]) -> bytes:
    """회의록을 docx 바이트로 생성한다 (hwpx와 동일 내용 구조)."""
    title = meeting.get("title", "회의록")
    date = meeting.get("meeting_date", "")

    paras = [_docx_para(title, bold=True, size_half_pt=32, center=True)]
    if date:
        paras.append(_docx_para(f"일시: {date}", center=True))
    paras.append(_docx_para(""))

    if not grouped:
        paras.append(_docx_para("(자막 데이터가 없습니다.)"))
    else:
        from app.services.hwpx_export import _speaker_heading

        for entry in grouped:
            text = " ".join(entry.get("texts", []))
            paras.append(_docx_para(_speaker_heading(entry), bold=True))
            paras.append(_docx_para(text))
            paras.append(_docx_para(""))

    # A4 세로 + 표준 여백 (twip)
    sect = (
        "<w:sectPr>"
        '<w:pgSz w:w="11906" w:h="16838"/>'
        '<w:pgMar w:top="1440" w:right="1200" w:bottom="1440" w:left="1200" '
        'w:header="720" w:footer="720" w:gutter="0"/>'
        "</w:sectPr>"
    )
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f"<w:document {_W_NS}><w:body>"
        + "".join(paras)
        + sect
        + "</w:body></w:document>"
    )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", _CONTENT_TYPES)
        zf.writestr("_rels/.rels", _RELS)
        zf.writestr("word/document.xml", document)
    return buf.getvalue()
