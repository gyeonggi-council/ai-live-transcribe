# -*- coding: utf-8 -*-
"""얼굴 검출·정렬의 순수 계산 부분 (services/face_engine, 2026-09-16).

모델 파일 없이 도는 것만 시험한다 — ONNX 추론은 Dockerfile 의 빌드 스모크가 잡는다.
"""
import importlib.util
from pathlib import Path

import numpy as np
import pytest

_spec = importlib.util.spec_from_file_location(
    "face_engine", Path(__file__).resolve().parents[2] / "app" / "services" / "face_engine.py")
try:
    fe = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(fe)
except Exception as e:  # cv2/onnxruntime 미설치 환경
    pytest.skip(f"얼굴 런타임 없음: {e}", allow_module_level=True)


def test_umeyama_recovers_known_similarity():
    """상사변환 추정이 회전·배율·평행이동을 되찾는가."""
    src = np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0], [1.0, 1.0], [0.5, 0.5]])
    theta, scale, tx, ty = np.pi / 6, 2.0, 3.0, -1.0
    R = np.array([[np.cos(theta), -np.sin(theta)], [np.sin(theta), np.cos(theta)]])
    dst = (scale * src @ R.T) + np.array([tx, ty])
    M = fe._umeyama(src, dst)
    got = src @ M[:, :2].T + M[:, 2]
    assert np.allclose(got, dst, atol=1e-6)


def test_align_face_outputs_requested_size():
    img = np.full((240, 320, 3), 128, dtype=np.uint8)
    kps = np.array([[120, 100], [180, 100], [150, 130], [125, 165], [175, 165]], dtype=np.float32)
    out = fe.align_face(img, kps, size=112)
    assert out.shape == (112, 112, 3)


def test_nms_keeps_best_and_drops_overlap():
    dets = np.array([
        [10, 10, 50, 50, 0.9],
        [12, 12, 52, 52, 0.8],   # 위와 크게 겹친다 — 버린다
        [200, 200, 240, 240, 0.7],
    ], dtype=np.float32)
    keep = fe._nms(dets, 0.4)
    assert keep == [0, 2]


def test_distance2bbox_and_kps_are_anchor_relative():
    points = np.array([[10.0, 10.0]])
    box = fe._distance2bbox(points, np.array([[1.0, 2.0, 3.0, 4.0]]))
    assert box.tolist() == [[9.0, 8.0, 13.0, 14.0]]
    kps = fe._distance2kps(points, np.array([[1.0, 1.0, 2.0, 2.0, 3.0, 3.0, 4.0, 4.0, 5.0, 5.0]]))
    assert kps.tolist() == [[11.0, 11.0, 12.0, 12.0, 13.0, 13.0, 14.0, 14.0, 15.0, 15.0]]
