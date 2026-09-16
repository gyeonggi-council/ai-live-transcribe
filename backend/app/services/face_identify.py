# -*- coding: utf-8 -*-
"""회의 영상 한 장면 → 화면에 잡힌 의원 식별.

경로 두 가지
------------
1. **브라우저가 보낸 그림**(기본) — 보고 있는 `<video>` 를 캔버스로 한 장 떠서 올린다.
   hls.js 는 세그먼트를 XHR 로 받아 MSE 에 넣으므로 캔버스가 오염되지 않는다.
   사용자가 **지금 보는 그 화면**을 그대로 판정한다는 점이 중요하다 — 라이브는 17초쯤
   뒤로 잡아 재생하므로 서버가 방금 받은 장면과는 다른 순간이다.
2. **서버가 직접 뜬 그림**(대비책) — iOS 네이티브 HLS 등 캔버스 캡처가 막힌 환경.
   ffmpeg 으로 재생목록에서 1프레임만 뽑는다.

결과의 좌표는 **0~1 비율**이다. 브라우저가 보낸 그림의 크기와 화면에 그려진 `<video>` 의
크기가 다르므로(해상도·letterbox), 픽셀로 돌려주면 상자가 어긋난다.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import numpy as np

from app.core.channels import get_channel, get_committee_for_channel
from app.core.config import settings
from app.services import face_index

logger = logging.getLogger(__name__)

_FFMPEG_TIMEOUT = 25.0

# 채널별 마지막 서버 캡처 (연타 방지 — 같은 장면을 반복해 디코딩하지 않는다)
_frame_cache: dict[str, tuple[float, bytes]] = {}
_frame_lock = asyncio.Lock()

# 얼굴 추론은 CPU 를 쓴다. 라이브 STT 와 같은 파드이므로 동시 실행을 1건으로 묶는다.
_infer_sem = asyncio.Semaphore(1)


async def grab_frame_from_channel(channel_id: str) -> bytes | None:
    """채널 HLS 에서 최신 프레임 1장을 JPEG 로 뽑는다. 실패 시 None."""
    ch = get_channel(channel_id)
    if not ch:
        return None
    url = ch.get("stream_url")
    if not url:
        return None

    async with _frame_lock:
        hit = _frame_cache.get(channel_id)
        if hit and (time.time() - hit[0]) < settings.face_frame_cache_seconds:
            return hit[1]

    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-user_agent", "Mozilla/5.0",
        "-i", url,
        "-frames:v", "1", "-q:v", "3",
        "-f", "image2", "-vcodec", "mjpeg", "pipe:1",
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        logger.error("ffmpeg 이 없다 — 서버 캡처 불가")
        return None
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=_FFMPEG_TIMEOUT)
    except asyncio.TimeoutError:
        proc.kill()
        logger.warning("프레임 캡처 시간 초과 channel=%s", channel_id)
        return None
    if proc.returncode != 0 or len(out) < 1000:
        logger.warning("프레임 캡처 실패 channel=%s rc=%s %s", channel_id, proc.returncode, err[:200])
        return None
    async with _frame_lock:
        _frame_cache[channel_id] = (time.time(), out)
    return out


def _identify_sync(
    supabase: Any,
    raw: bytes,
    committee: str | None,
    speaker_hint: str | None,
    channel_id: str | None,
    allow_ids: set[str] | None = None,
) -> dict[str, Any]:
    """무거운 부분(디코드·검출·임베딩·매칭). 호출부가 스레드로 던진다."""
    import cv2

    det, emb = face_index.load_models()
    img = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return {"faces": [], "error": "이미지를 읽지 못했습니다."}
    h, w = img.shape[:2]

    boxes, kpss = det.detect(
        img,
        input_size=(settings.face_det_size, settings.face_det_size),
        score_thresh=settings.face_det_threshold,
        max_faces=settings.face_max_faces,
    )
    if len(boxes) == 0:
        return {"faces": [], "width": w, "height": h}

    # 너무 작은 얼굴은 이름을 붙일 만큼의 정보가 없다 — 상자만 돌려준다
    widths = boxes[:, 2] - boxes[:, 0]
    usable = widths >= settings.face_min_px

    embs = emb.embed(img, kpss)
    matches = face_index.match_embeddings(supabase, embs, committee=committee, allow_ids=allow_ids)

    # 자막의 화자는 "이대한 위원"처럼 직책이 붙는다 — 이름만 떼어 명부와 맞춘다.
    # "위원장"·"집행부 실장"처럼 이름이 아닌 라벨은 명부에 없으니 그냥 안 맞는다(해가 없다).
    hint = (speaker_hint or "").strip().split()[0] if (speaker_hint or "").strip() else ""
    faces: list[dict[str, Any]] = []
    for i, (b, m) in enumerate(zip(boxes, matches)):
        x1, y1, x2, y2 = [float(v) for v in b[:4]]
        face: dict[str, Any] = {
            "box": [round(x1 / w, 4), round(y1 / h, 4), round((x2 - x1) / w, 4), round((y2 - y1) / h, 4)],
            "det_score": round(float(b[4]), 3),
            "face_px": int(x2 - x1),
            "score": m["score"],
            "margin": m["margin"],
            "councilor_id": m["councilor_id"],
            "name": m["name"],
            "party": m["party"],
            "district": m["district"],
            "confident": bool(m["confident"] and usable[i]),
            "basis": "face",
        }
        if not usable[i]:
            face.update({"councilor_id": None, "name": None, "confident": False, "reason": "얼굴이 너무 작다"})
            faces.append(face)
            continue

        # 지금 발언자를 안다면 애매한 얼굴의 저울을 그쪽으로 기울인다.
        # 음성(발언자)과 영상(얼굴)은 서로 다른 증거라, 둘이 같은 이름을 가리키면 훨씬 믿을 만하다.
        if not face["confident"] and hint:
            for c in m["candidates"]:
                if c["name"] == hint and c["score"] >= settings.face_cos_accept - settings.face_hint_relief:
                    face.update({
                        "councilor_id": c["councilor_id"], "name": c["name"],
                        "score": c["score"], "confident": True, "basis": "face+speaker",
                    })
                    break
        elif face["confident"] and hint and face["name"] == hint:
            face["basis"] = "face+speaker"

        if face["confident"] and face["councilor_id"]:
            face_index.enroll_video_template(
                supabase, face["councilor_id"], face["name"], embs[i],
                match_score=float(m["score"]), det_score=float(b[4]),
                face_px=int(x2 - x1), channel_id=channel_id,
            )
        faces.append(face)

    faces.sort(key=lambda f: -f["face_px"])
    return {"faces": faces, "width": w, "height": h}


async def resolve_candidates(supabase: Any, channel_id: str | None, committee: str | None) -> set[str] | None:
    """이 채널에서 나올 수 있는 의원으로 후보를 좁힌다.

    상임위는 `councilors.committees` 만으로 좁혀지지만 **예산결산특별위원회·윤리특별위원회**는
    그 필드에 없다(의원정보 API 가 상임위만 준다). 그런 채널은 의회 홈페이지 명단(코드 E020 등)을
    읽어 이름으로 이어 붙인다 — 후보가 166명에서 20명으로 줄면 닮은 남과 헷갈릴 일이 크게 준다.
    명단을 못 가져오면 None(제한 없음)이며, 그때는 더 높은 임계값이 걸린다.
    """
    if not channel_id or not committee:
        return None
    ch = get_channel(channel_id)
    code = (ch or {}).get("code")
    try:
        from app.services.councilor_profile import resolve_committee_members

        rows = await resolve_committee_members(supabase, committee, code)
    except Exception as e:
        logger.warning("후보 명단 해석 실패 channel=%s: %s", channel_id, e)
        return None
    ids = {r["id"] for r in rows if r.get("id")}
    return ids if len(ids) >= 5 else None


async def identify_image(
    supabase: Any,
    raw: bytes,
    *,
    channel_id: str | None = None,
    committee: str | None = None,
    speaker_hint: str | None = None,
) -> dict[str, Any]:
    """이미지 바이트에서 의원을 식별한다."""
    if committee is None and channel_id:
        committee = get_committee_for_channel(channel_id)
    allow_ids = await resolve_candidates(supabase, channel_id, committee)
    t = time.time()
    async with _infer_sem:
        result = await asyncio.to_thread(
            _identify_sync, supabase, raw, committee, speaker_hint, channel_id, allow_ids
        )
    result["committee"] = committee
    result["candidates"] = len(allow_ids) if allow_ids else None
    result["elapsed_ms"] = int((time.time() - t) * 1000)
    named = [f for f in result.get("faces", []) if f.get("confident")]
    logger.info(
        "얼굴 식별 channel=%s 위원회=%s 후보=%s 얼굴=%d 확인=%d %dms",
        channel_id, committee, result["candidates"] or "전체",
        len(result.get("faces", [])), len(named), result["elapsed_ms"],
    )
    return result


async def identify_channel(
    supabase: Any, channel_id: str, speaker_hint: str | None = None
) -> dict[str, Any]:
    """채널의 현재 화면에서 의원을 식별한다(서버 캡처 경로)."""
    raw = await grab_frame_from_channel(channel_id)
    if not raw:
        return {"faces": [], "error": "영상 화면을 가져오지 못했습니다. 방송 중인지 확인해 주세요."}
    return await identify_image(supabase, raw, channel_id=channel_id, speaker_hint=speaker_hint)
