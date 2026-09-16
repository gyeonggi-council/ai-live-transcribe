"""라이브 배치 STT — 자막 준비 지연 계측 (영상 지연 목표의 근거).

프런트가 영상을 라이브 엣지에서 몇 초 뒤로 잡아야 자막이 항상 먼저 준비되는지는
"창의 첫 발화 → 자막 방출" 까지의 오디오-초 차이(ready_lag)로 정해진다.
이 값을 창마다 기록하고 p95 를 stt_status 로 내보낸다.
"""

import time
from unittest.mock import MagicMock

import pytest

from app.services import live_batch_stt as lb
from app.services.live_batch_stt import LiveBatchSttService


@pytest.fixture
def svc() -> LiveBatchSttService:
    return LiveBatchSttService()


def _running(svc: LiveBatchSttService, ch: str) -> None:
    task = MagicMock()
    task.done.return_value = False
    svc._active_tasks = {ch: task}


def test_record_window_metrics_and_p95(svc):
    """창마다 API 왕복·준비 지연을 기록하고 p95 를 상태 방송에 싣는다."""
    ch = "ch14"
    _running(svc, ch)
    # 준비 지연 = 방출 시점 오디오 시계 − 창 시작. 시계 100.0, 창 시작 85.0 → 15.0
    svc._audio_sec[ch] = 100.0
    svc._record_window_metrics(ch, start_sec=85.0, api_sec=2.5)
    assert svc._ready_lags[ch][-1] == 15.0
    assert svc._api_secs[ch][-1] == 2.5

    for lag in [12.0, 13.0, 14.0, 16.0, 17.0, 18.0, 19.0, 20.0, 30.0]:
        svc._audio_sec[ch] = 100.0 + lag
        svc._record_window_metrics(ch, start_sec=100.0, api_sec=3.0)

    p = svc._build_status_payload(ch)
    assert p["api_sec_last"] == 3.0
    assert p["ready_lag_last"] == 30.0
    # 표본 10개 [12..20, 30] 의 p95 는 상위 5% 경계 — 20 이상 30 이하
    assert 20.0 <= p["ready_lag_p95"] <= 30.0
    assert p["hls_window_sec"] is None  # 파서 없음


def test_metrics_keep_bounded_history(svc):
    ch = "ch1"
    for i in range(150):
        svc._audio_sec[ch] = float(i)
        svc._record_window_metrics(ch, start_sec=0.0, api_sec=1.0)
    assert len(svc._ready_lags[ch]) == 100
    assert len(svc._api_secs[ch]) == 100


def test_status_payload_metrics_none_without_samples(svc):
    ch = "ch3"
    p = svc._build_status_payload(ch)
    assert p["api_sec_last"] is None
    assert p["ready_lag_last"] is None
    assert p["ready_lag_p95"] is None
    assert p["hls_window_sec"] is None


def test_status_payload_exposes_hls_window(svc):
    ch = "ch3"
    parser = MagicMock()
    parser.window_seconds = 15.9
    svc._parsers[ch] = parser
    p = svc._build_status_payload(ch)
    assert p["hls_window_sec"] == 15.9


def test_percentile_helper():
    from app.services.live_batch_stt import _percentile

    assert _percentile([], 95) is None
    assert _percentile([5.0], 95) == 5.0
    assert _percentile([1.0, 2.0, 3.0, 4.0], 50) == 2.0
    assert _percentile([1.0, 2.0, 3.0, 4.0], 100) == 4.0


# ─── 수집 지연(edge_lag)·동기 요구(sync_need)·영상 지연 목표 (2026-09-14) ──────────


def test_edge_lag_and_sync_need_recorded(svc):
    """edge_lag = (fed − audio) + (지금 − edge_wall), sync_need = ready_lag + edge_lag 가 창마다 기록되고 상태 방송에 실린다."""
    ch = "ch14"
    _running(svc, ch)
    svc._fed_clock[ch] = 102.0
    svc._audio_sec[ch] = 101.5
    svc._edge_wall[ch] = time.monotonic() - 0.8
    svc._record_window_metrics(ch, start_sec=90.0, api_sec=1.0)  # ready_lag = 11.5
    edge = svc._edge_lags[ch][-1]
    assert 1.2 <= edge <= 1.6  # 0.5 + 0.8(+약간)
    assert svc._sync_needs[ch][-1] == pytest.approx(11.5 + edge, abs=0.11)
    p = svc._build_status_payload(ch)
    assert p["edge_lag_last"] == edge and p["edge_lag_p95"] == edge
    assert p["sync_need_p95"] == svc._sync_needs[ch][-1] == p["sync_need_max"]
    assert p["samples"] == 1


def test_edge_lag_none_before_first_segment(svc):
    """세그먼트를 본 적 없으면 edge_lag 는 None 이고 sync_need 도 기록하지 않는다(ready_lag 만)."""
    ch = "ch3"
    svc._audio_sec[ch] = 5.0
    assert svc._edge_lag_now(ch) is None
    svc._record_window_metrics(ch, start_sec=0.0, api_sec=1.0)
    assert ch not in svc._edge_lags and ch not in svc._sync_needs
    p = svc._build_status_payload(ch)
    assert p["edge_lag_last"] is None and p["sync_need_p95"] is None and p["samples"] == 1


def test_status_payload_carries_sync_target_and_window(svc, monkeypatch):
    """영상 지연 목표(env)와 창 길이가 상태 방송·sync_info 에 실린다 — 프런트가 재빌드 없이 받는다."""
    monkeypatch.setattr(lb.settings, "live_sync_target_sec", 17)
    monkeypatch.setattr(lb.settings, "live_batch_window_seconds", 8.0)
    p = svc._build_status_payload("ch1")
    assert p["sync_target_sec"] == 17 and p["window_seconds"] == 8.0
    info = svc.get_sync_info("ch1")
    assert info["sync_target_sec"] == 17 and info["window_seconds"] == 8.0
    assert info["samples"] == 0 and info["sync_target_recommended"] is None


def test_sync_target_clamped_to_8_60(monkeypatch):
    monkeypatch.setattr(lb.settings, "live_sync_target_sec", 3)
    assert lb.live_sync_target_sec() == 8
    monkeypatch.setattr(lb.settings, "live_sync_target_sec", 99)
    assert lb.live_sync_target_sec() == 60
    monkeypatch.setattr(lb.settings, "live_sync_target_sec", "18")
    assert lb.live_sync_target_sec() == 18


def test_sync_target_recommended_needs_20_samples_and_clamps(svc):
    """진단값 = ceil(최근 100창 sync_need 최댓값 + 1), 표본 20 미만이면 None, 8~60 클램프."""
    ch = "ch5"
    _running(svc, ch)
    svc._edge_wall[ch] = time.monotonic() - 1.0
    for i in range(19):
        svc._audio_sec[ch] = svc._fed_clock[ch] = 100.0 + i
        svc._record_window_metrics(ch, start_sec=90.0 + i, api_sec=1.0)  # ready_lag 10 → sync_need ≈ 11
    assert svc.get_sync_info(ch)["sync_target_recommended"] is None
    svc._audio_sec[ch] = svc._fed_clock[ch] = 200.0
    svc._record_window_metrics(ch, start_sec=190.0, api_sec=1.0)
    assert svc.get_sync_info(ch)["sync_target_recommended"] in (12, 13)
    # 한 창이 크게 늦으면 최댓값이 끌어올린다(60 상한)
    svc._record_window_metrics(ch, start_sec=100.0, api_sec=1.0)  # ready_lag 100
    assert svc.get_sync_info(ch)["sync_target_recommended"] == 60
