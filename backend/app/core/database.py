"""데이터베이스 및 Supabase 클라이언트 설정

SQLAlchemy/asyncpg 대신 Supabase REST 클라이언트를 사용합니다.
(Windows 한글 사용자명 환경에서 asyncpg SSL 인증서 로딩 오류 방지)
"""

from sqlalchemy.orm import declarative_base
from supabase import Client, ClientOptions, create_client

from app.core.config import settings

# SQLAlchemy Base (models에서 참조 — 실제 DB 연결은 Supabase REST 사용)
Base = declarative_base()

# Supabase Client (싱글톤)
_supabase_client: Client | None = None


def get_supabase_client() -> Client:
    """Supabase 클라이언트 인스턴스를 반환합니다.

    Returns:
        Client: Supabase 클라이언트

    Raises:
        ValueError: Supabase URL 또는 KEY가 설정되지 않은 경우
    """
    global _supabase_client

    if _supabase_client is None:
        if not settings.supabase_url or not settings.supabase_key:
            raise ValueError(
                "SUPABASE_URL과 SUPABASE_KEY 환경변수가 설정되어야 합니다."
            )
        # 스키마를 명시해야 한다 — supabase-py 가 Accept-Profile 헤더를 항상 보내므로,
        # k3s pgrst 브리지(SUPABASE_SCHEMA=subtitle)에서 기본값 public 이 그대로 나가면
        # 전 쿼리가 PGRST106 으로 거부된다 (2026-08-20 운영 장애 실측).
        _supabase_client = create_client(
            settings.supabase_url,
            settings.supabase_key,
            options=ClientOptions(schema=settings.supabase_schema),
        )

    return _supabase_client


def get_supabase() -> Client:
    """FastAPI Dependency용 Supabase 클라이언트 제공자."""
    return get_supabase_client()


# Alias for backward compatibility (used in tests/conftest.py)
get_db = get_supabase


async def test_supabase_connection() -> bool:
    """Supabase 연결을 테스트합니다.

    Returns:
        bool: 연결 성공 여부
    """
    try:
        client = get_supabase_client()
        client.table("meetings").select("id").limit(1).execute()
        return True
    except Exception as e:
        print(f"Supabase 연결 실패: {e}")
        return False
