"""자막 대조 검증 서비스 테스트

# @TASK P7-T1.2 - 대조관리 서비스 (Verification Service) 테스트
# @TEST tests/services/test_verification_service.py
"""

import uuid
from unittest.mock import MagicMock, patch

import pytest

from app.services.verification_service import (
    VALID_STATUSES,
    batch_verify,
    get_review_queue,
    get_verification_stats,
    update_verification_status,
)

# -- 테스트 헬퍼 ----------------------------------------------------------


def _make_subtitle(
    meeting_id: str,
    verification_status: str = "unverified",
    confidence: float = 0.9,
    subtitle_id: str | None = None,
    text: str = "테스트 자막",
) -> dict:
    """검증 상태 포함 자막 행 생성"""
    return {
        "id": subtitle_id or str(uuid.uuid4()),
        "meeting_id": meeting_id,
        "start_time": 0.0,
        "end_time": 5.0,
        "text": text,
        "speaker": "발언자",
        "confidence": confidence,
        "verification_status": verification_status,
    }


class _MockResponse:
    """Supabase execute() 반환 객체"""

    def __init__(self, data: list | None = None, count: int | None = None):
        self.data = data if data is not None else []
        self.count = count


class _MockQuery:
    """체이닝 쿼리 빌더 모킹 (neq 포함)"""

    def __init__(self, data: list | None = None, count: int | None = None):
        self._data = data if data is not None else []
        self._count = count

    def select(self, *args, **kwargs):
        if kwargs.get("count") == "exact":
            self._count = len(self._data)
        return self

    def eq(self, *args, **kwargs):
        return self

    def neq(self, *args, **kwargs):
        return self

    def order(self, *args, **kwargs):
        return self

    def range(self, *args, **kwargs):
        return self

    def limit(self, *args, **kwargs):
        return self

    def update(self, *args, **kwargs):
        return self

    def execute(self):
        return _MockResponse(data=self._data, count=self._count)


class _MockSupabase:
    """Supabase Client 모킹"""

    def __init__(self, data: list | None = None):
        self._data = data if data is not None else []

    def table(self, name: str):
        return _MockQuery(data=self._data)


# == get_verification_stats 테스트 ========================================


class TestGetVerificationStats:
    """get_verification_stats 함수 테스트"""

    def test_empty_meeting_returns_zeros(self):
        """자막이 없는 회의는 모든 값이 0이어야 합니다."""
        supabase = _MockSupabase(data=[])
        result = get_verification_stats(supabase, "meeting-1")

        assert result["total"] == 0
        assert result["verified"] == 0
        assert result["unverified"] == 0
        assert result["flagged"] == 0
        assert result["progress"] == 0.0

    def test_all_unverified(self):
        """모든 자막이 미검증이면 unverified = total, progress = 0"""
        mid = "meeting-2"
        rows = [
            _make_subtitle(mid, "unverified"),
            _make_subtitle(mid, "unverified"),
            _make_subtitle(mid, "unverified"),
        ]
        supabase = _MockSupabase(data=rows)
        result = get_verification_stats(supabase, mid)

        assert result["total"] == 3
        assert result["verified"] == 0
        assert result["unverified"] == 3
        assert result["flagged"] == 0
        assert result["progress"] == 0.0

    def test_mixed_statuses(self):
        """다양한 상태가 혼합된 경우 정확한 통계를 반환해야 합니다."""
        mid = "meeting-3"
        rows = [
            _make_subtitle(mid, "verified"),
            _make_subtitle(mid, "verified"),
            _make_subtitle(mid, "verified"),
            _make_subtitle(mid, "flagged"),
            _make_subtitle(mid, "unverified"),
        ]
        supabase = _MockSupabase(data=rows)
        result = get_verification_stats(supabase, mid)

        assert result["total"] == 5
        assert result["verified"] == 3
        assert result["unverified"] == 1
        assert result["flagged"] == 1
        assert result["progress"] == pytest.approx(0.6)

    def test_all_verified_progress_is_one(self):
        """모든 자막이 검증되면 progress가 1.0이어야 합니다."""
        mid = "meeting-4"
        rows = [
            _make_subtitle(mid, "verified"),
            _make_subtitle(mid, "verified"),
        ]
        supabase = _MockSupabase(data=rows)
        result = get_verification_stats(supabase, mid)

        assert result["total"] == 2
        assert result["verified"] == 2
        assert result["progress"] == pytest.approx(1.0)

    def test_exception_returns_safe_defaults(self):
        """예외 발생 시 안전한 기본값을 반환해야 합니다."""
        supabase = MagicMock()
        supabase.table.side_effect = Exception("DB connection error")

        result = get_verification_stats(supabase, "meeting-err")

        assert result["total"] == 0
        assert result["progress"] == 0.0


# == get_review_queue 테스트 ==============================================


class TestGetReviewQueue:
    """get_review_queue 함수 테스트"""

    def test_empty_queue(self):
        """리뷰할 자막이 없으면 빈 items를 반환해야 합니다."""
        supabase = _MockSupabase(data=[])
        result = get_review_queue(supabase, "meeting-1")

        assert result["items"] == []
        assert result["total"] == 0
        assert result["limit"] == 50
        assert result["offset"] == 0

    def test_returns_items_with_pagination(self):
        """자막 목록과 페이지네이션 정보를 반환해야 합니다."""
        mid = "meeting-5"
        rows = [
            _make_subtitle(mid, "unverified", confidence=0.4),
            _make_subtitle(mid, "flagged", confidence=0.6),
        ]
        supabase = _MockSupabase(data=rows)
        result = get_review_queue(supabase, mid, limit=10, offset=0)

        assert len(result["items"]) == 2
        assert result["total"] == 2
        assert result["limit"] == 10
        assert result["offset"] == 0

    def test_custom_limit_and_offset(self):
        """사용자 정의 limit/offset이 반영되어야 합니다."""
        supabase = _MockSupabase(data=[])
        result = get_review_queue(supabase, "m1", limit=20, offset=5)

        assert result["limit"] == 20
        assert result["offset"] == 5

    def test_exception_returns_safe_defaults(self):
        """예외 발생 시 안전한 기본값을 반환해야 합니다."""
        supabase = MagicMock()
        supabase.table.side_effect = Exception("DB error")

        result = get_review_queue(supabase, "meeting-err")

        assert result["items"] == []
        assert result["total"] == 0


# == update_verification_status 테스트 ====================================


class TestUpdateVerificationStatus:
    """update_verification_status 함수 테스트"""

    def test_valid_status_verified(self):
        """'verified' 상태로 변경 시 업데이트된 행을 반환해야 합니다."""
        mid = "meeting-6"
        sid = str(uuid.uuid4())
        updated_row = _make_subtitle(mid, "verified", subtitle_id=sid)

        supabase = _MockSupabase(data=[updated_row])
        result = update_verification_status(supabase, mid, sid, "verified")

        assert result is not None
        assert result["id"] == sid
        assert result["verification_status"] == "verified"

    def test_valid_status_flagged(self):
        """'flagged' 상태로 변경 시 업데이트된 행을 반환해야 합니다."""
        mid = "meeting-7"
        sid = str(uuid.uuid4())
        updated_row = _make_subtitle(mid, "flagged", subtitle_id=sid)

        supabase = _MockSupabase(data=[updated_row])
        result = update_verification_status(supabase, mid, sid, "flagged")

        assert result is not None
        assert result["verification_status"] == "flagged"

    def test_invalid_status_returns_none(self):
        """잘못된 상태값은 None을 반환해야 합니다."""
        supabase = _MockSupabase(data=[])
        result = update_verification_status(
            supabase, "m1", "s1", "invalid_status"
        )

        assert result is None

    def test_nonexistent_subtitle_returns_none(self):
        """존재하지 않는 자막 ID는 None을 반환해야 합니다."""
        supabase = _MockSupabase(data=[])
        result = update_verification_status(
            supabase, "m1", "nonexistent-id", "verified"
        )

        assert result is None

    def test_exception_returns_none(self):
        """예외 발생 시 None을 반환해야 합니다."""
        supabase = MagicMock()
        supabase.table.side_effect = Exception("DB error")

        result = update_verification_status(supabase, "m1", "s1", "verified")

        assert result is None

    def test_valid_statuses_constant(self):
        """VALID_STATUSES 상수가 올바른 값을 포함해야 합니다."""
        assert VALID_STATUSES == {"unverified", "verified", "flagged"}


# == batch_verify 테스트 ==================================================


class TestBatchVerify:
    """batch_verify 함수 테스트"""

    def test_empty_ids_returns_zero(self):
        """빈 ID 목록은 updated=0을 반환해야 합니다."""
        supabase = _MockSupabase(data=[])
        result = batch_verify(supabase, "m1", [])

        assert result["updated"] == 0
        assert result["items"] == []

    def test_batch_verify_multiple(self):
        """여러 자막을 일괄 검증해야 합니다."""
        mid = "meeting-8"
        sid1 = str(uuid.uuid4())
        sid2 = str(uuid.uuid4())
        sid3 = str(uuid.uuid4())

        row1 = _make_subtitle(mid, "verified", subtitle_id=sid1)
        row2 = _make_subtitle(mid, "verified", subtitle_id=sid2)
        row3 = _make_subtitle(mid, "verified", subtitle_id=sid3)

        supabase = _MockSupabase(data=[row1])

        # batch_verify calls update_verification_status for each ID
        # With our mock, each call returns the same data (row1)
        result = batch_verify(supabase, mid, [sid1, sid2, sid3])

        assert result["updated"] == 3
        assert len(result["items"]) == 3

    def test_batch_verify_with_flagged_status(self):
        """'flagged' 상태로 일괄 변경이 가능해야 합니다."""
        mid = "meeting-9"
        sid = str(uuid.uuid4())
        row = _make_subtitle(mid, "flagged", subtitle_id=sid)

        supabase = _MockSupabase(data=[row])
        result = batch_verify(supabase, mid, [sid], status="flagged")

        assert result["updated"] == 1
        assert len(result["items"]) == 1

    def test_batch_verify_invalid_status(self):
        """잘못된 상태값은 updated=0을 반환해야 합니다."""
        supabase = _MockSupabase(data=[])
        result = batch_verify(supabase, "m1", ["s1", "s2"], status="bad")

        assert result["updated"] == 0
        assert result["items"] == []

    def test_batch_verify_partial_failure(self):
        """일부 업데이트 실패 시 성공한 것만 포함해야 합니다."""
        mid = "meeting-10"
        sid1 = str(uuid.uuid4())
        sid2 = str(uuid.uuid4())

        # Simulate: first call succeeds, second fails (empty data)
        call_count = 0
        row = _make_subtitle(mid, "verified", subtitle_id=sid1)

        def mock_table(name):
            nonlocal call_count
            call_count += 1
            # Odd calls return data (succeed), even calls return empty (fail)
            if call_count % 2 == 1:
                return _MockQuery(data=[row])
            else:
                return _MockQuery(data=[])

        supabase = MagicMock()
        supabase.table = mock_table

        result = batch_verify(supabase, mid, [sid1, sid2])

        # Each update_verification_status call does 1 table() call
        # sid1 -> call 1 (odd, success), sid2 -> call 2 (even, fail)
        assert result["updated"] == 1
        assert len(result["items"]) == 1

    def test_batch_verify_default_status_is_verified(self):
        """기본 상태가 'verified'여야 합니다."""
        mid = "meeting-11"
        sid = str(uuid.uuid4())
        row = _make_subtitle(mid, "verified", subtitle_id=sid)

        supabase = _MockSupabase(data=[row])
        # Don't pass status explicitly
        result = batch_verify(supabase, mid, [sid])

        assert result["updated"] == 1
