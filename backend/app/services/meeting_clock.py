"""회의 시각 기준점 — 자막 시계(초) ↔ 실제 시각(벽시계).

**왜 기준점이 필요한가.** 자막 `start_time` 은 회의 시작으로부터의 경과가 아니라
**수신된 오디오 초**다. 정회로 방송이 끊기면 자막 시계도 녹음도 그 구간을 통째로
건너뛴다(live_recorder 주석과 같은 시계). 그래서 "회의 시작 시각 + start_time" 으로
실제 시각을 만들면 정회 한 번에 그 길이만큼 틀어진다.

그래서 라이브 STT 가 **세션 시작·정회 재개마다** (그 순간의 자막 시계, 그 순간의 실제
시각) 한 쌍을 남기고(migration 037), 읽을 때는 **구간별 선형 매핑**으로 되돌린다:

    실제시각 = 기준점.wall_at + (자막시계 − 기준점.clock_sec)
    (기준점 = clock_sec 이 자막시계 이하인 것 중 마지막)

기준점이 없는 **과거 회의**는 자막의 `created_at`(DB 기록 시각)에서 추정한다. 자막은
말이 끝난 뒤 전사를 거쳐 기록되므로 `created_at` 은 실제 발언보다 항상 늦다 — 그 지연을
`ESTIMATED_EMIT_LAG_SEC` 로 빼고, 정회로 생긴 점프는 구간을 나눠 흡수한다.
추정값은 저장하지 않는다(응답에서 `source="estimated"` 로만 알린다).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Optional

logger = logging.getLogger(__name__)

# 자막이 DB 에 기록되기까지의 지연(초) — 추정 기준점에서 뺀다.
# 근거: 2026-09-03 본회의 실측 자막 준비 지연 p50 10.7 · p95 13.8 (HlsPlayer 주석과 같은 출처).
# 이 값이 곧 추정 기준점의 남은 오차다(±10초 내외) — 그래서 응답에 estimated 를 실어
# 화면이 "약 10:04" 처럼 근사임을 드러낼 수 있게 한다.
ESTIMATED_EMIT_LAG_SEC = 11.0

# 추정 기준점을 만들 자막 구간 길이(초). 짧을수록 정회 점프를 촘촘히 따라가지만 응답이 커진다.
ESTIMATE_BUCKET_SEC = 120.0

# 추정에 쓸 자막 최대 건수 (2시간 회의 ≈ 1,000건)
ESTIMATE_MAX_ROWS = 5000

# 추정 기준점 최대 개수 — 비정상적으로 긴 회의에서도 응답 크기를 묶는다
ESTIMATE_MAX_ANCHORS = 400

# 직전 기준점의 선형 연장과 이만큼도 어긋나지 않으면 새 기준점을 만들지 않는다(응답 다이어트)
ESTIMATE_MIN_DRIFT_SEC = 3.0

# 저장된 기준점이 이보다 늦게 시작하면 그 앞 구간은 덮이지 않은 것으로 본다.
# 기준점은 세션 첫 PCM 에서 남으므로 정상 회의는 0 근처에서 시작한다. 늦게 시작하는 경우는
# **회의 도중에 이 기능이 배포된 회의**뿐인데, 그때 앞 구간을 첫 기준점에서 거꾸로 늘리면
# 그 사이의 정회(점심 등)를 건너뛰어 오전 장면이 통째로 틀린다 — 앞 구간은 추정으로 채운다.
ANCHOR_COVERAGE_START_SEC = 120.0


def _parse_ts(value: object) -> Optional[datetime]:
    """PostgREST 타임스탬프 문자열 → tz-aware datetime. 못 읽으면 None."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not value:
        return None
    try:
        ts = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def record_anchor(supabase, meeting_id: str, clock_sec: float, wall_at: datetime) -> bool:
    """기준점 한 줄을 남긴다. 실패는 삼킨다 — 시각 표시가 STT 를 멈추게 하지 않는다."""
    try:
        (
            supabase.table("meeting_clock_anchors")
            .insert(
                {
                    "meeting_id": meeting_id,
                    "clock_sec": round(float(clock_sec), 2),
                    "wall_at": wall_at.astimezone(timezone.utc).isoformat(),
                    "source": "live",
                }
            )
            .execute()
        )
        return True
    except Exception as e:  # 표 미적용·권한·네트워크 — 어느 쪽이든 녹화/STT 는 계속된다
        logger.warning(
            "clock anchor 기록 실패 (meeting=%s, clock=%.1f): %s", meeting_id, clock_sec, e
        )
        return False


def get_recorded_anchors(supabase, meeting_id: str) -> list[dict]:
    """저장된 기준점 [{clock, wall}] — 자막 시계 오름차순."""
    try:
        res = (
            supabase.table("meeting_clock_anchors")
            .select("clock_sec, wall_at")
            .eq("meeting_id", meeting_id)
            .order("clock_sec")
            .limit(ESTIMATE_MAX_ANCHORS)
            .execute()
        )
    except Exception as e:
        logger.debug("clock anchor 조회 실패 (meeting=%s): %s", meeting_id, e)
        return []

    out: list[dict] = []
    for row in res.data or []:
        ts = _parse_ts(row.get("wall_at"))
        if ts is None:
            continue
        try:
            clock = float(row.get("clock_sec"))
        except (TypeError, ValueError):
            continue
        out.append({"clock": round(clock, 2), "wall": ts.isoformat()})
    out.sort(key=lambda a: a["clock"])
    return out


def estimate_anchors(supabase, meeting_id: str) -> list[dict]:
    """기준점이 없는 회의를 자막 `created_at` 으로 추정한다 (±10초 내외).

    같은 구간의 자막들에서 (기록 시각 − 자막 시계)의 **중앙값**을 잡아 한 명씩 튀는
    값(재시도·백로그 일괄 기록)을 밀어낸다. 정회가 있으면 그 값이 구간 경계에서
    점프하므로, 구간을 나누는 것만으로 정회가 자동으로 흡수된다.
    """
    try:
        res = (
            supabase.table("subtitles")
            .select("start_time, created_at")
            .eq("meeting_id", meeting_id)
            .eq("kind", "live")  # VOD AI 자막의 created_at 은 일괄 생성 시각이라 무의미하다
            .order("start_time")
            .limit(ESTIMATE_MAX_ROWS)
            .execute()
        )
    except Exception as e:
        logger.debug("자막 기준점 추정 조회 실패 (meeting=%s): %s", meeting_id, e)
        return []

    # (자막 시계, 시계 0 에 해당하는 실제 시각 추정치) 쌍으로 접는다
    samples: list[tuple[float, float]] = []
    for row in res.data or []:
        ts = _parse_ts(row.get("created_at"))
        if ts is None:
            continue
        try:
            clock = float(row.get("start_time"))
        except (TypeError, ValueError):
            continue
        samples.append((clock, ts.timestamp() - clock))
    if not samples:
        return []
    samples.sort(key=lambda s: s[0])

    anchors: list[dict] = []
    bucket_clock = samples[0][0]
    bucket: list[float] = []

    def flush(start_clock: float, epochs: list[float]) -> None:
        if not epochs or len(anchors) >= ESTIMATE_MAX_ANCHORS:
            return
        wall_epoch = median(epochs) + start_clock - ESTIMATED_EMIT_LAG_SEC
        if anchors:
            prev = anchors[-1]
            drift = wall_epoch - (prev["_epoch"] + (start_clock - prev["clock"]))
            if abs(drift) < ESTIMATE_MIN_DRIFT_SEC:
                return  # 직전 구간의 연장선과 사실상 같다 — 기준점을 늘리지 않는다
        anchors.append(
            {
                "clock": round(start_clock, 2),
                "wall": datetime.fromtimestamp(wall_epoch, tz=timezone.utc).isoformat(),
                "_epoch": wall_epoch,
            }
        )

    for clock, epoch in samples:
        if clock - bucket_clock >= ESTIMATE_BUCKET_SEC and bucket:
            flush(bucket_clock, bucket)
            bucket_clock, bucket = clock, []
        bucket.append(epoch)
    flush(bucket_clock, bucket)

    for a in anchors:
        a.pop("_epoch", None)
    return anchors


def anchors_for_meeting(supabase, meeting_id: str) -> tuple[list[dict], str]:
    """(기준점 목록, 출처). 출처: recorded(정확) / mixed / estimated(±10초) / none.

    mixed 는 "뒤는 정확하고 앞은 추정" 이다 — 회의 도중에 이 기능이 배포된 회의에서만 난다.
    화면은 recorded 가 아닌 출처에 "약" 을 붙여 근사임을 드러낸다.
    """
    recorded = get_recorded_anchors(supabase, meeting_id)
    if recorded:
        first = float(recorded[0]["clock"])
        if first <= ANCHOR_COVERAGE_START_SEC:
            return recorded, "recorded"
        head = [a for a in estimate_anchors(supabase, meeting_id) if a["clock"] < first]
        return (head + recorded, "mixed") if head else (recorded, "recorded")
    estimated = estimate_anchors(supabase, meeting_id)
    if estimated:
        return estimated, "estimated"
    return [], "none"


def wall_at_clock(anchors: list[dict], clock: float) -> Optional[datetime]:
    """자막 시계 → 실제 시각. 첫 기준점보다 앞이면 그 기준점에서 거꾸로 늘린다."""
    if not anchors:
        return None
    chosen = anchors[0]
    for a in anchors:
        if a["clock"] <= clock:
            chosen = a
        else:
            break
    base = _parse_ts(chosen["wall"])
    if base is None:
        return None
    return base + timedelta(seconds=clock - float(chosen["clock"]))
