# -*- coding: utf-8 -*-
"""KMS 회의록 내보내기 실측 검증 (실제 회의 자막 → hwpx + 영상회의록 html).

usage: python scripts/verify_kms_export.py <meeting_id>
"""
import asyncio
import io
import sys
import zipfile

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, ".")

from app.core.database import get_supabase_client  # noqa: E402
from app.services.hwpx_export import export_hwpx  # noqa: E402
from app.services.transcript_export import _group_by_speaker  # noqa: E402
from app.services.video_minutes_service import (  # noqa: E402
    derive_chapters_llm,
    export_video_minutes_html,
)


def _fetch_all_subs(sb, mid):
    out, off = [], 0
    while True:
        r = (
            sb.table("subtitles").select("*").eq("meeting_id", mid)
            .order("start_time").range(off, off + 999).execute()
        )
        if not r.data:
            break
        out.extend(r.data)
        if len(r.data) < 1000:
            break
        off += 1000
    # 엔드포인트와 동일: AI 자막 우선(있으면 그것만), 없으면 live 제외, 그래도 없으면 전체.
    ai = [s for s in out if s.get("kind") == "ai"]
    if ai:
        return ai
    non_live = [s for s in out if s.get("kind") != "live"]
    return non_live if non_live else out


async def main(mid):
    sb = get_supabase_client()
    meeting = sb.table("meetings").select("*").eq("id", mid).execute().data[0]
    subs = _fetch_all_subs(sb, mid)
    agendas = (
        sb.table("meeting_agendas").select("order_num,title,description")
        .eq("meeting_id", mid).order("order_num").execute().data or []
    )
    print(f"회의: {meeting.get('title')}")
    print(f"자막: {len(subs)}개 · 안건: {len(agendas)}개")

    grouped = _group_by_speaker(subs)

    # 1) hwpx 전자회의록
    data = export_hwpx(meeting, grouped, agendas)
    with open("_verify_hwpx.hwpx", "wb") as f:
        f.write(data)
    zf = zipfile.ZipFile(io.BytesIO(data))
    sec = zf.read("Contents/section0.xml").decode("utf-8")
    import re
    import html as _h
    heads = [_h.unescape(t) for t in re.findall(r"<hp:t>(.*?)</hp:t>", sec)]
    print(f"\n[hwpx] {len(data)} bytes · mimetype first STORED:",
          zf.infolist()[0].filename == "mimetype"
          and zf.infolist()[0].compress_type == zipfile.ZIP_STORED)
    print("[hwpx] 머리글 6줄:")
    for t in heads[:7]:
        print("   ", repr(t))

    # 2) 영상회의록 챕터 (LLM 1회 호출)
    chapters = await derive_chapters_llm(meeting, subs, agendas)
    html_doc = export_video_minutes_html(meeting, chapters)
    with open("_verify_video_minutes.html", "w", encoding="utf-8") as f:
        f.write(html_doc)
    print(f"\n[영상회의록] 챕터 {len(chapters)}개:")
    for c in chapters:
        print(f"   {c['hms']}  {c['label']}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else None))
