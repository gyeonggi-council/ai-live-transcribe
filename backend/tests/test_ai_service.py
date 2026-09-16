"""AI 어시스턴트 서비스 + API 테스트 (TDD RED -> GREEN)

# @TASK P11B - AI Assistant tests
# @TEST tests/test_ai_service.py
"""

import uuid
from typing import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.database import get_supabase
from app.main import app
from app.services.auth_service import create_access_token
from tests.conftest import (
    MockSupabaseClient,
    MockSupabaseQuery,
    MockSupabaseResponse,
    TEST_ADMIN_USER,
    TEST_ADMIN_USER_ID,
)


def _mock_httpx_openai(response_content: str):
    """OpenAI httpx 호출을 mock하는 context manager를 반환합니다.

    response.json()은 동기 메서드이므로 MagicMock을 사용합니다.
    """
    mock_response_data = {
        "choices": [{"message": {"content": response_content}}]
    }

    mock_resp = MagicMock()
    mock_resp.json.return_value = mock_response_data
    mock_resp.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_resp
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    return patch("httpx.AsyncClient", return_value=mock_client)


# ---------------------------------------------------------------------------
# AI-aware mock: ai_conversations 테이블 insert 지원
# ---------------------------------------------------------------------------
class AiAwareMockQuery(MockSupabaseQuery):
    """ai_conversations 테이블의 insert를 추적하는 mock."""

    def __init__(self, data: list | None = None, count: int | None = None):
        super().__init__(data, count)
        self.inserted: list[dict] = []

    def insert(self, record: dict) -> "AiAwareMockQuery":
        self.inserted.append(record)
        return self

    def execute(self) -> MockSupabaseResponse:
        return MockSupabaseResponse(data=self._data, count=self._count)


class AiMockSupabaseClient(MockSupabaseClient):
    """AI 테스트용 Supabase mock - ai_conversations insert 추적."""

    def __init__(self, table_data: dict[str, list] | None = None):
        super().__init__(table_data)
        self.ai_query = AiAwareMockQuery(
            data=self._table_data.get("ai_conversations", [])
        )

    def table(self, name: str) -> MockSupabaseQuery:
        if name == "ai_conversations":
            return self.ai_query
        return super().table(name)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
MEETING_ID = str(uuid.uuid4())

MOCK_SUBTITLES = [
    {
        "id": str(uuid.uuid4()),
        "meeting_id": MEETING_ID,
        "text": "경기도 예산안에 대해 논의하겠습니다",
        "speaker": "위원장",
        "start_time": 0.0,
        "end_time": 5.0,
        "confidence": 0.95,
    },
    {
        "id": str(uuid.uuid4()),
        "meeting_id": MEETING_ID,
        "text": "교육 분야 예산 증액을 제안합니다",
        "speaker": "김의원",
        "start_time": 5.0,
        "end_time": 10.0,
        "confidence": 0.92,
    },
]

MOCK_BILLS = [
    {
        "id": str(uuid.uuid4()),
        "bill_number": "제2026-001호",
        "title": "경기도 교육 지원 조례안",
        "proposer": "김의원",
        "committee": "교육위원회",
        "status": "reviewing",
    },
]


MOCK_MEETING = {
    "id": MEETING_ID,
    "title": "제393회 제3차 도시환경위원회",
    "meeting_date": "2026-09-02",
    "committee": "도시환경위원회",
    "duration_seconds": 7200,
    "status": "ended",
}

GUEST_ID = "3f1c2a4e-1111-4222-8333-444455556666"
GUEST_HEADER = {"X-Guest-Id": GUEST_ID}


def _make_ai_client(
    subtitles: list | None = None,
    bills: list | None = None,
    conversations: list | None = None,
    meetings: list | None = None,
) -> AiMockSupabaseClient:
    return AiMockSupabaseClient(
        table_data={
            "subtitles": subtitles or MOCK_SUBTITLES,
            "bills": bills or MOCK_BILLS,
            "meetings": [MOCK_MEETING] if meetings is None else meetings,
            "ai_conversations": conversations or [],
        }
    )


def _conv_row(session_id: str, role: str, content: str, owner_key: str | None, created_at: str,
              meeting_context_id: str | None = None) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "session_id": session_id,
        "user_id": None,
        "owner_key": owner_key,
        "role": role,
        "content": content,
        "sources": None,
        "meeting_context_id": meeting_context_id,
        "created_at": created_at,
    }


@pytest.fixture(autouse=True)
def _reset_rate_limit():
    """하루 한도 카운터는 인메모리라 테스트 사이에 누적된다(IP testclient 10회) — 매 테스트 초기화."""
    from app.api import ai as ai_mod

    ai_mod._chat_calls.clear()
    yield
    ai_mod._chat_calls.clear()


@pytest.fixture
def ai_client() -> Generator[TestClient, None, None]:
    mock_supabase = _make_ai_client()
    app.dependency_overrides[get_supabase] = lambda: mock_supabase
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def auth_header() -> dict[str, str]:
    token = create_access_token({"sub": TEST_ADMIN_USER_ID, "role": "admin"})
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# 1. search_context 테스트
# ---------------------------------------------------------------------------
class TestSearchContext:
    """RAG 검색 함수 테스트."""

    @pytest.mark.asyncio
    async def test_search_context_returns_results(self):
        """검색 키워드와 매칭되는 자막이 반환되어야 합니다."""
        from app.services.ai_rag_service import search_context

        mock_sb = _make_ai_client()
        results = await search_context(mock_sb, "예산")
        # MockSupabaseQuery는 ilike 필터를 실제 적용하지 않으므로 전체 데이터 반환
        assert isinstance(results, list)
        assert len(results) > 0
        assert results[0]["source_type"] == "subtitle"

    @pytest.mark.asyncio
    async def test_search_context_with_meeting_filter(self):
        """meeting_context_id가 있으면 해당 회의만 검색해야 합니다."""
        from app.services.ai_rag_service import search_context

        mock_sb = _make_ai_client()
        results = await search_context(mock_sb, "예산", MEETING_ID)
        assert isinstance(results, list)
        # 의안은 meeting_context_id 있을 때 검색 안 함
        bill_results = [r for r in results if r.get("source_type") == "bill"]
        assert len(bill_results) == 0
        # 회의 한정은 rag_context 가 조립한 컨텍스트 블록 하나 + 회의 메타
        block = next(r for r in results if r["source_type"] == "context_block")
        assert "예산" in block["text"]
        assert all(src["meeting_title"] == MOCK_MEETING["title"] for src in block["sources"])
        meta = next(r for r in results if r["source_type"] == "meeting_meta")
        assert meta["id"] == MEETING_ID

    @pytest.mark.asyncio
    async def test_search_context_unknown_meeting_raises(self):
        """없는 회의면 LookupError — 라우터가 404 로 낸다."""
        from app.services.ai_rag_service import search_context

        mock_sb = _make_ai_client(meetings=[])
        with pytest.raises(LookupError):
            await search_context(mock_sb, "예산", str(uuid.uuid4()))


class TestGlobalSearchHelpers:
    """여러 회의 검색 — 검색어 화이트리스트·토큰 OR 문법·회의별 분산(순수 함수)."""

    def test_search_terms_are_safe_and_bounded(self):
        from app.services.ai_rag_service import search_terms

        terms = search_terms("예산 삭감(2) 얘기, 김태희 의원이 뭐라고 했나?")
        assert "예산" in terms and "삭감" in terms and "김태희" in terms
        assert all(__import__("re").match(r"^[0-9A-Za-z가-힣]{2,20}$", t) for t in terms)
        assert len(terms) <= 6
        assert search_terms("?!,()") == []

    def test_build_ilike_or_syntax(self):
        from app.services.ai_rag_service import build_ilike_or

        assert build_ilike_or(["예산", "삭감"]) == "text.ilike.*예산*,text.ilike.*삭감*"
        assert build_ilike_or(["예산,삭감", "ok"], "title") == "title.ilike.*ok*"

    def test_distribute_prefers_ai_per_meeting_and_caps(self):
        from app.services.ai_rag_service import distribute_global_hits

        rows = []
        for i in range(10):  # 회의 A: ai+live 혼재, 히트 많음
            rows.append({"meeting_id": "A", "text": "예산 삭감 논의", "start_time": i, "kind": "ai"})
            rows.append({"meeting_id": "A", "text": "예산 삭감 논의", "start_time": i, "kind": "live"})
        rows.append({"meeting_id": "B", "text": "예산 이야기", "start_time": 1, "kind": "live"})  # 회의 B: live 만
        out = distribute_global_hits(rows, ["예산", "삭감"])
        a = [r for r in out if r["meeting_id"] == "A"]
        b = [r for r in out if r["meeting_id"] == "B"]
        assert len(a) == 4 and all(r["kind"] == "ai" for r in a)  # 회의별 상한·AI 우선
        assert len(b) == 1  # B 의 live 자막이 A 때문에 사라지지 않는다
        assert out[0]["meeting_id"] == "A"  # 점수 높은 회의 먼저

    @pytest.mark.asyncio
    async def test_scope_only_context_is_empty_prompt(self):
        """검색 결과가 0건이면 범위 안내만 남는데, 그건 자료가 아니다 — 모델을 부르지 않는다(Codex 검토)."""
        from app.services.ai_rag_service import _format_context_for_prompt, generate_answer

        ctx = [{"source_type": "scope", "days": 30, "committee": None, "meetings": 0, "terms": ["예산"]}]
        assert _format_context_for_prompt(ctx) == ""
        with patch("app.services.ai_rag_service.settings.openai_api_key", ""):
            result = await generate_answer("예산", ctx)
        assert "찾지 못했습니다" in result["answer"]

    def test_chat_rows_have_explicit_ordered_timestamps(self):
        """한 INSERT 의 질문·답변은 created_at 을 명시해 순서를 고정한다(답변 = 질문 + 1ms)."""
        mock_sb = _make_ai_client()
        app.dependency_overrides[get_supabase] = lambda: mock_sb
        client = TestClient(app)
        try:
            with patch("app.services.ai_rag_service.settings.openai_api_key", "sk-test"), _mock_httpx_openai("답"):
                client.post("/api/ai/chat", json={"question": "q"}, headers=GUEST_HEADER)
            rows = mock_sb.ai_query.inserted[0]
            assert rows[0]["created_at"] < rows[1]["created_at"]
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_global_search_scopes_meetings_first(self):
        """회의 미선택: 기간 안의 회의 → 그 회의들의 자막 → 결과에 회의 제목·범위 표시."""
        from app.services.ai_rag_service import search_context

        subs = [dict(MOCK_SUBTITLES[0], kind="ai"), dict(MOCK_SUBTITLES[1], kind="ai")]
        mock_sb = _make_ai_client(subtitles=subs)
        results = await search_context(mock_sb, "예산 증액", scope={"days": 30})
        subs_out = [r for r in results if r["source_type"] == "subtitle"]
        assert subs_out and all(r["meeting_title"] == MOCK_MEETING["title"] for r in subs_out)
        scope = next(r for r in results if r["source_type"] == "scope")
        assert scope["days"] == 30 and scope["meetings"] == 1 and "예산" in scope["terms"]


# ---------------------------------------------------------------------------
# 2. generate_answer 테스트
# ---------------------------------------------------------------------------
class TestGenerateAnswer:
    """AI 답변 생성 테스트."""

    @pytest.mark.asyncio
    async def test_generate_answer_with_context(self):
        """컨텍스트가 있으면 AI 답변이 생성되어야 합니다."""
        from app.services.ai_rag_service import generate_answer

        context = [
            {
                "source_type": "subtitle",
                "meeting_id": MEETING_ID,
                "text": "교육 예산 증액 논의",
                "speaker": "김의원",
                "start_time": 5.0,
                "end_time": 10.0,
            }
        ]

        with patch("app.services.ai_rag_service.settings.openai_api_key", "sk-test"), _mock_httpx_openai(
            "교육 예산 증액에 대해 김의원이 제안했습니다."
        ):
            result = await generate_answer("교육 예산은?", context)

        assert "answer" in result
        assert result["answer"] == "교육 예산 증액에 대해 김의원이 제안했습니다."
        assert "sources" in result

    @pytest.mark.asyncio
    async def test_generate_answer_not_configured_raises(self):
        """키가 없으면 AiNotConfiguredError — 오류 문구를 답변으로 위장하지 않는다."""
        from app.services.ai_rag_service import AiNotConfiguredError, generate_answer

        with patch("app.services.ai_rag_service.settings.openai_api_key", ""):
            with pytest.raises(AiNotConfiguredError):
                await generate_answer("q", [{"source_type": "subtitle", "meeting_id": MEETING_ID, "text": "x"}])

    @pytest.mark.asyncio
    async def test_generate_answer_upstream_failure_raises(self):
        from app.services.ai_rag_service import AiUpstreamError, generate_answer

        mock_client = AsyncMock()
        mock_client.post.side_effect = RuntimeError("boom")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        with patch("app.services.ai_rag_service.settings.openai_api_key", "sk-test"), patch(
            "httpx.AsyncClient", return_value=mock_client
        ):
            with pytest.raises(AiUpstreamError):
                await generate_answer("q", [{"source_type": "subtitle", "meeting_id": MEETING_ID, "text": "x"}])

    @pytest.mark.asyncio
    async def test_generate_answer_empty_context(self):
        """컨텍스트가 비어 있으면 안내 메시지를 반환해야 합니다."""
        from app.services.ai_rag_service import generate_answer

        result = await generate_answer("아무 질문", [])
        assert "찾지 못했습니다" in result["answer"]


# ---------------------------------------------------------------------------
# 3. Chat API 테스트
# ---------------------------------------------------------------------------
class TestChatApi:
    """POST /api/ai/chat 테스트."""

    def test_chat_api_returns_answer(self, ai_client: TestClient):
        """채팅 API가 답변을 반환해야 합니다."""
        with patch("app.services.ai_rag_service.settings.openai_api_key", "sk-test"), _mock_httpx_openai("테스트 답변입니다."):
            resp = ai_client.post("/api/ai/chat", json={"question": "예산 관련 논의?"})

        assert resp.status_code == 200
        data = resp.json()
        assert "answer" in data
        assert "session_id" in data
        assert data["answer"] == "테스트 답변입니다."
        # 소유자(로그인·손님 표식) 없음 → 저장 안 함
        assert data["saved"] is False

    def test_unknown_session_id_gets_server_issued_id(self, ai_client: TestClient):
        """DB 에 없는 session_id 는 채택하지 않고 서버가 새 ID 를 발급한다."""
        sid = str(uuid.uuid4())
        with patch("app.services.ai_rag_service.settings.openai_api_key", "sk-test"), _mock_httpx_openai("OK"):
            resp = ai_client.post("/api/ai/chat", json={"question": "질문", "session_id": sid})
        assert resp.status_code == 200
        assert resp.json()["session_id"] != sid
        uuid.UUID(resp.json()["session_id"])

    def test_foreign_session_is_404(self):
        """남의 세션 ID 로 이어 쓰면 404 — 그 이력이 컨텍스트로 들어가던 구멍."""
        sid = str(uuid.uuid4())
        rows = [_conv_row(sid, "user", "남의 질문", "user:someone-else", "2026-09-14T01:00:00+09:00")]
        mock_sb = _make_ai_client(conversations=rows)
        app.dependency_overrides[get_supabase] = lambda: mock_sb
        client = TestClient(app)
        try:
            with patch("app.services.ai_rag_service.settings.openai_api_key", "sk-test"), _mock_httpx_openai("OK"):
                resp = client.post("/api/ai/chat", json={"question": "질문", "session_id": sid}, headers=GUEST_HEADER)
            assert resp.status_code == 404
        finally:
            app.dependency_overrides.clear()

    def test_same_owner_other_meeting_is_400(self):
        """같은 소유자라도 세션의 회의와 다른 회의를 실으면 400 — 회의 변경은 새 대화."""
        sid = str(uuid.uuid4())
        other = str(uuid.uuid4())
        rows = [_conv_row(sid, "user", "질문", f"guest:{GUEST_ID}", "2026-09-14T01:00:00+09:00", meeting_context_id=other)]
        mock_sb = _make_ai_client(conversations=rows)
        app.dependency_overrides[get_supabase] = lambda: mock_sb
        client = TestClient(app)
        try:
            with patch("app.services.ai_rag_service.settings.openai_api_key", "sk-test"), _mock_httpx_openai("OK"):
                resp = client.post(
                    "/api/ai/chat",
                    json={"question": "질문", "session_id": sid, "meeting_context_id": MEETING_ID},
                    headers=GUEST_HEADER,
                )
            assert resp.status_code == 400
        finally:
            app.dependency_overrides.clear()

    def test_own_session_continues_and_history_is_latest_first_reversed(self):
        """본인 세션은 이어지고, 이력은 최근 N 건을 오래된 순으로 생성기에 넘긴다."""
        sid = str(uuid.uuid4())
        owner = f"guest:{GUEST_ID}"
        rows = [_conv_row(sid, "user", f"q{i}", owner, f"2026-09-14T01:{i:02d}:00+09:00") for i in range(5)]
        mock_sb = _make_ai_client(conversations=rows)
        app.dependency_overrides[get_supabase] = lambda: mock_sb
        client = TestClient(app)
        try:
            with patch("app.services.ai_rag_service.settings.openai_api_key", "sk-test"), patch(
                "app.api.ai.generate_answer", new_callable=AsyncMock
            ) as gen:
                gen.return_value = {"answer": "A", "sources": []}
                resp = client.post("/api/ai/chat", json={"question": "질문", "session_id": sid}, headers=GUEST_HEADER)
            assert resp.status_code == 200
            assert resp.json()["session_id"] == sid
            history = gen.call_args.args[3]
            # 서버는 DB 가 최신순(desc)으로 준 것을 뒤집어 오래된 순으로 만든다. mock 은 정렬을 안 하므로 입력 순서가 뒤집혀 온다
            assert [h["content"] for h in history] == ["q4", "q3", "q2", "q1", "q0"]
        finally:
            app.dependency_overrides.clear()

    def test_history_query_is_owner_scoped(self):
        """멀티턴 이력도 소유자 조건으로 읽는다 — 첫 행만 내 것이고 뒤에 남의 행이 섞인 옛 세션 방어(Codex 2차 P1)."""
        sid = str(uuid.uuid4())
        owner = f"guest:{GUEST_ID}"
        rows = [_conv_row(sid, "user", "내 질문", owner, "2026-09-14T01:00:00+09:00")]
        mock_sb = _make_ai_client(conversations=rows)
        calls: list[tuple] = []
        orig_eq = mock_sb.ai_query.eq

        def spy_eq(*a, **k):
            calls.append(a)
            return orig_eq(*a, **k)

        mock_sb.ai_query.eq = spy_eq
        app.dependency_overrides[get_supabase] = lambda: mock_sb
        client = TestClient(app)
        try:
            with patch("app.services.ai_rag_service.settings.openai_api_key", "sk-test"), patch(
                "app.api.ai.generate_answer", new_callable=AsyncMock
            ) as gen:
                gen.return_value = {"answer": "A", "sources": []}
                resp = client.post("/api/ai/chat", json={"question": "질문", "session_id": sid}, headers=GUEST_HEADER)
            assert resp.status_code == 200
            assert ("owner_key", owner) in calls
        finally:
            app.dependency_overrides.clear()

    def test_unknown_meeting_is_404(self):
        mock_sb = _make_ai_client(meetings=[])  # mock 은 eq 를 안 걸므로 회의 표를 비워 "없음" 을 만든다
        app.dependency_overrides[get_supabase] = lambda: mock_sb
        client = TestClient(app)
        try:
            with patch("app.services.ai_rag_service.settings.openai_api_key", "sk-test"), _mock_httpx_openai("OK"):
                resp = client.post("/api/ai/chat", json={"question": "질문", "meeting_context_id": str(uuid.uuid4())})
            assert resp.status_code == 404
        finally:
            app.dependency_overrides.clear()

    def test_not_configured_is_503(self, ai_client: TestClient):
        with patch("app.services.ai_rag_service.settings.openai_api_key", ""):
            resp = ai_client.post("/api/ai/chat", json={"question": "예산"})
        assert resp.status_code == 503

    def test_upstream_failure_is_502_and_not_saved(self):
        mock_sb = _make_ai_client()
        app.dependency_overrides[get_supabase] = lambda: mock_sb
        client = TestClient(app)
        mock_client = AsyncMock()
        mock_client.post.side_effect = RuntimeError("boom")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        try:
            with patch("app.services.ai_rag_service.settings.openai_api_key", "sk-test"), patch(
                "httpx.AsyncClient", return_value=mock_client
            ):
                resp = client.post("/api/ai/chat", json={"question": "예산"}, headers=GUEST_HEADER)
            assert resp.status_code == 502
            assert mock_sb.ai_query.inserted == []
        finally:
            app.dependency_overrides.clear()

    def test_kst_day_boundary(self):
        """일자 경계는 KST — 한국의 '내일' 에 한도가 열린다."""
        from datetime import datetime as dt
        from app.api import ai as ai_mod

        with patch.object(ai_mod, "datetime") as fake_dt:
            fake_dt.now.return_value = dt(2026, 9, 14, 23, 30, tzinfo=ai_mod.KST)
            assert ai_mod._today() == "2026-09-14"
            fake_dt.now.assert_called_with(ai_mod.KST)


# ---------------------------------------------------------------------------
# 4. Conversation 저장 테스트 (로그인 사용자)
# ---------------------------------------------------------------------------
class TestConversationSaved:
    """로그인 사용자의 대화 이력 저장 테스트."""

    def test_conversation_saved_for_logged_in_user(self, auth_header: dict):
        """로그인 상태에서 채팅하면 대화가 DB에 저장되어야 합니다."""
        mock_sb = _make_ai_client()
        app.dependency_overrides[get_supabase] = lambda: mock_sb
        client = TestClient(app)

        with patch("app.services.ai_rag_service.settings.openai_api_key", "sk-test"), _mock_httpx_openai("답변"):
            resp = client.post(
                "/api/ai/chat",
                json={"question": "테스트 질문"},
                headers=auth_header,
            )

        assert resp.status_code == 200
        assert resp.json()["saved"] is True
        # 질문+답변을 한 번의 insert 로(반쪽 저장 방지), 소유자 키는 user:<id>
        assert len(mock_sb.ai_query.inserted) == 1
        rows = mock_sb.ai_query.inserted[0]
        assert [r["role"] for r in rows] == ["user", "assistant"]
        assert all(r["owner_key"] == f"user:{TEST_ADMIN_USER_ID}" for r in rows)

        app.dependency_overrides.clear()

    def test_guest_header_owns_history(self):
        """손님 표식(X-Guest-Id)이 있으면 guest:<id> 소유로 저장된다."""
        mock_sb = _make_ai_client()
        app.dependency_overrides[get_supabase] = lambda: mock_sb
        client = TestClient(app)
        try:
            with patch("app.services.ai_rag_service.settings.openai_api_key", "sk-test"), _mock_httpx_openai("답변"):
                resp = client.post("/api/ai/chat", json={"question": "테스트 질문"}, headers=GUEST_HEADER)
            assert resp.status_code == 200
            assert resp.json()["saved"] is True
            assert mock_sb.ai_query.inserted[0][0]["owner_key"] == f"guest:{GUEST_ID}"
        finally:
            app.dependency_overrides.clear()

    def test_missing_guest_header_is_not_saved(self):
        """표식 없음 → 저장 없음(guest:shared 공용 폴백 금지)."""
        mock_sb = _make_ai_client()
        app.dependency_overrides[get_supabase] = lambda: mock_sb
        client = TestClient(app)
        try:
            with patch("app.services.ai_rag_service.settings.openai_api_key", "sk-test"), _mock_httpx_openai("답변"):
                resp = client.post("/api/ai/chat", json={"question": "테스트 질문"})
            assert resp.json()["saved"] is False
            assert mock_sb.ai_query.inserted == []
        finally:
            app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 5. Summary API 테스트
# ---------------------------------------------------------------------------
class TestSummaryApi:
    """POST /api/ai/summary 테스트."""

    def test_summary_generation(self, ai_client: TestClient, auth_header: dict):
        """요약 API가 요약을 반환해야 합니다."""
        mock_summary_result = {
            "summary_text": "회의에서 교육 예산 증액을 논의했습니다.",
            "key_points": ["교육 예산 증액"],
            "agenda_items": ["예산 심의"],
        }

        with patch(
            "app.services.summary_service.generate_meeting_summary",
            new_callable=AsyncMock,
        ) as mock_gen:
            from app.services.summary_service import MeetingSummary
            mock_gen.return_value = MeetingSummary(
                summary_text="회의에서 교육 예산 증액을 논의했습니다.",
                key_decisions=["교육 예산 증액"],
                agenda_summaries=[{"title": "예산 심의"}],
            )

            resp = ai_client.post(
                "/api/ai/summary",
                json={"meeting_id": MEETING_ID},
                headers=auth_header,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert "summary_text" in data
        assert "교육 예산" in data["summary_text"]

    def test_summary_requires_login_or_council(self, ai_client: TestClient):
        resp = ai_client.post("/api/ai/summary", json={"meeting_id": MEETING_ID})
        assert resp.status_code == 401

    def test_summary_no_subtitles(self, ai_client: TestClient, auth_header: dict):
        """자막이 없는 회의의 요약 요청도 에러 없이 처리되어야 합니다."""
        with patch(
            "app.services.summary_service.generate_meeting_summary",
            new_callable=AsyncMock,
            side_effect=ValueError("자막이 없습니다."),
        ):
            resp = ai_client.post(
                "/api/ai/summary",
                json={"meeting_id": str(uuid.uuid4())},
                headers=auth_header,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert "자막이 없습니다" in data["summary_text"]


# ---------------------------------------------------------------------------
# 6. Conversations list API (인증 필수)
# ---------------------------------------------------------------------------
class TestConversationsApi:
    """GET /api/ai/conversations 테스트 — 본인 것만."""

    def test_conversations_requires_auth(self, ai_client: TestClient):
        """비로그인·의회망 아님 → 401."""
        resp = ai_client.get("/api/ai/conversations")
        assert resp.status_code == 401

    def test_staff_can_list(self):
        """staff(QR 의원)도 AI 이력을 본다 — 예전엔 4역할만이라 의원이 막혔다."""
        from tests.conftest import TEST_ADMIN_USER_ID as UID

        token = create_access_token({"sub": UID, "role": "staff"})
        rows = [
            _conv_row("s1", "user", "첫 질문", f"user:{UID}", "2026-09-14T01:00:00+09:00", MEETING_ID),
            _conv_row("s1", "assistant", "답", f"user:{UID}", "2026-09-14T01:00:05+09:00", MEETING_ID),
            _conv_row("s1", "user", "둘째 질문", f"user:{UID}", "2026-09-14T01:01:00+09:00", MEETING_ID),
        ]
        mock_sb = _make_ai_client(conversations=list(reversed(rows)))  # 서버는 최신순으로 받는다
        app.dependency_overrides[get_supabase] = lambda: mock_sb
        client = TestClient(app)
        try:
            resp = client.get("/api/ai/conversations", headers={"Authorization": f"Bearer {token}"})
            assert resp.status_code == 200
            data = resp.json()
            assert len(data) == 1
            assert data[0]["first_question"] == "첫 질문"
            assert data[0]["message_count"] == 3
            assert data[0]["last_active_at"] == "2026-09-14T01:01:00+09:00"
            assert data[0]["meeting_title"] == MOCK_MEETING["title"]
        finally:
            app.dependency_overrides.clear()

    def test_conversations_returns_list(self, auth_header: dict):
        mock_sb = _make_ai_client(conversations=[])
        app.dependency_overrides[get_supabase] = lambda: mock_sb
        client = TestClient(app)
        resp = client.get("/api/ai/conversations", headers=auth_header)
        assert resp.status_code == 200
        assert resp.json() == []
        app.dependency_overrides.clear()

    def test_shared_endpoint_is_gone(self, ai_client: TestClient):
        """전체 공개 이력(/conversations/shared)은 없앴다 — 이 경로는 세션 ID 로 해석돼 401/404 여야지 목록이 나오면 안 된다."""
        resp = ai_client.get("/api/ai/conversations/shared")
        assert resp.status_code in (401, 404)

    def test_get_conversation_other_owner_is_404(self, auth_header: dict):
        rows = [_conv_row("s9", "user", "남의 질문", "guest:other", "2026-09-14T01:00:00+09:00")]
        mock_sb = _make_ai_client(conversations=rows)
        app.dependency_overrides[get_supabase] = lambda: mock_sb
        client = TestClient(app)
        try:
            resp = client.get("/api/ai/conversations/s9", headers=auth_header)
            assert resp.status_code == 404
        finally:
            app.dependency_overrides.clear()

    def test_get_conversation_own(self):
        rows = [
            _conv_row("s2", "user", "q", f"guest:{GUEST_ID}", "2026-09-14T01:00:00+09:00"),
            _conv_row("s2", "assistant", "a", f"guest:{GUEST_ID}", "2026-09-14T01:00:03+09:00"),
        ]
        mock_sb = _make_ai_client(conversations=rows)
        app.dependency_overrides[get_supabase] = lambda: mock_sb
        client = TestClient(app)
        try:
            with patch("app.core.auth_middleware.is_council", return_value=True):
                resp = client.get("/api/ai/conversations/s2", headers=GUEST_HEADER)
            assert resp.status_code == 200
            assert [r["role"] for r in resp.json()] == ["user", "assistant"]
        finally:
            app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 2026-09-15 — 답을 글자 조각으로 흘려보내기(/api/ai/chat/stream) · 대화 전용 모델 설정
# ---------------------------------------------------------------------------
def _sse_lines(pieces: list[str], finish: str = "stop", usage: dict | None = None) -> list[str]:
    import json as _json

    lines = []
    for p in pieces:
        lines.append("data: " + _json.dumps({"model": "gpt-5.4-mini-x", "choices": [{"delta": {"content": p}, "finish_reason": None}]}))
    lines.append("data: " + _json.dumps({"model": "gpt-5.4-mini-x", "choices": [{"delta": {}, "finish_reason": finish}]}))
    lines.append("data: " + _json.dumps({"choices": [], "usage": usage or {"prompt_tokens": 10, "completion_tokens": 3}}))
    lines.append("data: [DONE]")
    return lines


def _mock_httpx_stream(lines: list[str], status: int = 200):
    """httpx.AsyncClient().stream(...) 를 흉내 — status 와 aiter_lines 를 준다. 보낸 본문은 captured["json"]."""
    captured: dict = {}

    class _Resp:
        status_code = status

        async def aread(self):
            return b"upstream error"

        async def aiter_lines(self):
            for line in lines:
                yield line

    class _StreamCtx:
        async def __aenter__(self):
            return _Resp()

        async def __aexit__(self, *a):
            return False

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def stream(self, method, url, headers=None, json=None):
            captured["json"] = json
            return _StreamCtx()

    return patch("app.services.ai_rag_service.httpx.AsyncClient", return_value=_Client()), captured


CTX = [{"source_type": "context_block", "text": "회의 자막 발췌", "sources": [], "stats": {}}]


class TestStreamAnswer:
    @pytest.mark.asyncio
    async def test_yields_start_deltas_done_with_cleaned_answer(self):
        from app.services.ai_rag_service import stream_answer

        p, captured = _mock_httpx_stream(_sse_lines(["**예산**", "은 ", "가결"]))
        with patch("app.services.ai_rag_service.settings.openai_api_key", "sk-test"), p:
            events = [e async for e in stream_answer("질문", CTX)]
        kinds = [k for k, _ in events]
        assert kinds[0] == "start" and kinds[-1] == "done"
        assert "".join(v for k, v in events if k == "delta") == "**예산**은 가결"
        assert events[-1][1]["answer"] == "예산은 가결"  # 마크다운 제거는 끝에서 한 번
        assert captured["json"]["stream"] is True
        assert captured["json"]["stream_options"] == {"include_usage": True}

    @pytest.mark.asyncio
    async def test_start_failure_raises_before_start(self):
        from app.services.ai_rag_service import AiUpstreamError, stream_answer

        p, _ = _mock_httpx_stream([], status=500)
        with patch("app.services.ai_rag_service.settings.openai_api_key", "sk-test"), p:
            gen = stream_answer("질문", CTX)
            with pytest.raises(AiUpstreamError):
                await gen.__anext__()

    @pytest.mark.asyncio
    async def test_truncated_empty_answer_is_error(self):
        """생각 토큰이 상한을 먹어 본문 없이 length 로 끝나면 빈 답을 정상처럼 내보내지 않는다."""
        from app.services.ai_rag_service import AiUpstreamError, stream_answer

        p, _ = _mock_httpx_stream(_sse_lines([], finish="length"))
        with patch("app.services.ai_rag_service.settings.openai_api_key", "sk-test"), p:
            with pytest.raises(AiUpstreamError, match="길이 상한"):
                [e async for e in stream_answer("질문", CTX)]

    @pytest.mark.asyncio
    async def test_stream_without_finish_signal_is_error(self):
        """상류가 조각 몇 개만 보내고 완료 신호 없이 끊기면 반쪽 답을 done 으로 내지 않는다."""
        import json as _json

        from app.services.ai_rag_service import AiUpstreamError, stream_answer

        cut = ["data: " + _json.dumps({"choices": [{"delta": {"content": "반쪽"}, "finish_reason": None}]})]
        p, _ = _mock_httpx_stream(cut)
        with patch("app.services.ai_rag_service.settings.openai_api_key", "sk-test"), p:
            events = []
            with pytest.raises(AiUpstreamError, match="끊겼"):
                async for e in stream_answer("질문", CTX):
                    events.append(e)
        assert ("delta", "반쪽") in events and not any(k == "done" for k, _ in events)

    @pytest.mark.asyncio
    async def test_no_context_costs_nothing(self):
        from app.services.ai_rag_service import NO_CONTEXT_ANSWER, stream_answer

        with patch("app.services.ai_rag_service.settings.openai_api_key", ""):
            events = [e async for e in stream_answer("질문", [])]
        assert events[-1] == ("done", {"answer": NO_CONTEXT_ANSWER, "sources": []})


class TestChatBody:
    def test_uses_chat_model_not_shared_model(self):
        from app.services.ai_rag_service import _chat_body

        with patch("app.services.ai_rag_service.settings.ai_chat_model", "chat-m"), patch(
            "app.services.ai_rag_service.settings.openai_model", "shared-m"
        ), patch("app.services.ai_rag_service.settings.ai_chat_reasoning_effort", ""):
            body = _chat_body([{"role": "user", "content": "q"}], stream=False)
        assert body["model"] == "chat-m"
        assert "reasoning_effort" not in body  # 빈 값이면 보내지 않는다
        assert "stream" not in body

    def test_reasoning_effort_sent_when_set(self):
        from app.services.ai_rag_service import _chat_body

        with patch("app.services.ai_rag_service.settings.ai_chat_reasoning_effort", "low"):
            body = _chat_body([], stream=True)
        assert body["reasoning_effort"] == "low"


async def _fake_stream(*pieces: str, fail_at_start: bool = False, fail_mid: bool = False):
    from app.services.ai_rag_service import AiUpstreamError

    if fail_at_start:
        raise AiUpstreamError("AI 응답 생성에 실패했습니다.")
    yield ("start", None)
    for p in pieces:
        yield ("delta", p)
    if fail_mid:
        raise AiUpstreamError("AI 응답이 중간에 끊겼습니다. 다시 시도해 주세요.")
    yield ("done", {"answer": "".join(pieces), "sources": []})


class TestChatStreamApi:
    def _post(self, mock_sb, gen):
        app.dependency_overrides[get_supabase] = lambda: mock_sb
        client = TestClient(app)
        try:
            with patch("app.api.ai.stream_agent", return_value=gen), patch(
                "app.api.ai.search_context", AsyncMock(return_value=CTX)
            ):
                return client.post("/api/ai/chat/stream", json={"question": "q"}, headers=GUEST_HEADER)
        finally:
            app.dependency_overrides.clear()

    def test_event_order_and_history_saved_after_done(self):
        mock_sb = _make_ai_client()
        resp = self._post(mock_sb, _fake_stream("안녕", "하세요"))
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        body = resp.text
        assert body.index("event: delta") < body.index("event: done")
        assert '"saved": true' in body
        rows = mock_sb.ai_query.inserted[0]
        assert [r["role"] for r in rows] == ["user", "assistant"]
        assert rows[1]["content"] == "안녕하세요"

    def test_upstream_failure_before_start_is_502(self):
        resp = self._post(_make_ai_client(), _fake_stream(fail_at_start=True))
        assert resp.status_code == 502

    def test_mid_stream_failure_sends_error_and_saves_nothing(self):
        mock_sb = _make_ai_client()
        resp = self._post(mock_sb, _fake_stream("반쪽", fail_mid=True))
        assert resp.status_code == 200
        assert "event: error" in resp.text and "event: done" not in resp.text
        assert mock_sb.ai_query.inserted == []

    def test_rate_limit_is_plain_429_before_stream(self):
        from app.api import ai as ai_mod

        with patch.object(ai_mod.settings, "ai_chat_daily_limit", 0):
            resp = self._post(_make_ai_client(), _fake_stream("x"))
        assert resp.status_code == 429


class TestHistoryHygiene:
    """2026-09-15 "대화할수록 이상하다" — 근거 없는 이전 답이 다시 들어가 오답이 굳던 것."""

    def test_prior_answers_are_trimmed_marked_and_not_found_dropped(self):
        from app.services.ai_rag_service import RAG_SYSTEM_PROMPT, _build_messages

        history = [
            {"role": "user", "content": "이자형 의원 발언에 모바일 공무원증 있어?"},
            {"role": "assistant", "content": "확인되지 않습니다. 관련 자료를 찾지 못했습니다."},
            {"role": "user", "content": "q2"},
            {"role": "assistant", "content": "가" * 1000},
        ]
        msgs = _build_messages("그 발언 다시", "컨텍스트", history)
        assert msgs[0]["content"] == RAG_SYSTEM_PROMPT and "[검색 안내]" in RAG_SYSTEM_PROMPT
        assert "이어받아" not in RAG_SYSTEM_PROMPT
        assistants = [m["content"] for m in msgs if m["role"] == "assistant"]
        assert len(assistants) == 1                       # "찾지 못했습니다" 답은 뺐다
        assert assistants[0].startswith("[이전 답변 일부 — 근거 자막 없음]") and len(assistants[0]) < 340
        assert [m["content"] for m in msgs if m["role"] == "user"][:2] == ["이자형 의원 발언에 모바일 공무원증 있어?", "q2"]


class TestRosterCache:
    def test_roster_loaded_once_per_committee(self):
        from app.services import ai_rag_service as svc

        svc._roster_cache.clear()
        with patch("app.services.roster_loader.load_committee_with_roles", return_value=[{"name": "이자형"}]) as load:
            assert svc._roster_names(MagicMock(), "의회운영위원회") == ["이자형"]
            assert svc._roster_names(MagicMock(), "의회운영위원회") == ["이자형"]
            assert svc._roster_names(MagicMock(), None) == []
        assert load.call_count == 1
        svc._roster_cache.clear()


class TestVectorSearchWiring:
    """2026-09-15 뜻으로 찾기 — 켜져 있으면 벡터 조각을 합치고, 실패하면 키워드 검색만으로 계속한다."""

    @pytest.mark.asyncio
    async def test_vector_failure_falls_back_to_keywords(self):
        from app.services import ai_rag_service as svc

        with patch.object(svc.settings, "rag_vector_enabled", True), patch.object(svc.settings, "openai_api_key", "k"), \
                patch("app.services.subtitle_embeddings.search", side_effect=RuntimeError("PGRST202 no function")):
            results = await svc.search_context(_make_ai_client(), "예산", MEETING_ID)
        block = next(r for r in results if r["source_type"] == "context_block")
        assert block["stats"]["vector"] == "error" and "예산" in block["text"]

    @pytest.mark.asyncio
    async def test_vector_hits_are_passed_to_context(self):
        from app.services import ai_rag_service as svc

        hits = [{"seq": 0, "start_time": 0, "end_time": 99999, "speakers": [], "agenda_num": None, "similarity": 0.55}]
        with patch.object(svc.settings, "rag_vector_enabled", True), patch.object(svc.settings, "openai_api_key", "k"), \
                patch("app.services.subtitle_embeddings.search", return_value=hits) as search:
            results = await svc.search_context(_make_ai_client(), "예산", MEETING_ID)
        block = next(r for r in results if r["source_type"] == "context_block")
        assert block["stats"]["vector"] == "ok" and block["stats"]["semantic_rows"] > 0
        assert search.call_args.args[1] == MEETING_ID

    @pytest.mark.asyncio
    async def test_vector_off_by_default(self):
        from app.services import ai_rag_service as svc

        with patch("app.services.subtitle_embeddings.search") as search:
            results = await svc.search_context(_make_ai_client(), "예산", MEETING_ID)
        assert not search.called
        assert next(r for r in results if r["source_type"] == "context_block")["stats"]["vector"] == "off"


class TestAgentEvents:
    def test_status_and_reset_pass_through(self):
        async def gen():
            yield ("start", None)
            yield ("status", "자막 검색 중… '보안'")
            yield ("delta", "반쪽")
            yield ("reset", None)
            yield ("delta", "전자영 위원")
            yield ("done", {"answer": "전자영 위원", "sources": []})

        mock_sb = _make_ai_client()
        app.dependency_overrides[get_supabase] = lambda: mock_sb
        client = TestClient(app)
        try:
            with patch("app.api.ai.stream_agent", return_value=gen()), patch("app.api.ai.search_context", AsyncMock(return_value=CTX)):
                resp = client.post("/api/ai/chat/stream", json={"question": "q"}, headers=GUEST_HEADER)
        finally:
            app.dependency_overrides.clear()
        body = resp.text
        assert body.index("event: status") < body.index("event: reset") < body.index("event: done")
        assert mock_sb.ai_query.inserted[0][1]["content"] == "전자영 위원"
