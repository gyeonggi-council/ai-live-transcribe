# -*- coding: utf-8 -*-
"""의원 얼굴 명부(gallery) — 임베딩 적재·갱신·매칭.

무엇을 푸는가: 회의 영상 화면에 잡힌 얼굴이 **어느 의원인가**.

왜 이렇게 생겼는가
------------------
* **후보를 먼저 좁힌다.** 채널(위원회)을 알면 후보가 현역 166명에서 13~20명으로 준다.
  얼굴 인식의 오답은 대부분 "닮은 남"에서 나오므로, 후보를 줄이는 것이 임계값을 만지는 것보다
  훨씬 크게 정확도를 올린다.
* **한 사람에 템플릿 여러 장.** slot 0 은 공식 증명사진(정면·스튜디오 조명)이고, slot 1.. 은
  회의 영상에서 아주 확신할 때만 자동으로 담아 둔 현장 얼굴이다. 증명사진 한 장만으로 맞추면
  회의장 조명·측면 각도·안경 착용 차이를 전부 떠안는다. 같은 카메라에서 온 템플릿이 하나라도
  있으면 그 차이가 사라진다. 매칭은 **템플릿 중 최고점**을 그 사람의 점수로 쓴다.
* **점수 하나로 판정하지 않는다.** 1등 점수(`accept`)와 1·2등 차이(`margin`)를 함께 본다.
  회의장에는 의원이 아닌 사람(집행부 공무원·보좌진·방청객)이 늘 함께 잡히는데, 그들은 명부에
  정답이 없으므로 "1등이 그럭저럭 높다"만 보면 반드시 남의 이름이 붙는다. 실측에서 의원이
  아닌 얼굴의 최고점은 0.34 를 넘지 않았고 의원 본인은 0.49~0.62 였다(2026-09-16 ch60).

임계값 정본은 `docs/face-recognition-eval-2026-09.md` 와 `core/config.py` 의 `face_*` 값이다.
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from typing import Any

import numpy as np

from app.core.config import settings

logger = logging.getLogger(__name__)

# 임베딩 모델 식별자 — 모델을 바꾸면 이 값을 바꾼다. 섞이면 점수가 무의미해지므로
# 매칭·적재 모두 이 값으로 걸러 읽는다.
FACE_MODEL_ID = "w600k_r50"

_TABLE = "councilor_faces"


class FaceModelUnavailable(RuntimeError):
    """모델 파일이 없거나 onnxruntime 이 없어 얼굴 기능을 쓸 수 없다."""


# ─── 모델 (프로세스당 1회 적재) ────────────────────────────────────────────────
_lock = threading.Lock()
_detector: Any = None
_embedder: Any = None


def _model_path(rel: str) -> str:
    if os.path.isabs(rel):
        return rel
    return os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), rel)


def load_models() -> tuple[Any, Any]:
    """검출기·임베더를 적재한다(최초 1회). 없으면 FaceModelUnavailable."""
    global _detector, _embedder
    if _detector is not None and _embedder is not None:
        return _detector, _embedder
    with _lock:
        if _detector is not None and _embedder is not None:
            return _detector, _embedder
        det_path = _model_path(settings.face_det_model_path)
        rec_path = _model_path(settings.face_rec_model_path)
        for p in (det_path, rec_path):
            if not os.path.isfile(p):
                raise FaceModelUnavailable(f"얼굴 모델 파일이 없다: {p}")
        try:
            from app.services.face_engine import ArcFaceEmbedder, ScrfdDetector
        except Exception as e:  # onnxruntime/opencv 미설치
            raise FaceModelUnavailable(f"얼굴 런타임을 불러올 수 없다: {e}") from e
        t = time.time()
        _detector = ScrfdDetector(det_path, num_threads=settings.face_threads)
        _embedder = ArcFaceEmbedder(rec_path, num_threads=settings.face_threads)
        logger.info("얼굴 모델 적재 완료 (%.1fs) det=%s rec=%s", time.time() - t, det_path, rec_path)
        return _detector, _embedder


def models_ready() -> bool:
    try:
        load_models()
        return True
    except Exception:
        return False


# ─── 명부 캐시 ────────────────────────────────────────────────────────────────
class _Gallery:
    """councilor_faces 를 메모리에 올린 것. 행 수가 수백이라 통째로 든다."""

    def __init__(self) -> None:
        self.mat: np.ndarray = np.zeros((0, 512), dtype=np.float32)
        self.owner: list[str] = []          # 행 → councilor_id
        self.meta: dict[str, dict] = {}     # councilor_id → {name, party, district, committees, photo}
        self.loaded_at: float = 0.0

    @property
    def empty(self) -> bool:
        return self.mat.shape[0] == 0


_gallery = _Gallery()
_gallery_lock = threading.Lock()


def _fetch_gallery_rows(supabase: Any) -> tuple[list[dict], list[dict]]:
    faces = (
        supabase.table(_TABLE)
        .select("councilor_id,councilor_name,embedding,slot,source")
        .eq("model", FACE_MODEL_ID)
        .limit(5000)
        .execute()
    ).data or []
    councilors = (
        supabase.table("councilors")
        .select("id,name,party,district,committees,profile_image_url")
        .eq("is_active", True)
        .limit(1000)
        .execute()
    ).data or []
    return faces, councilors


def load_gallery(supabase: Any, force: bool = False) -> _Gallery:
    """명부를 적재한다. TTL 안이면 캐시를 그대로 쓴다."""
    global _gallery
    with _gallery_lock:
        fresh = (time.time() - _gallery.loaded_at) < settings.face_gallery_ttl_seconds
        if _gallery.loaded_at and fresh and not force:
            return _gallery
        try:
            faces, councilors = _fetch_gallery_rows(supabase)
        except Exception as e:
            logger.warning("얼굴 명부 조회 실패: %s", e)
            return _gallery
        g = _Gallery()
        g.meta = {
            c["id"]: {
                "name": c.get("name"),
                "party": c.get("party"),
                "district": c.get("district"),
                "committees": [x.get("name") for x in (c.get("committees") or []) if isinstance(x, dict)],
                "profile_image_url": c.get("profile_image_url"),
            }
            for c in councilors
        }
        vecs: list[list[float]] = []
        owner: list[str] = []
        for f in faces:
            emb = f.get("embedding")
            if not isinstance(emb, list) or len(emb) != 512:
                continue
            cid = f.get("councilor_id")
            if cid not in g.meta:
                continue  # 비활성 의원의 잔여 행
            vecs.append(emb)
            owner.append(cid)
        if vecs:
            m = np.asarray(vecs, dtype=np.float32)
            norms = np.linalg.norm(m, axis=1, keepdims=True)
            norms[norms == 0] = 1.0
            g.mat = m / norms
        g.owner = owner
        g.loaded_at = time.time()
        _gallery = g
        logger.info("얼굴 명부 적재: 템플릿 %d개 · 의원 %d명", len(owner), len(set(owner)))
        return _gallery


def invalidate_gallery() -> None:
    with _gallery_lock:
        _gallery.loaded_at = 0.0


def gallery_stats(supabase: Any) -> dict[str, Any]:
    g = load_gallery(supabase)
    by_owner: dict[str, int] = {}
    for o in g.owner:
        by_owner[o] = by_owner.get(o, 0) + 1
    return {
        "model": FACE_MODEL_ID,
        "templates": len(g.owner),
        "councilors_with_face": len(by_owner),
        "councilors_total": len(g.meta),
        "missing": sorted(
            [m["name"] for cid, m in g.meta.items() if cid not in by_owner and m.get("name")]
        ),
        "models_ready": models_ready(),
        "loaded_at": g.loaded_at,
    }


# ─── 매칭 ─────────────────────────────────────────────────────────────────────
def _candidate_mask(g: _Gallery, committee: str | None, allow_ids: set[str] | None) -> np.ndarray | None:
    """후보 제한 마스크. 제한이 없으면 None."""
    if allow_ids:
        idx = [i for i, o in enumerate(g.owner) if o in allow_ids]
        return np.asarray(idx, dtype=np.int64) if idx else np.zeros((0,), dtype=np.int64)
    if committee:
        norm = committee.replace(" ", "")
        idx = [
            i for i, o in enumerate(g.owner)
            if any(norm == (c or "").replace(" ", "") for c in g.meta.get(o, {}).get("committees", []))
        ]
        # 후보가 지나치게 적으면(명부 미상 위원회 등) 제한하지 않는다 — 없는 것보다 전체가 낫다
        if len(set(g.owner[i] for i in idx)) >= 5:
            return np.asarray(idx, dtype=np.int64)
    return None


def _blank_match() -> dict[str, Any]:
    """판정할 수 없을 때의 빈 결과 — 모든 열쇠를 갖춘다."""
    return {
        "councilor_id": None, "name": None, "party": None, "district": None,
        "score": 0.0, "margin": 0.0, "confident": False, "restricted": False,
        "candidates": [],
    }


def match_embeddings(
    supabase: Any,
    embeddings: np.ndarray,
    committee: str | None = None,
    allow_ids: set[str] | None = None,
    top_k: int = 3,
) -> list[dict[str, Any]]:
    """얼굴 임베딩 (N,512) → 얼굴마다 상위 후보와 판정.

    반환 각 항목: {councilor_id, name, score, margin, confident, candidates:[{name,score}]}
    """
    g = load_gallery(supabase)
    if g.empty or embeddings.shape[0] == 0:
        # 명부가 비어 있어도 **호출부가 기대하는 열쇠를 모두** 채워 돌려준다.
        # 2026-09-16: 여기서 party·district 를 빼먹어 얼굴 식별이 통째로 500(KeyError: 'party')이었다 —
        # 적재 직후 캐시가 아직 빈 5분 동안만 나타나서 더 찾기 어려웠다.
        return [_blank_match() for _ in range(embeddings.shape[0])]

    mask = _candidate_mask(g, committee, allow_ids)
    if mask is not None and mask.shape[0] == 0:
        mask = None
    mat = g.mat if mask is None else g.mat[mask]
    owner = g.owner if mask is None else [g.owner[i] for i in mask]
    restricted = mask is not None

    sims = embeddings @ mat.T  # (N, T)
    out: list[dict[str, Any]] = []
    owners = np.asarray(owner)
    uniq = list(dict.fromkeys(owner))
    # 사람별 최고 템플릿 점수로 접는다
    index_of = {cid: np.where(owners == cid)[0] for cid in uniq}
    accept = settings.face_cos_accept if restricted else settings.face_cos_accept_open
    for i in range(sims.shape[0]):
        row = sims[i]
        per_person = np.asarray([row[index_of[cid]].max() for cid in uniq], dtype=np.float32)
        order = np.argsort(-per_person)
        best = int(order[0])
        score = float(per_person[best])
        second = float(per_person[order[1]]) if len(order) > 1 else 0.0
        margin = score - second
        cid = uniq[best]
        meta = g.meta.get(cid, {})
        confident = score >= accept and margin >= settings.face_cos_margin
        out.append({
            "councilor_id": cid if confident else None,
            "name": meta.get("name") if confident else None,
            "party": meta.get("party") if confident else None,
            "district": meta.get("district") if confident else None,
            "score": round(score, 3),
            "margin": round(margin, 3),
            "confident": confident,
            "restricted": restricted,
            "candidates": [
                {"councilor_id": uniq[j], "name": g.meta.get(uniq[j], {}).get("name"),
                 "score": round(float(per_person[j]), 3)}
                for j in order[:top_k]
            ],
        })
    return out


# ─── 적재(증명사진) ───────────────────────────────────────────────────────────
async def _download(url: str) -> bytes | None:
    import httpx

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Referer": "https://www.ggc.go.kr/",
    }
    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            r = await client.get(url, headers=headers)
            r.raise_for_status()
            return r.content
    except Exception as e:
        logger.warning("사진 내려받기 실패 %s: %s", url, e)
        return None


def embed_image_bytes(raw: bytes, largest_only: bool = True) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """이미지 바이트 → (bboxes, kpss, embeddings). 얼굴이 없으면 빈 배열."""
    import cv2

    det, emb = load_models()
    img = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return np.zeros((0, 5), np.float32), np.zeros((0, 5, 2), np.float32), np.zeros((0, 512), np.float32)
    boxes, kpss = det.detect(img, score_thresh=settings.face_det_threshold)
    if len(boxes) == 0:
        return boxes, kpss, np.zeros((0, 512), np.float32)
    if largest_only:
        i = int(np.argmax((boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1])))
        boxes, kpss = boxes[i:i + 1], kpss[i:i + 1]
    return boxes, kpss, emb.embed(img, kpss)


async def rebuild_portrait_gallery(supabase: Any, only_missing: bool = True) -> dict[str, Any]:
    """현역 의원 공식 사진을 내려받아 slot 0 템플릿을 채운다(멱등).

    사진 원본은 ggc.go.kr 이므로 **아웃바운드가 되는 곳에서만** 성공한다. 실패한 의원은
    건너뛰고 목록으로 돌려준다 — 한 명 때문에 전체가 실패하지 않게 한다.
    """
    load_models()
    rows = (
        supabase.table("councilors")
        .select("id,name,profile_image_url")
        .eq("is_active", True)
        .limit(1000)
        .execute()
    ).data or []

    existing: set[str] = set()
    if only_missing:
        have = (
            supabase.table(_TABLE).select("councilor_id").eq("model", FACE_MODEL_ID).eq("slot", 0)
            .limit(5000).execute()
        ).data or []
        existing = {h["councilor_id"] for h in have}

    added, skipped = 0, []
    for r in rows:
        cid, name, url = r["id"], r.get("name"), r.get("profile_image_url")
        if only_missing and cid in existing:
            continue
        if not url:
            skipped.append({"name": name, "reason": "사진 주소 없음"})
            continue
        raw = await _download(url)
        if not raw:
            skipped.append({"name": name, "reason": "사진 내려받기 실패"})
            continue
        try:
            boxes, _kpss, embs = await asyncio.to_thread(embed_image_bytes, raw, True)
        except Exception as e:
            skipped.append({"name": name, "reason": f"임베딩 실패: {e}"})
            continue
        if embs.shape[0] == 0:
            skipped.append({"name": name, "reason": "사진에서 얼굴을 찾지 못함"})
            continue
        try:
            supabase.table(_TABLE).upsert({
                "councilor_id": cid,
                "councilor_name": name,
                "model": FACE_MODEL_ID,
                "slot": 0,
                "source": "portrait",
                "embedding": [float(x) for x in embs[0]],
                "det_score": float(boxes[0][4]),
                "face_px": int(boxes[0][2] - boxes[0][0]),
            }, on_conflict="councilor_id,model,slot").execute()
            added += 1
        except Exception as e:
            skipped.append({"name": name, "reason": f"저장 실패: {e}"})

    invalidate_gallery()
    return {"added": added, "skipped": skipped, "total": len(rows)}


def enroll_video_template(
    supabase: Any,
    councilor_id: str,
    councilor_name: str,
    embedding: np.ndarray,
    *,
    match_score: float,
    det_score: float,
    face_px: int,
    channel_id: str | None,
) -> bool:
    """영상에서 아주 확신한 얼굴을 현장 템플릿으로 담는다(slot 1..N 순환).

    잘못 담기면 그 이름이 계속 틀리게 나오므로 **점수·여유·해상도 세 관문을 모두** 넘을 때만
    담는다. 상한(`face_max_video_templates`)에 닿으면 가장 오래된 현장 템플릿을 덮어쓴다.
    """
    if not settings.face_auto_enroll:
        return False
    if (match_score < settings.face_enroll_min_score
            or face_px < settings.face_enroll_min_px
            or det_score < settings.face_enroll_min_det):
        return False
    try:
        have = (
            supabase.table(_TABLE)
            .select("id,slot,created_at")
            .eq("councilor_id", councilor_id).eq("model", FACE_MODEL_ID).eq("source", "video")
            .order("created_at", desc=False).limit(50).execute()
        ).data or []
        used = {int(h["slot"]) for h in have}
        limit = settings.face_max_video_templates
        slot = next((s for s in range(1, limit + 1) if s not in used), None)
        if slot is None:
            slot = int(have[0]["slot"])  # 가장 오래된 것을 덮는다
        supabase.table(_TABLE).upsert({
            "councilor_id": councilor_id,
            "councilor_name": councilor_name,
            "model": FACE_MODEL_ID,
            "slot": slot,
            "source": "video",
            "embedding": [float(x) for x in embedding],
            "det_score": float(det_score),
            "face_px": int(face_px),
            "match_score": float(match_score),
            "channel_id": channel_id,
            "captured_at": _now_iso(),
        }, on_conflict="councilor_id,model,slot").execute()
        invalidate_gallery()
        return True
    except Exception as e:
        logger.warning("현장 템플릿 등록 실패 %s: %s", councilor_name, e)
        return False


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
