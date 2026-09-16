"""채널 상태·STT 상태 응답의 /live 영상 지연 목표(sync_target_sec)와 근거 계측 (2026-09-14).

프런트는 /api/channels/status 로 방송 여부를 판정한 뒤 플레이어를 띄우므로 그 응답에 목표를 실으면
추가 왕복 없이 마운트 전에 값을 안다(재빌드 없이 env 로 조정). stt/status 는 근거 분포를 같이 돌려준다.
"""

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from app.services import live_batch_stt as lb


def test_stt_status_carries_sync_info(client: TestClient):
    with patch("app.api.channels.get_channel_stt_service") as svc:
        svc.return_value.is_running.return_value = True
        svc.return_value.get_sync_info.return_value = {
            "sync_target_sec": 18, "window_seconds": 12.0, "sync_need_p95": 14.2, "samples": 40,
        }
        res = client.get("/api/channels/ch14/stt/status")
    assert res.status_code == 200
    body = res.json()
    assert body["running"] is True and body["channel_id"] == "ch14"
    assert body["sync_target_sec"] == 18 and body["sync_need_p95"] == 14.2 and body["samples"] == 40


def test_stt_status_without_sync_info_method_still_200(client: TestClient):
    """realtime 엔진(get_sync_info 없음)에서도 옛 응답 그대로."""
    svc = MagicMock(spec=["is_running"])
    svc.is_running.return_value = False
    with patch("app.api.channels.get_channel_stt_service", return_value=svc):
        res = client.get("/api/channels/ch14/stt/status")
    assert res.status_code == 200
    assert res.json() == {"running": False, "channel_id": "ch14"}


def test_channels_status_carries_sync_target(client: TestClient, monkeypatch):
    monkeypatch.setattr(lb.settings, "live_sync_target_sec", 17)
    with patch("app.api.channels.get_channel_status_service") as css, \
         patch("app.api.channels.get_channel_stt_service") as svc, \
         patch("app.api.channels.get_auto_stt_manager") as auto:
        css.return_value.get_channels_with_status = AsyncMock(
            return_value=[{"id": "ch1", "code": "ch1", "name": "운영위", "stream_url": "https://s/ch1/playlist.m3u8"}]
        )
        svc.return_value.is_running.return_value = False
        auto.return_value.enabled = False
        res = client.get("/api/channels/status")
    assert res.status_code == 200
    ch = res.json()[0]
    assert ch["sync_target_sec"] == 17 and ch["stt_running"] is False
