"""메인 애플리케이션 테스트"""

import pytest

from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client() -> TestClient:
    """테스트 클라이언트 픽스처"""
    return TestClient(app)


def test_root(client: TestClient) -> None:
    """루트 엔드포인트 테스트"""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "running"


def test_health_check(client: TestClient) -> None:
    """헬스체크 엔드포인트 테스트"""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
