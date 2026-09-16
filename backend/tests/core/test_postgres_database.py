"""직접 PostgreSQL engine 구성 계약 테스트."""


def test_create_postgres_engine_uses_psycopg_and_pre_ping_without_connecting():
    from app.core.postgres import create_postgres_engine

    engine = create_postgres_engine("postgresql+psycopg://user:pass@db.internal:5432/ggc_test")

    assert engine.url.get_backend_name() == "postgresql"
    assert engine.url.get_driver_name() == "psycopg"
    assert engine.pool._pre_ping is True
    engine.dispose()


def test_create_postgres_session_factory_binds_sessions_to_supplied_engine():
    from app.core.postgres import create_postgres_engine, create_postgres_session_factory

    engine = create_postgres_engine("postgresql+psycopg://user:pass@db.internal:5432/ggc_test")
    session_factory = create_postgres_session_factory(engine)
    session = session_factory()

    assert session.get_bind() is engine
    session.close()
    engine.dispose()


def test_get_postgres_session_closes_session_after_request(monkeypatch):
    from app.core import postgres

    closed = []

    class FakeSession:
        def close(self):
            closed.append(True)

    monkeypatch.setattr(postgres, "get_postgres_session_factory", lambda: lambda: FakeSession())

    sessions = postgres.get_postgres_session()
    session = next(sessions)
    assert isinstance(session, FakeSession)
    with __import__("pytest").raises(StopIteration):
        next(sessions)

    assert closed == [True]
