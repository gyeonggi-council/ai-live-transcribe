# -*- coding: utf-8 -*-
"""화자별 연속 발언구간 API 테스트 — GET /api/meetings/{meeting_id}/speakers/segments

발언영상 추출 기능의 데이터 원천. 연속된 같은 화자 발언을 강제 분할 없이 병합한다.
"""

import uuid

from fastapi.testclient import TestClient

from app.core.database import get_supabase
from app.main import app
from tests.conftest import MockSupabaseClient

MEETING_ID = str(uuid.uuid4())
MEETING_ROW = {
    "id": MEETING_ID,
    "title": "제391회 테스트 위원회",
    "kms_midx": "138176",
}


def _sub(
    start: float,
    end: float,
    text: str,
    speaker: str | None,
    kind: str = "ai",
) -> dict:
    """Supabase 응답 형태의 자막 dict를 생성합니다."""
    return {
        "id": str(uuid.uuid4()),
        "meeting_id": MEETING_ID,
        "start_time": start,
        "end_time": end,
        "text": text,
        "speaker": speaker,
        "kind": kind,
    }


def _make_client(meetings: list[dict], subtitles: list[dict]) -> TestClient:
    """meetings/subtitles 데이터를 가진 모킹 클라이언트를 만듭니다."""
    mock = MockSupabaseClient(
        table_data={"meetings": meetings, "subtitles": subtitles}
    )
    app.dependency_overrides[get_supabase] = lambda: mock
    return TestClient(app)


class TestSpeakerSegmentsApi:
    """GET /api/meetings/{meeting_id}/speakers/segments 테스트"""

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_segments_merges_consecutive_same_speaker(self):
        """연속된 같은 화자 자막이 하나의 구간으로 병합된다."""
        subs = [
            _sub(0, 5, "안녕하세요.", "김위원"),
            _sub(5, 10, "질의하겠습니다.", "김위원"),
            _sub(10, 15, "답변 드리겠습니다.", "국장"),
            _sub(15, 20, "추가 질의입니다.", "김위원"),
        ]
        client = _make_client([MEETING_ROW], subs)

        response = client.get(f"/api/meetings/{MEETING_ID}/speakers/segments")

        assert response.status_code == 200
        data = response.json()
        speakers = {s["speaker"]: s for s in data["speakers"]}
        kim = speakers["김위원"]
        assert kim["segment_count"] == 2
        assert kim["total_time"] == 15
        first = kim["segments"][0]
        assert first["start_time"] == 0
        assert first["end_time"] == 10
        assert first["duration"] == 10
        assert first["subtitle_count"] == 2
        # total_time 내림차순: 김위원(15초)이 국장(5초)보다 앞
        assert data["speakers"][0]["speaker"] == "김위원"

    def test_segments_no_forced_split_for_long_speech(self):
        """150초를 넘는 연속 발언도 강제 분할 없이 하나의 구간으로 유지된다."""
        subs = [
            _sub(0, 60, "발언 1", "박위원"),
            _sub(60, 120, "발언 2", "박위원"),
            _sub(120, 180, "발언 3", "박위원"),
            _sub(180, 240, "발언 4", "박위원"),
        ]
        client = _make_client([MEETING_ROW], subs)

        response = client.get(f"/api/meetings/{MEETING_ID}/speakers/segments")

        assert response.status_code == 200
        data = response.json()
        assert len(data["speakers"]) == 1
        park = data["speakers"][0]
        assert park["segment_count"] == 1
        seg = park["segments"][0]
        assert seg["start_time"] == 0
        assert seg["end_time"] == 240
        assert seg["duration"] == 240
        assert seg["subtitle_count"] == 4

    def test_segments_prefers_ai_subtitles(self):
        """live+ai 혼재 시 AI 자막만 사용한다 ('(미지정)' 부풀림 방지)."""
        subs = [
            _sub(0, 5, "라이브 자막 1", None, kind="live"),
            _sub(5, 10, "라이브 자막 2", None, kind="live"),
            _sub(0, 5, "AI 자막입니다.", "이위원", kind="ai"),
        ]
        client = _make_client([MEETING_ROW], subs)

        response = client.get(f"/api/meetings/{MEETING_ID}/speakers/segments")

        assert response.status_code == 200
        data = response.json()
        names = [s["speaker"] for s in data["speakers"]]
        assert names == ["이위원"]
        assert data["speakers"][0]["segments"][0]["text_preview"] == "AI 자막입니다."

    def test_segments_meeting_not_found_404(self):
        """회의가 없으면 404를 반환한다."""
        client = _make_client([], [])

        response = client.get(f"/api/meetings/{uuid.uuid4()}/speakers/segments")

        assert response.status_code == 404

    def test_segments_includes_kms_midx_and_preview(self):
        """kms_midx·메타데이터가 포함되고 text_preview는 첫 80자로 잘린다."""
        long_text = "가나다라마바사아자차" * 10  # 100자
        subs = [_sub(0, 30, long_text, "최위원")]
        client = _make_client([MEETING_ROW], subs)

        response = client.get(f"/api/meetings/{MEETING_ID}/speakers/segments")

        assert response.status_code == 200
        data = response.json()
        assert data["meeting_id"] == MEETING_ID
        assert data["kms_midx"] == "138176"
        assert data["title"] == "제391회 테스트 위원회"
        assert data["total_duration"] == 30
        preview = data["speakers"][0]["segments"][0]["text_preview"]
        assert preview == long_text[:80]
        assert len(preview) == 80
