"""직접 PostgreSQL 연결 인프라.

이 모듈은 Supabase REST를 대체하기 위한 SQLAlchemy/psycopg engine factory입니다.
engine 생성은 네트워크 연결을 열지 않으며, request 또는 background 작업이 session을
실제로 사용할 때만 연결합니다.
"""

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings


_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def is_postgres_backend() -> bool:
    """직접 PostgreSQL 경로가 명시적으로 선택됐는지 반환합니다."""
    return settings.db_backend == "postgres"


def create_postgres_engine(database_url: str) -> Engine:
    """psycopg 3 드라이버 기반의 보수적 PostgreSQL engine을 생성합니다."""
    return create_engine(
        database_url,
        pool_pre_ping=True,
        pool_size=3,
        max_overflow=2,
        pool_recycle=1800,
    )


def create_postgres_session_factory(engine: Engine) -> sessionmaker[Session]:
    """request/background 작업마다 독립 session을 생성하는 factory를 반환합니다."""
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_postgres_session_factory() -> sessionmaker[Session]:
    """설정된 DATABASE_URL의 lazy session factory를 반환합니다.

    engine 생성만으로는 네트워크 연결을 열지 않습니다.
    """
    global _engine, _session_factory
    if _session_factory is None:
        _engine = create_postgres_engine(settings.database_url)
        _session_factory = create_postgres_session_factory(_engine)
    return _session_factory


def get_postgres_session():
    """FastAPI dependency용 request-scoped PostgreSQL session."""
    session = get_postgres_session_factory()()
    try:
        yield session
    finally:
        session.close()
