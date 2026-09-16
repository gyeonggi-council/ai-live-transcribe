"""LiveMeetingManager 테스트

생중계 회의 자동 생성/종료 로직을 검증합니다.
"""

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from app.services.live_meeting import LiveMeetingManager, build_live_title


@pytest.fixture
def mock_supabase():
    """Mock Supabase client."""
    client = MagicMock()
    return client


@pytest.fixture
def mgr():
    """LiveMeetingManager instance."""
    return LiveMeetingManager()


class TestGetMeetingId:
    """get_meeting_id 테스트."""

    def test_returns_none_when_no_mapping(self, mgr):
        """매핑이 없으면 None을 반환한다."""
        assert mgr.get_meeting_id("ch14") is None

    def test_returns_uuid_when_mapped(self, mgr):
        """매핑이 있으면 UUID를 반환한다."""
        mgr._channel_to_meeting["ch14"] = "test-uuid-123"
        assert mgr.get_meeting_id("ch14") == "test-uuid-123"


class TestCreateMeetingForChannel:
    """create_meeting_for_channel 테스트."""

    @pytest.mark.asyncio
    async def test_returns_existing_mapping(self, mgr):
        """이미 매핑이 있으면 DB 호출 없이 기존 UUID를 반환한다."""
        mgr._channel_to_meeting["ch14"] = "existing-uuid"

        result = await mgr.create_meeting_for_channel("ch14")

        assert result == "existing-uuid"

    @staticmethod
    def _set_lookup_result(mock_supabase, data):
        """create_meeting_for_channel의 재사용 조회(단일 쿼리) 결과를 설정한다.

        체인: table().select().eq().eq().is_().in_().is_().order().limit().execute()

        ★뒤쪽 `.is_()` 가 차수 필터다(2026-08-31 추가). 차수를 키에 넣지 않으면 1차가
          끝나고 열린 2차의 자막이 1차 회의에 합쳐진다. 회차를 모르는 상태에서 만든
          회의끼리만 재사용하도록 `is_("session_order", "null")` 로 좁힌다.
        """
        result = MagicMock()
        result.data = data
        (
            mock_supabase.table.return_value.select.return_value
            .eq.return_value.eq.return_value.is_.return_value
            .in_.return_value.is_.return_value
            .order.return_value.limit.return_value
            .execute.return_value
        ) = result
        return result

    @pytest.mark.asyncio
    async def test_reuses_live_meeting_from_db(self, mgr, mock_supabase):
        """DB에 이미 live 회의가 있으면 재사용한다 (되살림 update 없음)."""
        self._set_lookup_result(mock_supabase, [{"id": "db-meeting-uuid", "status": "live"}])

        with patch("app.services.live_meeting.get_supabase_client", return_value=mock_supabase):
            result = await mgr.create_meeting_for_channel("ch14")

        assert result == "db-meeting-uuid"
        assert mgr._channel_to_meeting["ch14"] == "db-meeting-uuid"
        # 이미 live 이므로 상태 되살림 update 를 호출하지 않는다
        mock_supabase.table.return_value.update.assert_not_called()

    @pytest.mark.asyncio
    async def test_revives_todays_ended_placeholder(self, mgr, mock_supabase):
        """오늘 방송상태 깜빡임으로 ended 된 플레이스홀더를 되살려 재사용한다 (flap-resume)."""
        self._set_lookup_result(mock_supabase, [{"id": "revive-uuid", "status": "ended"}])

        with patch("app.services.live_meeting.get_supabase_client", return_value=mock_supabase):
            result = await mgr.create_meeting_for_channel("ch14")

        # 새로 만들지 않고 기존 UUID를 되살려 반환
        assert result == "revive-uuid"
        assert mgr._channel_to_meeting["ch14"] == "revive-uuid"
        mock_supabase.table.return_value.insert.assert_not_called()
        # status를 live로 되살리는 update 호출
        mock_supabase.table.return_value.update.assert_called_once()
        update_data = mock_supabase.table.return_value.update.call_args[0][0]
        assert update_data["status"] == "live"

    @pytest.mark.asyncio
    async def test_creates_new_meeting(self, mgr, mock_supabase):
        """오늘 재사용할 회의가 없으면 새로 생성한다."""
        # 재사용 조회 결과: 없음
        self._set_lookup_result(mock_supabase, [])

        # INSERT 결과
        mock_insert_result = MagicMock()
        mock_supabase.table.return_value.insert.return_value.execute.return_value = mock_insert_result

        with patch("app.services.live_meeting.get_supabase_client", return_value=mock_supabase):
            result = await mgr.create_meeting_for_channel("ch14")

        # UUID가 반환되고 매핑에 저장됨
        assert result is not None
        assert result != "ch14"
        assert mgr._channel_to_meeting["ch14"] == result

        # INSERT가 호출됨
        mock_supabase.table.return_value.insert.assert_called_once()
        insert_data = mock_supabase.table.return_value.insert.call_args[0][0]
        assert insert_data["status"] == "live"
        assert insert_data["channel_id"] == "ch14"
        assert "본회의" in insert_data["title"]

    @pytest.mark.asyncio
    async def test_returns_channel_id_on_db_error(self, mgr, mock_supabase):
        """DB 오류 시 channel_id를 폴백으로 반환한다."""
        mock_supabase.table.side_effect = Exception("DB connection error")

        with patch("app.services.live_meeting.get_supabase_client", return_value=mock_supabase):
            result = await mgr.create_meeting_for_channel("ch14")

        assert result == "ch14"


class TestEndMeetingForChannel:
    """end_meeting_for_channel 테스트."""

    @pytest.mark.asyncio
    async def test_updates_status_to_ended(self, mgr, mock_supabase):
        """회의 상태를 ended로 업데이트한다."""
        mgr._channel_to_meeting["ch14"] = "meeting-uuid"

        with patch("app.services.live_meeting.get_supabase_client", return_value=mock_supabase):
            await mgr.end_meeting_for_channel("ch14")

        assert "ch14" not in mgr._channel_to_meeting
        mock_supabase.table.return_value.update.assert_called_once()
        update_data = mock_supabase.table.return_value.update.call_args[0][0]
        assert update_data["status"] == "ended"

    @pytest.mark.asyncio
    async def test_noop_when_no_mapping(self, mgr, mock_supabase):
        """매핑이 없으면 아무것도 하지 않는다."""
        with patch("app.services.live_meeting.get_supabase_client", return_value=mock_supabase):
            await mgr.end_meeting_for_channel("ch14")

        mock_supabase.table.assert_not_called()


class TestRecoverActiveMeetings:
    """recover_active_meetings 테스트.

    ★2026-08-31 에 날짜 조건이 추가됐다. 그전에는 `status="live"` 면 날짜를 안 보고 전부
      채널에 되붙여, 방송 종료를 놓쳐 live 로 남은 옛 회의가 재시작마다 되살아났고
      **몇 주 뒤 방송의 자막이 그 옛 날짜 회의에 쌓였다** — 2026-07-24 ch7 회의의 자막
      103건 중 27건이 2026-08-26 생성분이었다(실측). 화면의 "일자가 안 맞는" 현상의 정체다.
    """

    @staticmethod
    def _set_live_rows(mock_supabase, rows):
        """`select().eq("status","live").not_.is_("channel_id","null").execute()` 결과."""
        result = MagicMock()
        result.data = rows
        (
            mock_supabase.table.return_value.select.return_value
            .eq.return_value.not_.is_.return_value.execute.return_value
        ) = result
        return result

    @pytest.mark.asyncio
    async def test_rebuilds_mapping_from_db(self, mgr, mock_supabase):
        """오늘 날짜의 live 회의를 조회해 매핑을 복원한다."""
        today = date.today().isoformat()
        self._set_live_rows(
            mock_supabase,
            [
                {"id": "uuid-1", "channel_id": "ch14", "meeting_date": today, "title": "본회의"},
                {"id": "uuid-2", "channel_id": "ch8", "meeting_date": today, "title": "문체위"},
            ],
        )

        with patch("app.services.live_meeting.get_supabase_client", return_value=mock_supabase):
            await mgr.recover_active_meetings()

        assert mgr._channel_to_meeting["ch14"] == "uuid-1"
        assert mgr._channel_to_meeting["ch8"] == "uuid-2"

    @pytest.mark.asyncio
    async def test_handles_empty_result(self, mgr, mock_supabase):
        """live 회의가 없으면 매핑이 비어있다."""
        self._set_live_rows(mock_supabase, [])

        with patch("app.services.live_meeting.get_supabase_client", return_value=mock_supabase):
            await mgr.recover_active_meetings()

        assert mgr._channel_to_meeting == {}

    @pytest.mark.asyncio
    async def test_지난_날짜_live_는_복원하지_않는다(self, mgr, mock_supabase):
        """★핵심 회귀 방지 — 옛 회의를 채널에 되붙이면 오늘 자막이 그리로 간다."""
        today = date.today().isoformat()
        self._set_live_rows(
            mock_supabase,
            [
                {"id": "today-1", "channel_id": "ch14", "meeting_date": today, "title": "오늘"},
                {"id": "old-1", "channel_id": "ch7", "meeting_date": "2026-07-24", "title": "5주 전"},
            ],
        )

        with patch("app.services.live_meeting.get_supabase_client", return_value=mock_supabase):
            await mgr.recover_active_meetings()

        assert mgr.get_meeting_id("ch14") == "today-1"
        assert mgr.get_meeting_id("ch7") is None


class TestSweepStale:
    """지난 날짜 live 회의 정리 — 빈 것은 삭제, 자막이 있으면 종료 처리."""

    @staticmethod
    def _supabase(sub_count):
        """meetings/subtitles 를 각각 다른 목으로 돌려주는 클라이언트."""
        meetings, subtitles = MagicMock(), MagicMock()
        cnt = MagicMock()
        cnt.count = sub_count
        cnt.data = [{"id": "s"}] if sub_count else []
        subtitles.select.return_value.eq.return_value.limit.return_value.execute.return_value = cnt

        client = MagicMock()
        client.table.side_effect = lambda name: subtitles if name == "subtitles" else meetings
        return client, meetings

    def test_자막이_있으면_종료_처리한다(self):
        client, meetings = self._supabase(sub_count=103)
        LiveMeetingManager._sweep_stale(
            client, [{"id": "old-1", "channel_id": "ch7", "meeting_date": "2026-07-24"}]
        )

        meetings.update.assert_called_once()
        assert meetings.update.call_args[0][0]["status"] == "ended"
        meetings.delete.assert_not_called()

    def test_자막이_없으면_삭제한다(self):
        client, meetings = self._supabase(sub_count=0)
        LiveMeetingManager._sweep_stale(
            client, [{"id": "empty-1", "channel_id": "ch2", "meeting_date": "2026-07-24"}]
        )

        meetings.delete.assert_called_once()
        meetings.update.assert_not_called()

    def test_자막_수를_못_세면_지우지_않는다(self):
        """셀 수 없을 때 지우는 것은 되돌릴 수 없다. 보수적으로 종료 처리만 한다."""
        client, meetings = self._supabase(sub_count=0)
        client.table.side_effect = lambda name: (_ for _ in ()).throw(
            RuntimeError("PostgREST 오류")
        ) if name == "subtitles" else meetings

        LiveMeetingManager._sweep_stale(
            client, [{"id": "x", "channel_id": "ch2", "meeting_date": "2026-07-24"}]
        )

        meetings.delete.assert_not_called()
        assert meetings.update.call_args[0][0]["status"] == "ended"


class TestBuildLiveTitle:
    """제목 형식 — KMS 정식 회의록 제목과 글자 하나까지 같아야 한다.

    실측: `제392회 제4차 본회의 [2026-07-23]`. 형식을 맞춘 이유는 회의 목록이 제목에서
    `제N회` 를 뽑아 회기를 묶기 때문이다(frontend `vod/page.tsx` extractSessionNumber).
    """

    def test_회차와_차수가_있으면_정식_형식(self):
        assert (
            build_live_title("본회의", 393, 1, "2026-09-01")
            == "제393회 제1차 본회의 [2026-09-01]"
        )

    def test_차수가_없으면_회차까지만(self):
        assert build_live_title("본회의", 393, None, "2026-09-01") == "제393회 본회의 [2026-09-01]"

    def test_회차를_못_얻으면_예전_형식으로_폴백(self):
        """일정 API 가 죽어도 자막은 나와야 한다 — 제목이 중단 사유가 될 수 없다."""
        assert (
            build_live_title("문화체육관광위원회", None, None, "2026-09-01")
            == "문화체육관광위원회 생중계"
        )

    def test_0은_없음으로_본다(self):
        """생중계 API 는 값이 없을 때 0 을 준다. 0 은 '제0회'가 아니다."""
        assert build_live_title("본회의", 0, 0, "2026-09-01") == "본회의 생중계"
