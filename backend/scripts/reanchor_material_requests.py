"""라이브 감지 요구자료 시각을 VOD(AI) 자막 타임라인으로 재앵커 (백필).

배경: 생중계 중 감지된 요구자료는 라이브 STT 시계의 start_time을 저장하는데,
VOD AI 자막 생성 후에는 타임라인이 영상 파일 기준으로 바뀌어 시간이 어긋난다
(오프셋은 정회 편집 등으로 가변). vod_stt_service에 자동 훅이 추가됐지만,
그 이전에 AI 자막이 생성된 회의는 이 스크립트로 일괄 보정한다.

사용:
  python scripts/reanchor_material_requests.py --meeting-id <uuid> [...]   # dry-run
  python scripts/reanchor_material_requests.py --all                       # 대상 자동 발견
  ... --apply                                                              # 실제 반영
"""
import argparse
import asyncio
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.database import get_supabase_client
from app.services.material_request_anchor import reanchor_live_requests


def _discover_meetings(sb) -> list[str]:
    """source='live' 요구자료가 있고 AI 자막(kind='ai')도 있는 회의를 찾는다."""
    rows = (
        sb.table("material_requests")
        .select("meeting_id")
        .eq("source", "live")
        .execute()
    ).data or []
    meeting_ids = sorted({r["meeting_id"] for r in rows})
    targets = []
    for mid in meeting_ids:
        n = (
            sb.table("subtitles")
            .select("id", count="exact")
            .eq("meeting_id", mid)
            .eq("kind", "ai")
            .limit(1)
            .execute()
        ).count or 0
        if n > 0:
            targets.append(mid)
    return targets


def _fmt(sec) -> str:
    if sec is None:
        return "--:--"
    s = int(sec)
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"


async def _run(sb, meeting_ids: list[str], apply: bool) -> None:
    for mid in meeting_ids:
        title = ""
        try:
            m = sb.table("meetings").select("title").eq("id", mid).limit(1).execute().data
            title = (m[0].get("title") or "")[:40] if m else ""
        except Exception:
            pass
        print(f"\n=== {mid}  {title}")

        stats = await reanchor_live_requests(sb, mid, apply=apply)
        for p in stats["plans"]:
            delta = (
                f"Δ{p['old_start'] - p['new_start']:+.1f}s"
                if p["old_start"] is not None and p["new_start"] is not None
                else ""
            )
            print(
                f"  {p['method']:<13} {_fmt(p['old_start'])} → {_fmt(p['new_start'])}"
                f"  {delta:<12} match={p['match_size']:<3} {p['request_id']}"
            )
        print(
            f"  합계: 총 {stats['total']} / 텍스트 {stats['text_matched']}"
            f" / 오프셋 {stats['offset_applied']} / 스킵 {stats['skipped']}"
            f" / 미매칭 {stats['unmatched']}"
        )


def main() -> None:
    ap = argparse.ArgumentParser(description="요구자료 시각 재앵커 백필")
    ap.add_argument("--meeting-id", action="append", default=[], help="대상 회의 UUID (반복 가능)")
    ap.add_argument("--all", action="store_true", help="라이브 요구자료+AI 자막 보유 회의 자동 발견")
    ap.add_argument("--apply", action="store_true", help="실제 DB 반영 (기본 dry-run)")
    args = ap.parse_args()

    sb = get_supabase_client()
    meeting_ids = args.meeting_id or (_discover_meetings(sb) if args.all else [])
    if not meeting_ids:
        print("대상 회의가 없습니다. --meeting-id 또는 --all 을 지정하세요.")
        return

    print(f"대상 회의 {len(meeting_ids)}건 ({'APPLY' if args.apply else 'dry-run'})")
    asyncio.run(_run(sb, meeting_ids, args.apply))
    print("\nUPDATED" if args.apply else "\n(dry-run — --apply 로 적용)")


if __name__ == "__main__":
    main()
