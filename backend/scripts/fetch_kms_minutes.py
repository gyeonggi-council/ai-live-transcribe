"""KMS 영상회의록(속기사 작성) 수집기 — STT 정확도 평가용 ground truth.

경기도의회 KMS의 captionDoc.do 에서 속기 전문을 내려받아
발언 블록([{speaker, role, text}]) JSON으로 저장한다.

페이지 구조 (2026-08 실측):
- https://kms.ggc.go.kr/caster/player/captionDoc.do?proc=view&midx=<N> (UTF-8)
- 발언 블록: <div id="CONTEXT{n}"><strong>○ 이름 직책</strong> 본문(<br/> 단락)
- 화자 마커: ○ (U+25CB). 본문 내 ● (U+25CF)는 의사일정 항목 불릿.

사용법 (backend 디렉터리에서):
    python scripts/fetch_kms_minutes.py 138285 138283
출력: backend/eval_data/minutes_<midx>.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

BASE = "https://kms.ggc.go.kr"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

# 직책 토큰 (이름/직책 분리 휴리스틱)
_ROLE_RE = re.compile(
    r"^(위원장|부위원장|위원|의원|의장|부의장|교육감|도지사|부지사|국장|과장|실장|처장|팀장|서기관|사무관|전문위원|수석전문위원|담당관|본부장|원장|관장|소장|청장|단장|대변인)$"
)


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    return urllib.request.urlopen(req, timeout=30).read()


def _strip_tags(html: str) -> str:
    html = re.sub(r"<br\s*/?>", "\n", html, flags=re.I)
    html = re.sub(r"<[^>]+>", "", html)
    return html


def _split_header(header: str) -> tuple[str, str]:
    """'○ 이름 직책' 또는 '○ 직책 이름' 헤더에서 (name, role)을 추정한다."""
    tokens = header.replace("○", "").split()
    if not tokens:
        return header.strip(), ""
    if len(tokens) == 1:
        return tokens[0], ""
    # 마지막 토큰이 직책이면 [이름..., 직책], 첫 토큰이 직책이면 [직책, 이름...]
    if _ROLE_RE.match(tokens[-1]):
        return " ".join(tokens[:-1]), tokens[-1]
    if _ROLE_RE.match(tokens[0]):
        return " ".join(tokens[1:]), tokens[0]
    return " ".join(tokens), ""


def parse_caption_doc(html: str) -> list[dict]:
    """CONTEXT 블록들을 [{speaker, role, header, text}] 로 파싱한다."""
    blocks = re.split(r'<div[^>]*id="CONTEXT\d+"[^>]*>', html)[1:]
    out: list[dict] = []
    for raw_block in blocks:
        m = re.search(r"<strong>(.*?)</strong>(.*)", raw_block, flags=re.S)
        if not m:
            continue
        header = _strip_tags(m.group(1)).strip()
        body = _strip_tags(m.group(2))
        # 단락 정리: 빈 줄 제거, 공백 정규화
        lines = [re.sub(r"\s+", " ", ln).strip() for ln in body.splitlines()]
        text = "\n".join(ln for ln in lines if ln)
        if not header.startswith("○"):
            continue
        name, role = _split_header(header)
        out.append({"speaker": name, "role": role, "header": header, "text": text})
    return out


def fetch_meeting_title(midx: int) -> str:
    try:
        html = fetch(f"{BASE}/caster/player/vodViewer.do?midx={midx}").decode("utf-8", "replace")
        m = re.search(r"<title>(.*?)</title>", html, flags=re.S)
        if m:
            return re.sub(r"\s+", " ", _strip_tags(m.group(1))).strip()
    except Exception:
        pass
    return ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("midx", nargs="+", type=int)
    ap.add_argument("--out-dir", default=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "eval_data"))
    args = ap.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)
    for midx in args.midx:
        url = f"{BASE}/caster/player/captionDoc.do?proc=view&midx={midx}"
        html = fetch(url).decode("utf-8")
        utterances = parse_caption_doc(html)
        total_chars = sum(len(u["text"]) for u in utterances)
        speakers = sorted({u["speaker"] for u in utterances if u["speaker"]})
        doc = {
            "midx": midx,
            "source_url": url,
            "title": fetch_meeting_title(midx),
            "utterances": utterances,
            "speakers": speakers,
            "stats": {"blocks": len(utterances), "chars": total_chars},
        }
        out_path = os.path.join(args.out_dir, f"minutes_{midx}.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=1)
        print(f"[{midx}] blocks={len(utterances)} chars={total_chars:,} speakers={len(speakers)} → {out_path}")
        if utterances:
            print(f"       화자 예: {', '.join(speakers[:8])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
