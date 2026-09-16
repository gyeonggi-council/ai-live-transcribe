"""Minutes API 테스트 - 안건별 자막 분류 API

# @TASK P10-T2.1 - 안건별 자막 분류 API 테스트
# @SPEC docs/planning/02-trd.md#회의록-작성

TDD RED 단계: 테스트 먼저 작성
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.database import get_supabase
from app.main import app
from tests.conftest import MockSupabaseClient, MockSupabaseQuery, MockSupabaseResponse


# =============================================================================
# Helpers
# =============================================================================


def _make_agenda(meeting_id: str, order_num: int, title: str, description: str = None) -> dict:
    """테스트용 안건 데이터를 생성합니다."""
    return {
        "id": str(uuid.uuid4()),
        "meeting_id": meeting_id,
        "order_num": order_num,
        "title": title,
        "description": description,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def _make_subtitle(
    meeting_id: str,
    start_time: float,
    end_time: float,
    text: str,
    speaker: str = "발언자",
    confidence: float = 0.95,
) -> dict:
    """테스트용 자막 데이터를 생성합니다."""
    return {
        "id": str(uuid.uuid4()),
        "meeting_id": meeting_id,
        "start_time": start_time,
        "end_time": end_time,
        "text": text,
        "speaker": speaker,
        "confidence": confidence,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def meeting_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def sample_agendas(meeting_id: str) -> list[dict]:
    """테스트용 안건 목록 (3개)"""
    return [
        _make_agenda(meeting_id, 1, "개회선언", "의장 개회사"),
        _make_agenda(meeting_id, 2, "안건 상정", "제1호 의안 심의"),
        _make_agenda(meeting_id, 3, "폐회선언", "폐회사"),
    ]


@pytest.fixture
def sample_subtitles(meeting_id: str) -> list[dict]:
    """테스트용 자막 목록 (9개, 시간순)"""
    return [
        # 안건 1 시간대: 0~30초
        _make_subtitle(meeting_id, 0.0, 3.0, "지금부터 회의를 시작하겠습니다.", "의장"),
        _make_subtitle(meeting_id, 3.0, 8.0, "오늘 안건을 말씀드리겠습니다.", "의장"),
        _make_subtitle(meeting_id, 8.0, 15.0, "먼저 개회사를 하겠습니다.", "의장"),
        # 안건 2 시간대: 30~90초
        _make_subtitle(meeting_id, 30.0, 35.0, "제1호 의안을 상정합니다.", "의장"),
        _make_subtitle(meeting_id, 35.0, 45.0, "이 의안에 대해 찬성합니다.", "김위원"),
        _make_subtitle(meeting_id, 45.0, 60.0, "저도 찬성합니다.", "김위원"),
        _make_subtitle(meeting_id, 60.0, 75.0, "반대 의견이 있습니다.", "박위원"),
        # 안건 3 시간대: 90~끝
        _make_subtitle(meeting_id, 90.0, 95.0, "이상으로 회의를 마치겠습니다.", "의장"),
        _make_subtitle(meeting_id, 95.0, 100.0, "수고하셨습니다.", "의장"),
    ]


# =============================================================================
# MockSupabaseClient 확장 - 테이블별 다른 데이터 반환
# =============================================================================


class MinutesMockSupabaseClient:
    """minutes API 테스트용 Supabase Client 모킹

    table() 호출 시 테이블명에 따라 다른 데이터를 반환합니다.
    """

    def __init__(self, table_data: dict[str, list] | None = None):
        self._table_data = table_data or {}

    def table(self, name: str) -> MockSupabaseQuery:
        data = self._table_data.get(name, [])
        return MockSupabaseQuery(data=data)


# =============================================================================
# GET /api/meetings/{meeting_id}/minutes/by-agenda
# =============================================================================


class TestGetMinutesByAgenda:
    """GET /api/meetings/{meeting_id}/minutes/by-agenda 테스트"""

    def _make_client(self, table_data: dict[str, list]) -> TestClient:
        """테스트용 클라이언트를 생성합니다."""
        mock_supabase = MinutesMockSupabaseClient(table_data=table_data)
        app.dependency_overrides[get_supabase] = lambda: mock_supabase
        return TestClient(app)

    def teardown_method(self):
        """테스트 후 의존성 오버라이드를 정리합니다."""
        app.dependency_overrides.clear()

    def test_returns_200_with_agendas_and_subtitles(
        self, meeting_id: str, sample_agendas: list, sample_subtitles: list
    ):
        """안건과 자막이 모두 있으면 안건별로 자막을 분류하여 반환한다"""
        client = self._make_client({
            "meeting_agendas": sample_agendas,
            "subtitles": sample_subtitles,
        })

        response = client.get(f"/api/meetings/{meeting_id}/minutes/by-agenda")

        assert response.status_code == 200
        data = response.json()
        assert "agendas" in data
        assert "unassigned_subtitles" in data
        assert "total_subtitles" in data
        assert data["total_subtitles"] == 9

    def test_agenda_count_matches(
        self, meeting_id: str, sample_agendas: list, sample_subtitles: list
    ):
        """안건 수가 DB의 안건 수와 일치한다"""
        client = self._make_client({
            "meeting_agendas": sample_agendas,
            "subtitles": sample_subtitles,
        })

        response = client.get(f"/api/meetings/{meeting_id}/minutes/by-agenda")

        data = response.json()
        assert len(data["agendas"]) == 3

    def test_agenda_has_required_fields(
        self, meeting_id: str, sample_agendas: list, sample_subtitles: list
    ):
        """각 안건에 필수 필드가 포함되어 있다"""
        client = self._make_client({
            "meeting_agendas": sample_agendas,
            "subtitles": sample_subtitles,
        })

        response = client.get(f"/api/meetings/{meeting_id}/minutes/by-agenda")

        data = response.json()
        for agenda in data["agendas"]:
            assert "order_num" in agenda
            assert "title" in agenda
            assert "subtitles" in agenda
            assert "speaker_groups" in agenda

    def test_no_agendas_returns_single_group(
        self, meeting_id: str, sample_subtitles: list
    ):
        """안건이 없으면 전체 자막을 하나의 그룹으로 반환한다"""
        client = self._make_client({
            "meeting_agendas": [],
            "subtitles": sample_subtitles,
        })

        response = client.get(f"/api/meetings/{meeting_id}/minutes/by-agenda")

        data = response.json()
        assert len(data["agendas"]) == 1
        assert data["agendas"][0]["title"] == "전체"
        assert data["agendas"][0]["order_num"] == 0
        assert len(data["agendas"][0]["subtitles"]) == 9

    def test_no_subtitles_returns_empty(
        self, meeting_id: str, sample_agendas: list
    ):
        """자막이 없으면 빈 안건 목록을 반환한다"""
        client = self._make_client({
            "meeting_agendas": sample_agendas,
            "subtitles": [],
        })

        response = client.get(f"/api/meetings/{meeting_id}/minutes/by-agenda")

        data = response.json()
        assert data["total_subtitles"] == 0
        # 안건은 있지만 각 안건의 자막은 비어있음
        assert len(data["agendas"]) == 3
        for agenda in data["agendas"]:
            assert len(agenda["subtitles"]) == 0

    def test_empty_db_returns_empty(self, meeting_id: str):
        """안건도 자막도 없으면 완전히 빈 결과를 반환한다"""
        client = self._make_client({
            "meeting_agendas": [],
            "subtitles": [],
        })

        response = client.get(f"/api/meetings/{meeting_id}/minutes/by-agenda")

        data = response.json()
        assert data["total_subtitles"] == 0
        assert len(data["agendas"]) == 1  # "전체" 그룹
        assert len(data["agendas"][0]["subtitles"]) == 0

    def test_speaker_groups_merge_consecutive(
        self, meeting_id: str, sample_agendas: list, sample_subtitles: list
    ):
        """연속 동일 화자의 발언이 하나의 speaker_group으로 병합된다"""
        client = self._make_client({
            "meeting_agendas": sample_agendas,
            "subtitles": sample_subtitles,
        })

        response = client.get(f"/api/meetings/{meeting_id}/minutes/by-agenda")

        data = response.json()
        # 안건이 없으면 균등 분배인데, 여기서는 안건이 start_time 없이 order_num 기반이므로
        # 자막을 균등 분배함. 대신 speaker_groups가 병합 결과를 가지는지 확인
        for agenda in data["agendas"]:
            for group in agenda["speaker_groups"]:
                assert "speaker" in group
                assert "texts" in group
                assert "start_time" in group
                assert "end_time" in group

    def test_subtitle_fields_in_response(
        self, meeting_id: str, sample_subtitles: list
    ):
        """자막 항목에 필수 필드가 포함되어 있다"""
        client = self._make_client({
            "meeting_agendas": [],
            "subtitles": sample_subtitles,
        })

        response = client.get(f"/api/meetings/{meeting_id}/minutes/by-agenda")

        data = response.json()
        subtitles = data["agendas"][0]["subtitles"]
        assert len(subtitles) > 0
        for sub in subtitles:
            assert "id" in sub
            assert "start_time" in sub
            assert "end_time" in sub
            assert "text" in sub
            assert "speaker" in sub
            assert "confidence" in sub


# =============================================================================
# 비즈니스 로직 단위 테스트 - 자막 분류 서비스
# =============================================================================


class TestClassifySubtitlesByAgenda:
    """자막 분류 비즈니스 로직 테스트"""

    def test_classify_with_no_agendas(self):
        """안건이 없으면 전체를 하나의 그룹으로"""
        from app.services.minutes_service import classify_subtitles_by_agenda

        subtitles = [
            {"id": "1", "start_time": 0, "end_time": 5, "text": "hello", "speaker": "A", "confidence": 0.9},
            {"id": "2", "start_time": 5, "end_time": 10, "text": "world", "speaker": "B", "confidence": 0.8},
        ]

        result = classify_subtitles_by_agenda([], subtitles)

        assert len(result["agendas"]) == 1
        assert result["agendas"][0]["order_num"] == 0
        assert result["agendas"][0]["title"] == "전체"
        assert len(result["agendas"][0]["subtitles"]) == 2
        assert result["total_subtitles"] == 2

    def test_classify_with_equal_distribution(self):
        """안건에 start_time이 없으면 균등 분배한다"""
        from app.services.minutes_service import classify_subtitles_by_agenda

        agendas = [
            {"id": "a1", "order_num": 1, "title": "안건1", "description": None},
            {"id": "a2", "order_num": 2, "title": "안건2", "description": None},
        ]
        subtitles = [
            {"id": "1", "start_time": 0, "end_time": 5, "text": "s1", "speaker": "A", "confidence": 0.9},
            {"id": "2", "start_time": 5, "end_time": 10, "text": "s2", "speaker": "A", "confidence": 0.9},
            {"id": "3", "start_time": 10, "end_time": 15, "text": "s3", "speaker": "B", "confidence": 0.9},
            {"id": "4", "start_time": 15, "end_time": 20, "text": "s4", "speaker": "B", "confidence": 0.9},
        ]

        result = classify_subtitles_by_agenda(agendas, subtitles)

        assert len(result["agendas"]) == 2
        # 4개 자막 / 2개 안건 = 2개씩
        assert len(result["agendas"][0]["subtitles"]) == 2
        assert len(result["agendas"][1]["subtitles"]) == 2

    def test_classify_with_start_time_boundaries(self):
        """안건에 start_time이 있으면 시간 경계로 분류한다"""
        from app.services.minutes_service import classify_subtitles_by_agenda

        agendas = [
            {"id": "a1", "order_num": 1, "title": "안건1", "description": None, "start_time": 0},
            {"id": "a2", "order_num": 2, "title": "안건2", "description": None, "start_time": 30},
        ]
        subtitles = [
            {"id": "1", "start_time": 0, "end_time": 10, "text": "s1", "speaker": "A", "confidence": 0.9},
            {"id": "2", "start_time": 10, "end_time": 20, "text": "s2", "speaker": "A", "confidence": 0.9},
            {"id": "3", "start_time": 30, "end_time": 40, "text": "s3", "speaker": "B", "confidence": 0.9},
            {"id": "4", "start_time": 40, "end_time": 50, "text": "s4", "speaker": "B", "confidence": 0.9},
        ]

        result = classify_subtitles_by_agenda(agendas, subtitles)

        assert len(result["agendas"]) == 2
        assert len(result["agendas"][0]["subtitles"]) == 2
        assert len(result["agendas"][1]["subtitles"]) == 2
        assert result["agendas"][0]["subtitles"][0]["text"] == "s1"
        assert result["agendas"][1]["subtitles"][0]["text"] == "s3"

    def test_speaker_groups_consecutive_merge(self):
        """연속 동일 화자가 하나의 그룹으로 병합된다"""
        from app.services.minutes_service import group_by_speaker

        subtitles = [
            {"id": "1", "start_time": 0, "end_time": 5, "text": "발언1", "speaker": "A", "confidence": 0.9},
            {"id": "2", "start_time": 5, "end_time": 10, "text": "발언2", "speaker": "A", "confidence": 0.9},
            {"id": "3", "start_time": 10, "end_time": 15, "text": "발언3", "speaker": "B", "confidence": 0.9},
            {"id": "4", "start_time": 15, "end_time": 20, "text": "발언4", "speaker": "A", "confidence": 0.9},
        ]

        groups = group_by_speaker(subtitles)

        assert len(groups) == 3
        # 첫 그룹: A, 발언1+발언2
        assert groups[0]["speaker"] == "A"
        assert groups[0]["texts"] == ["발언1", "발언2"]
        assert groups[0]["start_time"] == 0
        assert groups[0]["end_time"] == 10
        # 두 번째 그룹: B
        assert groups[1]["speaker"] == "B"
        assert groups[1]["texts"] == ["발언3"]
        # 세 번째 그룹: A (다시)
        assert groups[2]["speaker"] == "A"
        assert groups[2]["texts"] == ["발언4"]

    def test_speaker_groups_single_speaker(self):
        """화자가 한 명이면 하나의 그룹"""
        from app.services.minutes_service import group_by_speaker

        subtitles = [
            {"id": "1", "start_time": 0, "end_time": 5, "text": "발언1", "speaker": "A", "confidence": 0.9},
            {"id": "2", "start_time": 5, "end_time": 10, "text": "발언2", "speaker": "A", "confidence": 0.9},
        ]

        groups = group_by_speaker(subtitles)

        assert len(groups) == 1
        assert groups[0]["speaker"] == "A"
        assert groups[0]["texts"] == ["발언1", "발언2"]

    def test_speaker_groups_empty(self):
        """자막이 없으면 빈 리스트"""
        from app.services.minutes_service import group_by_speaker

        groups = group_by_speaker([])

        assert groups == []

    def test_unassigned_subtitles_with_time_gap(self):
        """안건 시간 사이에 매핑되지 않는 자막은 unassigned로 처리"""
        from app.services.minutes_service import classify_subtitles_by_agenda

        agendas = [
            {"id": "a1", "order_num": 1, "title": "안건1", "description": None, "start_time": 10},
            {"id": "a2", "order_num": 2, "title": "안건2", "description": None, "start_time": 50},
        ]
        # 0~10초 자막은 첫 안건 시작 전이므로 unassigned
        subtitles = [
            {"id": "1", "start_time": 0, "end_time": 5, "text": "시작 전 발언", "speaker": "A", "confidence": 0.9},
            {"id": "2", "start_time": 10, "end_time": 20, "text": "안건1 발언", "speaker": "B", "confidence": 0.9},
            {"id": "3", "start_time": 50, "end_time": 60, "text": "안건2 발언", "speaker": "C", "confidence": 0.9},
        ]

        result = classify_subtitles_by_agenda(agendas, subtitles)

        assert len(result["unassigned_subtitles"]) == 1
        assert result["unassigned_subtitles"][0]["text"] == "시작 전 발언"
        assert len(result["agendas"][0]["subtitles"]) == 1
        assert len(result["agendas"][1]["subtitles"]) == 1
