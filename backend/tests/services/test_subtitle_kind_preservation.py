"""실시간 자막(초안) 보존 테스트

회의 상세의 [실시간 자막(초안) | AI 자막(완성본)] 두 탭은 subtitles.kind 로 갈린다.
AI 자막을 다시 만들 때 kind 를 가리지 않고 지우면 초안이 영구히 사라진다 —
회의는 이미 끝났으므로 복구할 방법이 없다. 그 경로들을 여기서 지킨다.
"""

from unittest.mock import MagicMock, patch

from app.repositories.subtitle_repository import SubtitleRepository


class _DeleteSpy:
    """supabase delete 체인을 흉내 내며 eq() 호출을 기록한다."""

    def __init__(self):
        self.filters: dict[str, str] = {}
        self.executed = False

    def eq(self, column: str, value: str):
        self.filters[column] = value
        return self

    def execute(self):
        self.executed = True
        return MagicMock(data=[])


def _repo_with_spy() -> tuple[SubtitleRepository, _DeleteSpy]:
    spy = _DeleteSpy()
    table = MagicMock()
    table.delete.return_value = spy
    db = MagicMock()
    db.table.return_value = table
    return SubtitleRepository(db), spy


class TestDeleteByMeeting:
    def test_kind_ai_deletes_only_ai_subtitles(self):
        """AI 자막 재생성은 kind='ai' 만 지워야 한다."""
        repo, spy = _repo_with_spy()

        repo.delete_by_meeting("m-1", kind="ai")

        assert spy.filters == {"meeting_id": "m-1", "kind": "ai"}
        assert spy.executed

    def test_without_kind_deletes_everything(self):
        """자막 전체 삭제(관리 기능)는 종류를 가리지 않는다 — 기존 동작 유지."""
        repo, spy = _repo_with_spy()

        repo.delete_by_meeting("m-1")

        assert spy.filters == {"meeting_id": "m-1"}
        assert "kind" not in spy.filters


class TestRealtimeSubtitleKind:
    def test_realtime_persist_marks_subtitle_as_live(self):
        """kind 를 안 넣으면 컬럼 기본값 'ai' 가 붙어 초안이 AI 자막으로 둔갑한다."""
        from app.services import openai_realtime_stt as mod

        captured: dict = {}

        class _Insert:
            def execute(self):
                return MagicMock(data=[])

        def _insert(payload):
            captured.update(payload)
            return _Insert()

        table = MagicMock()
        table.insert.side_effect = _insert
        # meetings 업데이트 체인은 관심 밖 — 기본 MagicMock 으로 흘려보낸다
        client = MagicMock()
        client.table.return_value = table

        service = mod.OpenAiRealtimeSttService.__new__(mod.OpenAiRealtimeSttService)
        service._stage_promoted = set()

        subtitle = {
            "id": "s-1",
            "meeting_id": "m-1",
            "text": "회의를 시작하겠습니다",
            "start_time": 0.0,
            "end_time": 2.0,
            "speaker": None,
            "confidence": 0.9,
        }

        with patch.object(mod, "get_supabase_client", return_value=client):
            import asyncio

            asyncio.run(service._persist_subtitle({"subtitle": subtitle}))

        assert captured.get("kind") == "live", "실시간 자막은 kind='live' 로 저장해야 한다"


class TestMergeKeepsKindsApart:
    def test_merge_targets_a_single_kind(self):
        """초안과 완성본을 한 덩어리로 병합하면 두 탭이 모두 망가진다."""
        from app.services import subtitle_edit_service as mod

        rows = [
            {"id": "l1", "text": "초안1", "start_time": 0.0, "end_time": 1.0, "kind": "live", "speaker": None, "confidence": 0.8},
            {"id": "l2", "text": "초안2", "start_time": 1.0, "end_time": 2.0, "kind": "live", "speaker": None, "confidence": 0.8},
            {"id": "a1", "text": "완성본1", "start_time": 0.0, "end_time": 1.0, "kind": "ai", "speaker": "홍길동 의원", "confidence": 0.95},
            {"id": "a2", "text": "완성본2", "start_time": 1.0, "end_time": 2.0, "kind": "ai", "speaker": "홍길동 의원", "confidence": 0.95},
        ]

        repo = MagicMock()
        repo.list_all_ordered.return_value = rows
        # 병합 결과는 실제 로직이 만들되, 개수만 줄어들면 삭제·삽입 경로를 탄다
        with patch.object(mod, "SubtitleRepository", return_value=repo), patch.object(
            mod.VodSttService,
            "_merge_short_utterances",
            return_value=[
                {
                    "meeting_id": "m-1",
                    "text": "완성본1 완성본2",
                    "start_time": 0.0,
                    "end_time": 2.0,
                    "speaker": "홍길동 의원",
                    "confidence": 0.95,
                }
            ],
        ):
            result = mod.merge_short(MagicMock(), "m-1", gap_threshold=1.0, min_length=10)

        # 병합 대상은 AI 자막 2건뿐 — 초안 2건은 세지도, 지우지도 않는다
        assert result["original_count"] == 2
        repo.delete_by_meeting.assert_called_once_with("m-1", kind="ai")
        inserted = repo.insert_many.call_args[0][0]
        assert all(row["kind"] == "ai" for row in inserted)
