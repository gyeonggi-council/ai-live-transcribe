"""방송상태 제공자 레지스트리."""

from __future__ import annotations

from app.core.config import settings

from .base import (
    LIVESTATUS_BEFORE,
    LIVESTATUS_BROADCASTING,
    LIVESTATUS_ENDED,
    LIVESTATUS_NONE,
    LIVESTATUS_RECESS,
    ChannelStatusProvider,
)
from .ggc import GgcOnairProvider
from .manual import ManualProvider
from .probe import StreamProbeProvider

_INSTANCES: dict[str, ChannelStatusProvider] = {}
_FACTORIES = {
    "ggc": GgcOnairProvider,
    "probe": StreamProbeProvider,
    "manual": ManualProvider,
    "schedule": ManualProvider,   # 일정 기반은 수동과 같은 자리(관리자가 채운다)
}


def get_provider(name: str) -> ChannelStatusProvider | None:
    """제공자 인스턴스(싱글턴). 'none' 이거나 모르는 이름이면 None."""
    key = (name or "").strip() or settings.default_status_provider
    if key == "none":
        return None
    factory = _FACTORIES.get(key)
    if factory is None:
        return None
    if key not in _INSTANCES:
        _INSTANCES[key] = factory()
    return _INSTANCES[key]


def group_by_provider(channels: list[dict]) -> dict[str, list[dict]]:
    """채널을 status_provider 별로 묶는다. 값이 비면 기본 제공자로."""
    groups: dict[str, list[dict]] = {}
    for ch in channels:
        key = (ch.get("status_provider") or "").strip() or settings.default_status_provider
        groups.setdefault(key, []).append(ch)
    return groups


def reset_providers() -> None:
    """테스트 정리용."""
    _INSTANCES.clear()


__all__ = [
    "ChannelStatusProvider",
    "GgcOnairProvider",
    "ManualProvider",
    "StreamProbeProvider",
    "LIVESTATUS_BEFORE",
    "LIVESTATUS_BROADCASTING",
    "LIVESTATUS_RECESS",
    "LIVESTATUS_ENDED",
    "LIVESTATUS_NONE",
    "get_provider",
    "group_by_provider",
    "reset_providers",
]
