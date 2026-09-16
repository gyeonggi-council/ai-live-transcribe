"""Bills API 테스트 - TDD

@TASK P5-T4.2 - 의안 CRUD API
@SPEC docs/planning/
"""

import uuid
from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.core.database import get_supabase
from app.main import app
from app.schemas.bill import BillCreate, BillMentionCreate, BillResponse
from tests.conftest import (
    MockSupabaseClient,
    MockSupabaseQuery,
    MockSupabaseResponse,
)


# =============================================================================
# Helpers
# =============================================================================


def _make_bill_row(
    bill_number: str = "제2026-001호",
    title: str = "경기도 조례 일부개정안",
    proposer: str | None = "홍길동",
    committee: str | None = "행정안전위원회",
    status: str = "received",
    proposed_date: str | None = "2026-01-15",
    bill_id: str | None = None,
) -> dict:
    """Supabase 응답 형태의 의안 dict를 생성합니다."""
    return {
        "id": bill_id or str(uuid.uuid4()),
        "bill_number": bill_number,
        "title": title,
        "proposer": proposer,
        "committee": committee,
        "status": status,
        "proposed_date": proposed_date,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def _make_mention_row(
    bill_id: str,
    meeting_id: str,
    subtitle_id: str | None = None,
    start_time: float | None = 120.5,
    end_time: float | None = 135.0,
    note: str | None = "의안 관련 논의",
    mention_id: str | None = None,
) -> dict:
    """Supabase 응답 형태의 의안-회의 연결 dict를 생성합니다."""
    return {
        "id": mention_id or str(uuid.uuid4()),
        "bill_id": bill_id,
        "meeting_id": meeting_id,
        "subtitle_id": subtitle_id,
        "start_time": start_time,
        "end_time": end_time,
        "note": note,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


# =============================================================================
# Bills-aware Mock Supabase (필터링 지원)
# =============================================================================


class _BillsMockSupabaseQuery(MockSupabaseQuery):
    """Bills API 테스트용 Supabase 쿼리 빌더

    select/eq/ilike/insert 체이닝에서 필터링을 실제로 수행합니다.
    """

    def __init__(self, data: list | None = None, count: int | None = None):
        super().__init__(data, count)
        self._filters: dict[str, str] = {}
        self._ilike_filters: dict[str, str] = {}
        self._insert_payload: dict | list | None = None

    def select(self, *args, **kwargs) -> "_BillsMockSupabaseQuery":
        if kwargs.get("count") == "exact":
            self._count = len(self._data)
        return self

    def eq(self, column: str, value: str) -> "_BillsMockSupabaseQuery":
        self._filters[column] = str(value)
        return self

    def ilike(self, column: str, pattern: str) -> "_BillsMockSupabaseQuery":
        self._ilike_filters[column] = pattern
        return self

    def order(self, *args, **kwargs) -> "_BillsMockSupabaseQuery":
        return self

    def range(self, *args, **kwargs) -> "_BillsMockSupabaseQuery":
        return self

    def limit(self, *args, **kwargs) -> "_BillsMockSupabaseQuery":
        return self

    def in_(self, *args, **kwargs) -> "_BillsMockSupabaseQuery":
        return self

    def insert(self, payload) -> "_BillsMockSupabaseQuery":
        self._insert_payload = payload
        return self

    def execute(self) -> MockSupabaseResponse:
        # insert 호출: 생성된 데이터를 반환
        if self._insert_payload is not None:
            if isinstance(self._insert_payload, dict):
                row = {
                    "id": str(uuid.uuid4()),
                    **self._insert_payload,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
                return MockSupabaseResponse(data=[row])
            return MockSupabaseResponse(data=self._insert_payload)

        # 필터 적용
        matched = list(self._data)
        if self._filters:
            for col, val in self._filters.items():
                matched = [
                    row for row in matched if str(row.get(col, "")) == val
                ]
        if self._ilike_filters:
            for col, pattern in self._ilike_filters.items():
                # ILIKE %term% 패턴 시뮬레이션
                term = pattern.strip("%").lower()
                matched = [
                    row
                    for row in matched
                    if term in str(row.get(col, "")).lower()
                ]

        count = len(matched) if self._count is not None else None
        return MockSupabaseResponse(data=matched, count=count)


class _BillsMockSupabaseClient:
    """Bills 테스트에 특화된 Supabase 클라이언트 모킹"""

    def __init__(self, table_data: dict[str, list] | None = None):
        self._table_data = table_data or {}

    def table(self, name: str) -> _BillsMockSupabaseQuery:
        data = self._table_data.get(name, [])
        return _BillsMockSupabaseQuery(data=data)


# =============================================================================
# GET /api/bills - 의안 목록 조회
# =============================================================================


class TestGetBills:
    """GET /api/bills 테스트"""

    def test_get_bills_returns_200(self) -> None:
        """의안 목록 조회 시 200 응답을 반환한다"""
        mock_client = _BillsMockSupabaseClient(table_data={"bills": []})
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.get("/api/bills")
        assert response.status_code == 200

        app.dependency_overrides.clear()

    def test_get_bills_returns_paginated_structure(self) -> None:
        """의안 목록 조회 시 페이지네이션 구조를 반환한다"""
        bills = [_make_bill_row(), _make_bill_row(bill_number="제2026-002호")]
        mock_client = _BillsMockSupabaseClient(table_data={"bills": bills})
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.get("/api/bills")
        data = response.json()

        assert "items" in data
        assert "total" in data
        assert "limit" in data
        assert "offset" in data
        assert isinstance(data["items"], list)
        assert data["total"] == 2

        app.dependency_overrides.clear()

    def test_get_bills_with_committee_filter(self) -> None:
        """committee 파라미터로 위원회 필터링할 수 있다"""
        bills = [
            _make_bill_row(committee="행정안전위원회"),
            _make_bill_row(committee="교육위원회"),
        ]
        mock_client = _BillsMockSupabaseClient(table_data={"bills": bills})
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.get("/api/bills?committee=행정안전위원회")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data["items"], list)

        app.dependency_overrides.clear()

    def test_get_bills_with_status_filter(self) -> None:
        """status 파라미터로 상태 필터링할 수 있다"""
        bills = [
            _make_bill_row(status="received"),
            _make_bill_row(status="decided"),
        ]
        mock_client = _BillsMockSupabaseClient(table_data={"bills": bills})
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.get("/api/bills?status=received")
        assert response.status_code == 200

        app.dependency_overrides.clear()

    def test_get_bills_with_search_query(self) -> None:
        """q 파라미터로 의안명 검색할 수 있다"""
        bills = [
            _make_bill_row(title="경기도 조례 일부개정안"),
            _make_bill_row(title="교육 예산 승인건"),
        ]
        mock_client = _BillsMockSupabaseClient(table_data={"bills": bills})
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.get("/api/bills?q=조례")
        assert response.status_code == 200

        app.dependency_overrides.clear()

    def test_get_bills_with_pagination(self) -> None:
        """limit, offset 파라미터로 페이지네이션할 수 있다"""
        bills = [_make_bill_row() for _ in range(5)]
        mock_client = _BillsMockSupabaseClient(table_data={"bills": bills})
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.get("/api/bills?limit=2&offset=0")
        assert response.status_code == 200
        data = response.json()
        assert data["limit"] == 2
        assert data["offset"] == 0

        app.dependency_overrides.clear()

    def test_get_bills_empty_list(self) -> None:
        """의안이 없으면 빈 리스트를 반환한다"""
        mock_client = _BillsMockSupabaseClient(table_data={"bills": []})
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.get("/api/bills")
        data = response.json()
        assert data["items"] == []
        assert data["total"] == 0

        app.dependency_overrides.clear()


# =============================================================================
# GET /api/bills/{bill_id} - 의안 상세 조회
# =============================================================================


class TestGetBill:
    """GET /api/bills/{bill_id} 테스트"""

    def test_get_bill_returns_200(self) -> None:
        """존재하는 의안 조회 시 200 응답을 반환한다"""
        bill = _make_bill_row()
        bill_id = bill["id"]
        mock_client = _BillsMockSupabaseClient(
            table_data={
                "bills": [bill],
                "bill_mentions": [],
                "meetings": [],
            }
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.get(f"/api/bills/{bill_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == bill_id
        assert data["bill_number"] == bill["bill_number"]
        assert "mentions" in data

        app.dependency_overrides.clear()

    def test_get_bill_not_found(self) -> None:
        """존재하지 않는 의안 조회 시 404를 반환한다"""
        mock_client = _BillsMockSupabaseClient(table_data={"bills": []})
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        non_existent_id = str(uuid.uuid4())
        response = client.get(f"/api/bills/{non_existent_id}")
        assert response.status_code == 404

        app.dependency_overrides.clear()

    def test_get_bill_with_mentions(self) -> None:
        """의안 상세 조회 시 관련 회의 mentions를 포함한다"""
        bill_id = str(uuid.uuid4())
        meeting_id = str(uuid.uuid4())
        bill = _make_bill_row(bill_id=bill_id)
        meeting = {
            "id": meeting_id,
            "title": "제123회 본회의",
            "meeting_date": "2026-01-20",
        }
        mention = _make_mention_row(bill_id=bill_id, meeting_id=meeting_id)

        mock_client = _BillsMockSupabaseClient(
            table_data={
                "bills": [bill],
                "bill_mentions": [mention],
                "meetings": [meeting],
            }
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.get(f"/api/bills/{bill_id}")
        assert response.status_code == 200
        data = response.json()
        assert "mentions" in data
        assert isinstance(data["mentions"], list)

        app.dependency_overrides.clear()


# =============================================================================
# POST /api/bills - 의안 등록
# =============================================================================


class TestCreateBill:
    """POST /api/bills 테스트"""

    def test_create_bill_returns_201(self) -> None:
        """유효한 데이터로 의안 생성 시 201 응답을 반환한다"""
        mock_client = _BillsMockSupabaseClient(table_data={"bills": []})
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        body = {
            "bill_number": "제2026-100호",
            "title": "경기도 문화재 보호 조례",
            "proposer": "김의원",
            "committee": "문화체육관광위원회",
            "status": "received",
            "proposed_date": "2026-02-01",
        }
        response = client.post("/api/bills", json=body)
        assert response.status_code == 201
        data = response.json()
        assert "id" in data
        assert data["bill_number"] == "제2026-100호"
        assert data["title"] == "경기도 문화재 보호 조례"

        app.dependency_overrides.clear()

    def test_create_bill_duplicate_bill_number(self) -> None:
        """중복된 의안번호로 생성 시 409 Conflict를 반환한다"""
        existing = _make_bill_row(bill_number="제2026-100호")
        mock_client = _BillsMockSupabaseClient(
            table_data={"bills": [existing]}
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        body = {
            "bill_number": "제2026-100호",
            "title": "중복 의안",
        }
        response = client.post("/api/bills", json=body)
        assert response.status_code == 409

        app.dependency_overrides.clear()

    def test_create_bill_missing_required_field(self) -> None:
        """필수 필드(title)가 없으면 422 에러를 반환한다"""
        mock_client = _BillsMockSupabaseClient(table_data={"bills": []})
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        body = {"bill_number": "제2026-100호"}
        response = client.post("/api/bills", json=body)
        assert response.status_code == 422

        app.dependency_overrides.clear()

    def test_create_bill_minimal_data(self) -> None:
        """최소 필수 데이터(bill_number, title)만으로 생성 가능하다"""
        mock_client = _BillsMockSupabaseClient(table_data={"bills": []})
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        body = {
            "bill_number": "제2026-200호",
            "title": "최소 의안",
        }
        response = client.post("/api/bills", json=body)
        assert response.status_code == 201
        data = response.json()
        assert data["bill_number"] == "제2026-200호"

        app.dependency_overrides.clear()


# =============================================================================
# POST /api/bills/{bill_id}/mentions - 의안-회의 연결 등록
# =============================================================================


class TestCreateBillMention:
    """POST /api/bills/{bill_id}/mentions 테스트"""

    def test_create_mention_returns_201(self) -> None:
        """유효한 데이터로 의안-회의 연결 생성 시 201 응답을 반환한다"""
        bill_id = str(uuid.uuid4())
        meeting_id = str(uuid.uuid4())
        bill = _make_bill_row(bill_id=bill_id)
        meeting = {
            "id": meeting_id,
            "title": "제123회 본회의",
            "meeting_date": "2026-01-20",
        }

        mock_client = _BillsMockSupabaseClient(
            table_data={
                "bills": [bill],
                "meetings": [meeting],
                "bill_mentions": [],
            }
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        body = {
            "bill_id": bill_id,
            "meeting_id": meeting_id,
            "start_time": 120.5,
            "end_time": 135.0,
            "note": "조례 논의",
        }
        response = client.post(f"/api/bills/{bill_id}/mentions", json=body)
        assert response.status_code == 201
        data = response.json()
        assert "id" in data
        assert data["bill_id"] == bill_id
        assert data["meeting_id"] == meeting_id

        app.dependency_overrides.clear()

    def test_create_mention_bill_not_found(self) -> None:
        """존재하지 않는 bill_id로 연결 생성 시 404를 반환한다"""
        mock_client = _BillsMockSupabaseClient(
            table_data={"bills": [], "meetings": [], "bill_mentions": []}
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        non_existent_bill_id = str(uuid.uuid4())
        body = {
            "bill_id": non_existent_bill_id,
            "meeting_id": str(uuid.uuid4()),
        }
        response = client.post(
            f"/api/bills/{non_existent_bill_id}/mentions", json=body
        )
        assert response.status_code == 404

        app.dependency_overrides.clear()

    def test_create_mention_meeting_not_found(self) -> None:
        """존재하지 않는 meeting_id로 연결 생성 시 404를 반환한다"""
        bill_id = str(uuid.uuid4())
        bill = _make_bill_row(bill_id=bill_id)

        mock_client = _BillsMockSupabaseClient(
            table_data={"bills": [bill], "meetings": [], "bill_mentions": []}
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        body = {
            "bill_id": bill_id,
            "meeting_id": str(uuid.uuid4()),
        }
        response = client.post(f"/api/bills/{bill_id}/mentions", json=body)
        assert response.status_code == 404

        app.dependency_overrides.clear()


# =============================================================================
# GET /api/bills/{bill_id}/mentions - 의안-회의 연결 목록 조회
# =============================================================================


class TestGetBillMentions:
    """GET /api/bills/{bill_id}/mentions 테스트"""

    def test_get_mentions_returns_200(self) -> None:
        """의안의 mentions 조회 시 200 응답을 반환한다"""
        bill_id = str(uuid.uuid4())
        bill = _make_bill_row(bill_id=bill_id)

        mock_client = _BillsMockSupabaseClient(
            table_data={
                "bills": [bill],
                "bill_mentions": [],
                "meetings": [],
            }
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.get(f"/api/bills/{bill_id}/mentions")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert isinstance(data["items"], list)

        app.dependency_overrides.clear()

    def test_get_mentions_bill_not_found(self) -> None:
        """존재하지 않는 bill_id로 mentions 조회 시 404를 반환한다"""
        mock_client = _BillsMockSupabaseClient(
            table_data={"bills": [], "bill_mentions": []}
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        non_existent_id = str(uuid.uuid4())
        response = client.get(f"/api/bills/{non_existent_id}/mentions")
        assert response.status_code == 404

        app.dependency_overrides.clear()

    def test_get_mentions_with_data(self) -> None:
        """mentions가 있을 경우 올바른 구조의 데이터를 반환한다"""
        bill_id = str(uuid.uuid4())
        meeting_id = str(uuid.uuid4())
        bill = _make_bill_row(bill_id=bill_id)
        mention = _make_mention_row(bill_id=bill_id, meeting_id=meeting_id)
        meeting = {
            "id": meeting_id,
            "title": "제123회 본회의",
            "meeting_date": "2026-01-20",
        }

        mock_client = _BillsMockSupabaseClient(
            table_data={
                "bills": [bill],
                "bill_mentions": [mention],
                "meetings": [meeting],
            }
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.get(f"/api/bills/{bill_id}/mentions")
        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) >= 1
        item = data["items"][0]
        assert "bill_id" in item
        assert "meeting_id" in item

        app.dependency_overrides.clear()

    def test_get_mentions_empty_list(self) -> None:
        """mentions가 없을 경우 빈 리스트를 반환한다"""
        bill_id = str(uuid.uuid4())
        bill = _make_bill_row(bill_id=bill_id)

        mock_client = _BillsMockSupabaseClient(
            table_data={
                "bills": [bill],
                "bill_mentions": [],
                "meetings": [],
            }
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.get(f"/api/bills/{bill_id}/mentions")
        assert response.status_code == 200
        data = response.json()
        assert data["items"] == []

        app.dependency_overrides.clear()


# =============================================================================
# Schema 테스트
# =============================================================================


class TestBillSchema:
    """Bill 스키마 테스트"""

    def test_bill_create_valid(self) -> None:
        """유효한 BillCreate 스키마 생성"""
        bill = BillCreate(
            bill_number="제2026-001호",
            title="경기도 조례",
            proposer="홍길동",
            committee="행정안전위원회",
            status="received",
            proposed_date=date(2026, 1, 15),
        )
        assert bill.bill_number == "제2026-001호"
        assert bill.title == "경기도 조례"
        assert bill.status == "received"

    def test_bill_create_minimal(self) -> None:
        """최소 필수 필드로 BillCreate 생성"""
        bill = BillCreate(
            bill_number="제2026-001호",
            title="경기도 조례",
        )
        assert bill.proposer is None
        assert bill.committee is None
        assert bill.status == "received"
        assert bill.proposed_date is None

    def test_bill_mention_create_valid(self) -> None:
        """유효한 BillMentionCreate 스키마 생성"""
        mention = BillMentionCreate(
            bill_id=uuid.uuid4(),
            meeting_id=uuid.uuid4(),
            start_time=120.5,
            end_time=135.0,
            note="논의",
        )
        assert mention.start_time == 120.5
        assert mention.end_time == 135.0

    def test_bill_mention_create_minimal(self) -> None:
        """최소 필수 필드로 BillMentionCreate 생성"""
        mention = BillMentionCreate(
            bill_id=uuid.uuid4(),
            meeting_id=uuid.uuid4(),
        )
        assert mention.subtitle_id is None
        assert mention.start_time is None
        assert mention.end_time is None
        assert mention.note is None
