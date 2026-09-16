# -*- coding: utf-8 -*-
"""이미 AI 자막이 있는 회의에 음성 화자 융합(speaker_voice_fusion)을 다시 돌려 화자 라벨을 고친다.

왜(2026-09-08): 클립 슬롯 채점(scripts/eval_clip_slots.py)에서 남은 오답의 뿌리가 라벨 오귀속이었고,
7월 회의 자막은 융합(09-05 도입) 전에 만들어져 라벨이 텍스트 귀속 그대로였다. 같은 회의 8건에 융합을
메모리에서 다시 돌려 보니 4건이 좋아지고(도시환경 40→44, 건설교통 37→41, 미래과학 36→39, 교육기획1차 36→38)
2건은 1건씩 나빠졌다 → 공식 인덱스로 전/후를 재서 **좋아질 때만** DB 에 쓴다. 정답이 없는 회의(본회의·KMS 인덱스
미등록)는 --force 없이는 안 쓴다. 원래 라벨은 /app/clips/fusion_backup/<meeting_id>.json 에 남긴다(되돌리기용).

사용 (파드 안, cwd /app, nice 19 로 돈다 — 생중계 STT 가 먼저):
  PYTHONPATH=/app python scripts/refuse_speaker_labels.py <meeting_id> [--force] [--keep-pcm]
음성은 KMS mp4 에서 16k mono PCM 으로 뽑아 /tmp/eval/pcm_<id8>.raw 에 둔다(회의 4시간 ≈ 500MB, 2~3분).
"""
from __future__ import annotations

import asyncio
import copy
import json
import os
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")
os.nice(19)


def _pcm_path(mid: str) -> str:
    return f"/tmp/eval/pcm_{mid[:8]}.raw"


def extract_pcm(m: dict) -> str:
    from app.services import clip_service

    os.makedirs("/tmp/eval", exist_ok=True)
    out = _pcm_path(m["id"])
    if os.path.exists(out):
        return out
    url = clip_service.normalize_vod_download_url(m["vod_url"])
    cmd = ["nice", "-n", "19", "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
           "-headers", clip_service._FFMPEG_HTTP_HEADERS, "-i", url,
           "-vn", "-ac", "1", "-ar", "16000", "-f", "s16le", out + ".part"]
    t0 = time.time()
    rc = subprocess.call(cmd)
    if rc != 0:
        raise SystemExit(f"ffmpeg 실패 rc={rc}")
    os.replace(out + ".part", out)
    print("PCM", out, os.path.getsize(out), "bytes", "%.0fs" % (time.time() - t0), flush=True)
    return out


def main() -> int:
    force = "--force" in sys.argv
    keep = "--keep-pcm" in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__)
        return 2
    mid = args[0]

    from app.core.database import get_supabase_client
    from app.services import clip_draft_index as draft
    from app.services import kms_angun_service as kms
    from app.services import speaker_segments as segmod
    from app.services.roster_loader import load_committee_with_roles
    from app.services.speaker_voice_fusion import FusionConfig, fuse_voice_speakers
    from scripts.eval_clip_slots import _ai_segments, _official_member_segments, judge

    sb = get_supabase_client()
    m = sb.table("meetings").select("*").eq("id", mid).limit(1).execute().data[0]
    if not m.get("vod_url"):
        print("SKIP no vod_url")
        return 1
    subs = [s for s in segmod._fetch_all_subtitles(sb, mid) if s.get("kind") == "ai"]
    if not subs:
        print("SKIP no ai subtitles")
        return 1
    committee = m.get("committee") or (draft._COMMITTEE_RE.search(m.get("title") or "") or [None])[0]
    roster = load_committee_with_roles(sb, committee) or draft._load_roster(sb, m)
    angun = asyncio.run(kms.fetch_angun(str(m["kms_midx"]))) if m.get("kms_midx") else []
    osegs = (_official_member_segments(kms.build_speakers(angun, m.get("duration_seconds")), kms.norm_name)
             if angun else [])
    if len({s["key"] for s in osegs}) < 2:
        osegs = []

    def score(sub_list):
        if not osegs:
            return None
        segmod._fetch_all_subtitles = lambda _sb, _mid: sub_list
        seg = segmod.build_speaker_segments(sb, m)
        ai = draft.build_draft_from_ai(seg, roster, sub_list, m.get("duration_seconds"))
        rows = judge(osegs, _ai_segments(ai, kms.norm_name), draft._closing_times(sub_list, roster), kms.norm_name)
        return sum(1 for r in rows if r["verdict"] == "correct"), len(rows)

    pcm = extract_pcm(m)
    before = score(subs)
    fused = copy.deepcopy(subs)
    stats = asyncio.run(fuse_voice_speakers(fused, roster, pcm_path=pcm, cfg=FusionConfig.from_settings()))
    after = score(fused)
    changed = [(a["id"], b.get("speaker")) for a, b in zip(subs, fused)
               if (a.get("speaker") or "") != (b.get("speaker") or "")]
    print("MEETING", m["title"], "before", before, "after", after, "changed", len(changed),
          "reliable", len(stats.get("reliable", [])))
    if not keep:
        try:
            os.remove(pcm)
        except OSError:
            pass
    if not changed:
        print("SKIP no changes")
        return 0
    if before is None and not force:
        print("SKIP 정답(공식 인덱스)이 없어 전/후를 못 잰다 — --force 로만 쓴다")
        return 1
    if before is not None and after is not None and after[0] <= before[0] and not force:
        print("SKIP not better")
        return 0
    os.makedirs("/app/clips/fusion_backup", exist_ok=True)
    old = {a["id"]: a.get("speaker") for a, b in zip(subs, fused)
           if (a.get("speaker") or "") != (b.get("speaker") or "")}
    with open(f"/app/clips/fusion_backup/{mid}.json", "w", encoding="utf-8") as f:
        json.dump({"meeting_id": mid, "title": m["title"], "before": before, "after": after,
                   "old_speakers": old, "new_speakers": dict(changed)}, f, ensure_ascii=False)
    by_label: dict = {}
    for sid, sp in changed:
        by_label.setdefault(sp, []).append(sid)
    n = 0
    for sp, ids in by_label.items():
        for i in range(0, len(ids), 200):
            sb.table("subtitles").update({"speaker": sp}).in_("id", ids[i:i + 200]).execute()
            n += len(ids[i:i + 200])
    print("APPLIED", n, "rows  backup /app/clips/fusion_backup/%s.json" % mid)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
