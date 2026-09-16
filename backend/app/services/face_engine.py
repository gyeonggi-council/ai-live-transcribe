"""얼굴 검출(SCRFD) + 얼굴 임베딩(ArcFace) — onnxruntime 단독.

insightface 패키지를 쓰지 않는다: scikit-image·scipy·cython 빌드까지 끌고 와
런타임 이미지가 200MB 넘게 불어나는데, 실제로 필요한 것은 아래 두 모델의
전/후처리뿐이다. 여기서는 그 둘만 numpy 로 직접 구현한다.

모델 (insightface v0.7 릴리스 buffalo_l / buffalo_s, Dockerfile 이 sha256 으로 검증해 굽는다):
  det_10g.onnx  / det_500m.onnx  — SCRFD, stride 8/16/32 · anchor 2 · 5점 랜드마크
  w600k_r50.onnx / w600k_mbf.onnx — ArcFace(glint360k), 112x112 → 512차원 단위벡터
"""

from __future__ import annotations

import logging
from typing import Any

import cv2
import numpy as np
import onnxruntime as ort

logger = logging.getLogger(__name__)

# ArcFace 표준 정렬 기준점 (112x112) — 눈·코·입 5점
_ARCFACE_REF = np.array(
    [
        [38.2946, 51.6963],
        [73.5318, 51.5014],
        [56.0252, 71.7366],
        [41.5493, 92.3655],
        [70.7299, 92.2041],
    ],
    dtype=np.float32,
)


def _umeyama(src: np.ndarray, dst: np.ndarray) -> np.ndarray:
    """상사변환(회전+등방스케일+평행이동) 추정 — skimage.SimilarityTransform 대체."""
    num, dim = src.shape
    src_mean = src.mean(axis=0)
    dst_mean = dst.mean(axis=0)
    src_demean = src - src_mean
    dst_demean = dst - dst_mean
    A = dst_demean.T @ src_demean / num
    d = np.ones((dim,), dtype=np.float64)
    if np.linalg.det(A) < 0:
        d[dim - 1] = -1
    T = np.eye(dim + 1, dtype=np.float64)
    U, S, Vt = np.linalg.svd(A)
    rank = np.linalg.matrix_rank(A)
    if rank == 0:
        return np.eye(dim + 1)[:dim]
    if rank == dim - 1:
        if np.linalg.det(U) * np.linalg.det(Vt) > 0:
            T[:dim, :dim] = U @ Vt
        else:
            s = d[dim - 1]
            d[dim - 1] = -1
            T[:dim, :dim] = U @ np.diag(d) @ Vt
            d[dim - 1] = s
    else:
        T[:dim, :dim] = U @ np.diag(d) @ Vt
    scale = 1.0 / src_demean.var(axis=0).sum() * (S @ d)
    T[:dim, dim] = dst_mean - scale * (T[:dim, :dim] @ src_mean)
    T[:dim, :dim] *= scale
    return T[:dim]


def align_face(img: np.ndarray, kps: np.ndarray, size: int = 112) -> np.ndarray:
    """5점 랜드마크로 얼굴을 112x112 정면 규격으로 편다."""
    ref = _ARCFACE_REF * (size / 112.0)
    M = _umeyama(np.asarray(kps, dtype=np.float64), ref.astype(np.float64))
    return cv2.warpAffine(img, M.astype(np.float32), (size, size), borderValue=0.0)


def _distance2bbox(points: np.ndarray, distance: np.ndarray) -> np.ndarray:
    x1 = points[:, 0] - distance[:, 0]
    y1 = points[:, 1] - distance[:, 1]
    x2 = points[:, 0] + distance[:, 2]
    y2 = points[:, 1] + distance[:, 3]
    return np.stack([x1, y1, x2, y2], axis=-1)


def _distance2kps(points: np.ndarray, distance: np.ndarray) -> np.ndarray:
    preds = []
    for i in range(0, distance.shape[1], 2):
        preds.append(points[:, 0] + distance[:, i])
        preds.append(points[:, 1] + distance[:, i + 1])
    return np.stack(preds, axis=-1)


def _nms(dets: np.ndarray, thresh: float) -> list[int]:
    x1, y1, x2, y2, scores = dets[:, 0], dets[:, 1], dets[:, 2], dets[:, 3], dets[:, 4]
    areas = (x2 - x1 + 1) * (y2 - y1 + 1)
    order = scores.argsort()[::-1]
    keep = []
    while order.size > 0:
        i = order[0]
        keep.append(int(i))
        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])
        w = np.maximum(0.0, xx2 - xx1 + 1)
        h = np.maximum(0.0, yy2 - yy1 + 1)
        inter = w * h
        ovr = inter / (areas[i] + areas[order[1:]] - inter)
        order = order[np.where(ovr <= thresh)[0] + 1]
    return keep


class ScrfdDetector:
    """SCRFD 얼굴 검출기 (det_10g / det_500m 공통 — 출력 텐서 수로 구조를 읽는다)."""

    def __init__(self, model_path: str, num_threads: int = 1) -> None:
        so = ort.SessionOptions()
        so.intra_op_num_threads = num_threads
        so.inter_op_num_threads = 1
        so.log_severity_level = 3
        self.session = ort.InferenceSession(model_path, sess_options=so, providers=["CPUExecutionProvider"])
        self.input_name = self.session.get_inputs()[0].name
        self.output_names = [o.name for o in self.session.get_outputs()]
        n_out = len(self.output_names)
        # 출력 9개 = stride 3종 × (score, bbox, kps)
        self.fmc = n_out // 3
        self._feat_strides = [8, 16, 32] if self.fmc == 3 else [8, 16, 32, 64, 128]
        self._num_anchors = 2
        self._use_kps = n_out % 3 == 0 and n_out >= 9
        self._center_cache: dict[tuple[int, int, int], np.ndarray] = {}

    def detect(
        self,
        img: np.ndarray,
        input_size: tuple[int, int] = (640, 640),
        score_thresh: float = 0.5,
        nms_thresh: float = 0.4,
        max_faces: int = 40,
    ) -> tuple[np.ndarray, np.ndarray]:
        """BGR 이미지에서 얼굴 검출 → (bboxes Nx5[x1,y1,x2,y2,score], kps Nx5x2)."""
        ih, iw = img.shape[:2]
        tw, th = input_size
        scale = min(tw / iw, th / ih)
        nw, nh = int(round(iw * scale)), int(round(ih * scale))
        resized = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LINEAR)
        canvas = np.zeros((th, tw, 3), dtype=np.uint8)
        canvas[:nh, :nw] = resized

        blob = cv2.dnn.blobFromImage(canvas, 1.0 / 128.0, (tw, th), (127.5, 127.5, 127.5), swapRB=True)
        outs = self.session.run(self.output_names, {self.input_name: blob})

        scores_list, bboxes_list, kpss_list = [], [], []
        for idx, stride in enumerate(self._feat_strides):
            scores = outs[idx]
            bbox_preds = outs[idx + self.fmc] * stride
            kps_preds = outs[idx + self.fmc * 2] * stride if self._use_kps else None
            height, width = th // stride, tw // stride
            key = (height, width, stride)
            anchor_centers = self._center_cache.get(key)
            if anchor_centers is None:
                ac = np.stack(np.mgrid[:height, :width][::-1], axis=-1).astype(np.float32) * stride
                ac = ac.reshape((-1, 2))
                if self._num_anchors > 1:
                    ac = np.stack([ac] * self._num_anchors, axis=1).reshape((-1, 2))
                if len(self._center_cache) < 100:
                    self._center_cache[key] = ac
                anchor_centers = ac
            scores = scores.reshape(-1)
            pos = np.where(scores >= score_thresh)[0]
            if pos.size == 0:
                continue
            bboxes = _distance2bbox(anchor_centers, bbox_preds.reshape(-1, 4))[pos]
            scores_list.append(scores[pos])
            bboxes_list.append(bboxes)
            if kps_preds is not None:
                kpss = _distance2kps(anchor_centers, kps_preds.reshape(-1, 10))[pos]
                kpss_list.append(kpss.reshape(-1, 5, 2))

        if not scores_list:
            return np.zeros((0, 5), dtype=np.float32), np.zeros((0, 5, 2), dtype=np.float32)

        scores = np.concatenate(scores_list)
        bboxes = np.concatenate(bboxes_list) / scale
        order = scores.argsort()[::-1]
        dets = np.hstack([bboxes, scores[:, None]]).astype(np.float32)[order]
        kpss = (np.concatenate(kpss_list) / scale).astype(np.float32)[order] if kpss_list else np.zeros((len(dets), 5, 2), np.float32)
        keep = _nms(dets, nms_thresh)[:max_faces]
        return dets[keep], kpss[keep]


class ArcFaceEmbedder:
    """ArcFace 임베딩 — 정렬된 112x112 얼굴 → 512차원 단위벡터."""

    def __init__(self, model_path: str, num_threads: int = 1) -> None:
        so = ort.SessionOptions()
        so.intra_op_num_threads = num_threads
        so.inter_op_num_threads = 1
        so.log_severity_level = 3
        self.session = ort.InferenceSession(model_path, sess_options=so, providers=["CPUExecutionProvider"])
        inp = self.session.get_inputs()[0]
        self.input_name = inp.name
        self.input_size = (int(inp.shape[3]), int(inp.shape[2])) if len(inp.shape) == 4 else (112, 112)
        self.output_name = self.session.get_outputs()[0].name

    def embed_aligned(self, faces: list[np.ndarray]) -> np.ndarray:
        """정렬된 얼굴 목록 → (N, 512) 단위벡터."""
        if not faces:
            return np.zeros((0, 512), dtype=np.float32)
        blob = cv2.dnn.blobFromImages(faces, 1.0 / 127.5, self.input_size, (127.5, 127.5, 127.5), swapRB=True)
        out = self.session.run([self.output_name], {self.input_name: blob})[0]
        norms = np.linalg.norm(out, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return (out / norms).astype(np.float32)

    def embed(self, img: np.ndarray, kpss: np.ndarray) -> np.ndarray:
        aligned = [align_face(img, k, self.input_size[0]) for k in kpss]
        return self.embed_aligned(aligned)
