"""생중계 회의 자동 생성/관리 서비스

방송 시작 시 자동으로 회의 레코드를 DB에 생성하고,
채널 ID ↔ 회의 UUID 매핑을 관리합니다.

동작 방식:
- 방송 시작 (livestatus 0→1): 해당 채널의 meeting 레코드 생성 (status="live")
- 방송 종료 (livestatus 1→0,3,4): meeting status를 "ended"로 업데이트
- 정회 (livestatus 1→2): 회의는 유지, STT만 중지 (재개 시 같은 회의 사용)
- 서버 재시작: DB에서 status="live" 회의를 조회해 매핑 복원
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import date, datetime, timezone

from app.core.channels import get_channel
from app.core.database import get_supabase_client

logger = logging.getLogger(__name__)


def build_live_title(
    channel_name: str,
    session_no: int | None,
    session_order: int | None,
    meeting_date: str,
) -> str:
    """생중계 회의 제목을 만든다 — KMS 정식 회의록 제목과 **같은 형식**으로.

        제393회 제1차 본회의 [2026-09-01]

    형식을 KMS 와 맞춘 이유(2026-08-31): 회의 목록이 제목에서 `제N회` 를 뽑아 회기를
    묶는데(frontend `vod/page.tsx` `extractSessionNumber`), 예전 제목 `"본회의 생중계"` 는
    회기가 없어 목록에서 미아가 됐다. 나중에 `kms_bulk_matcher` 가 정식 VOD 를 붙일 때도
    제목 형식이 바뀌지 않아 화면이 흔들리지 않는다.

    회차를 못 얻으면 **예전 형식으로 폴백한다.** 일정 API 가 죽어도 자막은 나와야 한다.
    """
    if not session_no:
        return f"{channel_name} 생중계"
    order = f" 제{session_order}차" if session_order else ""
    return f"제{session_no}회{order} {channel_name} [{meeting_date}]"


class LiveMeetingManager:
    """채널-회의 매핑을 관리하는 싱글톤 서비스."""

    def __init__(self) -> None:
        self._channel_to_meeting: dict[str, str] = {}

    def get_meeting_id(self, channel_id: str) -> str | None:
        """채널의 현재 활성 회의 UUID를 반환합니다."""
        return self._channel_to_meeting.get(channel_id)

    async def create_meeting_for_channel(self, channel_id: str) -> str:
        """채널에 대한 생중계 회의 레코드를 생성합니다.

        이미 해당 채널에 live 회의가 있으면 재사용합니다 (멱등성).

        Returns:
            생성되거나 기존 회의의 UUID
        """
        # 이미 매핑이 있으면 기존 UUID 반환
        if channel_id in self._channel_to_meeting:
            return self._channel_to_meeting[channel_id]

        channel = get_channel(channel_id)
        channel_name = channel["name"] if channel else channel_id

        # 회차·차수 — 생중계 일정 API 가 이미 채워 둔 캐시에서 읽는다.
        # 얻지 못하면 (session_no=None) 예전 제목 형식으로 폴백한다.
        session_no: int | None = None
        session_order: int | None = None
        if channel and channel.get("code"):
            try:
                from app.services.channel_status import get_channel_status_service

                sched = get_channel_status_service().get_schedule(channel["code"])
                if sched:
                    session_no = sched.get("session_no")
                    session_order = sched.get("session_order")
            except Exception as e:
                logger.warning("LiveMeeting: 회차 조회 실패 (%s): %s", channel_id, e)

        try:
            supabase = get_supabase_client()
            today = date.today().isoformat()
            now = datetime.now(timezone.utc).isoformat()

            # 오늘 같은 채널의 라이브 플레이스홀더(아직 KMS 미등록)를 재사용한다.
            # - status="live": 이미 진행 중인 회의 (서버 재시작 후 매핑 유실 대응)
            # - status="ended": 방금 방송상태가 깜빡여(1→4→1 등) 종료됐던 회의를
            #   되살림 → 한 번의 방송이 여러 조각으로 쪼개지는 것 방지(flap-resume).
            # kms_no가 채워진 회의(정식 VOD로 매칭됨)는 되살리지 않는다.
            # ★차수(session_order)를 키에 포함한다 — 없으면 1차가 끝나고 열린 2차의 자막이
            #   1차 회의에 합쳐진다(2026-08-31 발견).
            query = (
                supabase.table("meetings")
                .select("id, status")
                .eq("channel_id", channel_id)
                .eq("meeting_date", today)
                .is_("kms_no", "null")
                .in_("status", ["live", "ended"])
            )
            if session_order:
                query = query.eq("session_order", session_order)
            else:
                # 차수를 모르는 상태에서 만든 회의끼리만 재사용한다
                query = query.is_("session_order", "null")
            existing = query.order("created_at", desc=True).limit(1).execute()

            if existing.data:
                meeting_id = existing.data[0]["id"]
                prev_status = existing.data[0].get("status")
                if prev_status != "live":
                    # ended 였던 오늘 플레이스홀더를 live 로 되살림
                    supabase.table("meetings").update(
                        {"status": "live", "updated_at": now}
                    ).eq("id", meeting_id).execute()
                    logger.info(
                        "LiveMeeting: reviving today's placeholder %s for channel %s (%s) — flap-resume",
                        meeting_id, channel_id, channel_name,
                    )
                else:
                    logger.info(
                        "LiveMeeting: reusing existing live meeting %s for channel %s (%s)",
                        meeting_id, channel_id, channel_name,
                    )
                self._channel_to_meeting[channel_id] = meeting_id
                return meeting_id

            # 새 회의 생성
            meeting_id = str(uuid.uuid4())

            # 위원회를 생성 시점에 확정 — 글로서리(13명 명부 주입)와 이름 교정이
            # 위원회 명부를 정확히 쓰려면 meetings.committee가 채워져 있어야 한다.
            from app.core.channels import get_committee_for_channel

            row = {
                "id": meeting_id,
                "title": build_live_title(channel_name, session_no, session_order, today),
                "meeting_date": today,
                "stream_url": channel["stream_url"] if channel else "",
                "status": "live",
                "channel_id": channel_id,
                "committee": get_committee_for_channel(channel_id),
                "session_no": session_no,
                "session_order": session_order,
                "created_at": now,
                "updated_at": now,
            }

            supabase.table("meetings").insert(row).execute()
            self._channel_to_meeting[channel_id] = meeting_id

            logger.info(
                "LiveMeeting: created meeting %s for channel %s (%s)",
                meeting_id, channel_id, channel_name,
            )
            return meeting_id

        except Exception as e:
            logger.error(
                "LiveMeeting: failed to create meeting for channel %s: %s",
                channel_id, e,
            )
            # 실패해도 channel_id를 반환하여 기존 동작 유지
            return channel_id

    async def end_meeting_for_channel(self, channel_id: str) -> None:
        """채널의 생중계 회의를 종료합니다 (status → "ended")."""
        meeting_id = self._channel_to_meeting.pop(channel_id, None)
        if not meeting_id:
            return

        try:
            supabase = get_supabase_client()
            now = datetime.now(timezone.utc).isoformat()

            supabase.table("meetings").update({
                "status": "ended",
                "updated_at": now,
            }).eq("id", meeting_id).execute()

            logger.info(
                "LiveMeeting: ended meeting %s for channel %s",
                meeting_id, channel_id,
            )
        except Exception as e:
            logger.error(
                "LiveMeeting: failed to end meeting %s: %s", meeting_id, e,
            )

    async def recover_active_meetings(self) -> None:
        """서버 재시작 시 **오늘** live 회의만 매핑을 복원하고, 지난 live 는 정리한다.

        ★날짜 조건이 없던 것이 큰 결함이었다(2026-08-31 발견).
          예전에는 `status="live"` 면 날짜를 안 보고 전부 채널에 되붙였다. 그 결과
          방송 종료를 놓쳐 `live` 로 남은 옛 회의가 재시작마다 되살아나
          **몇 주 뒤 방송의 자막이 그 옛 날짜 회의에 쌓였다** — 2026-07-24 ch7 회의의
          자막 103건 중 27건이 2026-08-26 생성분이었다(실측). 화면상 "일자가 안 맞는"
          현상의 정체가 이것이다.
        """
        try:
            supabase = get_supabase_client()
            today = date.today().isoformat()

            result = (
                supabase.table("meetings")
                .select("id, channel_id, meeting_date, title")
                .eq("status", "live")
                .not_.is_("channel_id", "null")
                .execute()
            )
            rows = result.data or []

            recovered = [r for r in rows if (r.get("meeting_date") or "")[:10] == today]
            stale = [r for r in rows if (r.get("meeting_date") or "")[:10] != today]

            for row in recovered:
                self._channel_to_meeting[row["channel_id"]] = row["id"]

            if recovered:
                logger.info(
                    "LiveMeeting: recovered %d active meetings from DB: %s",
                    len(recovered),
                    [r["channel_id"] for r in recovered],
                )

            if stale:
                await asyncio.to_thread(self._sweep_stale, supabase, stale)
        except Exception as e:
            logger.error("LiveMeeting: failed to recover active meetings: %s", e)

    @staticmethod
    def _sweep_stale(supabase, stale: list[dict]) -> None:
        """지난 날짜의 `live` 회의를 정리한다 — 빈 것은 삭제, 자막이 있으면 종료 처리.

        자막이 하나라도 있으면 지우지 않는다. 잘못 열린 회의라도 그 안의 전사 결과는
        누군가 이미 봤을 수 있고, 되돌릴 수 없는 삭제보다 상태 정정이 안전하다.
        """
        now = datetime.now(timezone.utc).isoformat()
        deleted = ended = 0
        for row in stale:
            meeting_id = row["id"]
            try:
                cnt = (
                    supabase.table("subtitles")
                    .select("id", count="exact")
                    .eq("meeting_id", meeting_id)
                    .limit(1)
                    .execute()
                )
                has_subtitles = bool(cnt.count) or bool(cnt.data)
            except Exception as e:
                # 셀 수 없으면 지우지 않는다 — 보수적으로 종료 처리만
                logger.warning("LiveMeeting: 자막 수 조회 실패 (%s): %s", meeting_id, e)
                has_subtitles = True

            try:
                if has_subtitles:
                    supabase.table("meetings").update(
                        {"status": "ended", "updated_at": now}
                    ).eq("id", meeting_id).execute()
                    ended += 1
                else:
                    supabase.table("meetings").delete().eq("id", meeting_id).execute()
                    deleted += 1
            except Exception as e:
                logger.warning("LiveMeeting: 유령 회의 정리 실패 (%s): %s", meeting_id, e)

        logger.info(
            "LiveMeeting: 지난 날짜 live 회의 정리 — 종료 %d건, 삭제 %d건 (자막 없음)",
            ended,
            deleted,
        )


# 싱글톤
_live_meeting_manager: LiveMeetingManager | None = None


def get_live_meeting_manager() -> LiveMeetingManager:
    """LiveMeetingManager 싱글톤을 반환합니다."""
    global _live_meeting_manager
    if _live_meeting_manager is None:
        _live_meeting_manager = LiveMeetingManager()
    return _live_meeting_manager
