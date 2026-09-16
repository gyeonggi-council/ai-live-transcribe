"""Auth Service 단위 테스트 (TDD RED -> GREEN)

# @TASK P11A-R1-T3 - 인증 서비스 테스트
# @TEST tests/test_auth_service.py
"""

import pytest

from app.services.auth_service import (
    create_access_token,
    hash_password,
    verify_password,
    verify_token,
)


class TestPasswordHashing:
    """비밀번호 해싱/검증 테스트"""

    def test_hash_password_returns_hash(self):
        """hash_password는 원본과 다른 해시 문자열을 반환해야 한다."""
        raw = "test-password-123"
        hashed = hash_password(raw)
        assert hashed != raw
        assert len(hashed) > 20

    def test_verify_password_correct(self):
        """올바른 비밀번호는 True를 반환해야 한다."""
        raw = "my-secret-pw"
        hashed = hash_password(raw)
        assert verify_password(raw, hashed) is True

    def test_verify_password_wrong(self):
        """잘못된 비밀번호는 False를 반환해야 한다."""
        hashed = hash_password("correct-pw")
        assert verify_password("wrong-pw", hashed) is False

    def test_hash_password_unique(self):
        """같은 비밀번호도 매번 다른 해시를 생성해야 한다 (salt)."""
        raw = "same-password"
        h1 = hash_password(raw)
        h2 = hash_password(raw)
        assert h1 != h2
        # 둘 다 검증은 통과해야 한다
        assert verify_password(raw, h1) is True
        assert verify_password(raw, h2) is True


class TestJwtToken:
    """JWT 토큰 생성/검증 테스트"""

    def test_create_and_verify_token(self):
        """생성한 토큰을 검증하면 원본 데이터가 반환되어야 한다."""
        data = {"sub": "user-123", "role": "admin"}
        token = create_access_token(data)
        assert isinstance(token, str)
        assert len(token) > 20

        payload = verify_token(token)
        assert payload is not None
        assert payload["sub"] == "user-123"
        assert payload["role"] == "admin"

    def test_verify_token_has_exp(self):
        """토큰에 exp (만료 시간) 클레임이 있어야 한다."""
        token = create_access_token({"sub": "u1"})
        payload = verify_token(token)
        assert "exp" in payload

    def test_verify_invalid_token_returns_none(self):
        """잘못된 토큰은 None을 반환해야 한다."""
        result = verify_token("this.is.not.a.valid.jwt")
        assert result is None

    def test_verify_empty_token_returns_none(self):
        """빈 토큰은 None을 반환해야 한다."""
        result = verify_token("")
        assert result is None

    def test_token_with_custom_expiry(self):
        """커스텀 만료 시간으로 토큰을 생성할 수 있어야 한다."""
        token = create_access_token({"sub": "u1"}, expires_minutes=1)
        payload = verify_token(token)
        assert payload is not None
        assert payload["sub"] == "u1"
