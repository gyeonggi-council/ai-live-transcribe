"""인증 서비스 - 비밀번호 해싱 및 JWT 토큰 관리

# @TASK P11A-R1-T3 - 인증 서비스
# @SPEC docs/planning/02-trd.md#인증-API
"""

import logging
from datetime import datetime, timedelta, timezone

import bcrypt
from jose import JWTError, jwt

from app.core.config import settings

logger = logging.getLogger(__name__)


def hash_password(password: str) -> str:
    """비밀번호를 bcrypt로 해싱합니다.

    Args:
        password: 원본 비밀번호

    Returns:
        bcrypt 해시 문자열
    """
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """비밀번호를 검증합니다.

    Args:
        plain_password: 원본 비밀번호
        hashed_password: bcrypt 해시

    Returns:
        일치 여부
    """
    return bcrypt.checkpw(
        plain_password.encode("utf-8"),
        hashed_password.encode("utf-8"),
    )


def create_access_token(
    data: dict,
    expires_minutes: int | None = None,
) -> str:
    """JWT 액세스 토큰을 생성합니다.

    Args:
        data: 토큰에 포함할 데이터 (sub, role 등)
        expires_minutes: 만료 시간(분). None이면 설정값 사용.

    Returns:
        JWT 토큰 문자열
    """
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=expires_minutes or settings.jwt_expire_minutes
    )
    to_encode["exp"] = expire
    return jwt.encode(
        to_encode,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )


def verify_token(token: str) -> dict | None:
    """JWT 토큰을 검증하고 페이로드를 반환합니다.

    Args:
        token: JWT 토큰 문자열

    Returns:
        검증 성공 시 페이로드 dict, 실패 시 None
    """
    if not token:
        return None
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        return payload
    except JWTError:
        logger.debug("JWT verification failed")
        return None
