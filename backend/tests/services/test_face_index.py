# -*- coding: utf-8 -*-
"""얼굴 매칭 판정 (services/face_index, 2026-09-16).

여기서 지키는 규칙은 하나다 — **애매하면 이름을 붙이지 않는다.** 회의장에는 명부에 없는 사람
(집행부 공무원·직원·방청객)이 늘 함께 잡히므로, 임계값과 1·2등 차이를 모두 넘을 때만 이름이 나간다.
"""
import sys
import types
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

try:
    from app.services import face_index
except Exception as e:  # cv2/onnxruntime 미설치
    pytest.skip(f"얼굴 런타임 없음: {e}", allow_module_level=True)


class _Result:
    def __init__(self, data):
        self.data = data


class _Table:
    def __init__(self, rows):
        self._rows = rows

    def select(self, *_a, **_k):
        return self

    def eq(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    def order(self, *_a, **_k):
        return self

    def execute(self):
        return _Result(self._rows)


class _Supabase:
    def __init__(self, faces, councilors):
        self._faces, self._councilors = faces, councilors

    def table(self, name):
        return _Table(self._faces if name == "councilor_faces" else self._councilors)


def _unit(vec):
    v = np.asarray(vec, dtype=np.float32)
    return (v / np.linalg.norm(v)).tolist()


def _fixture():
    a = _unit([1.0] + [0.0] * 511)
    b = _unit([0.0, 1.0] + [0.0] * 510)
    faces = [
        {"councilor_id": "id-a", "councilor_name": "가의원", "embedding": a, "slot": 0, "source": "portrait"},
        {"councilor_id": "id-b", "councilor_name": "나의원", "embedding": b, "slot": 0, "source": "portrait"},
    ]
    councilors = [
        {"id": "id-a", "name": "가의원", "party": "정당1", "district": "지역1",
         "committees": [{"name": "기획재정위원회", "role": "위원"}], "profile_image_url": None},
        {"id": "id-b", "name": "나의원", "party": "정당2", "district": "지역2",
         "committees": [{"name": "경제노동위원회", "role": "위원"}], "profile_image_url": None},
    ]
    return _Supabase(faces, councilors), np.asarray([a, b], dtype=np.float32)


@pytest.fixture(autouse=True)
def _clean_gallery():
    face_index.invalidate_gallery()
    yield
    face_index.invalidate_gallery()


def test_exact_match_gets_named():
    sb, vecs = _fixture()
    out = face_index.match_embeddings(sb, vecs[:1])
    assert out[0]["name"] == "가의원"
    assert out[0]["confident"] is True
    assert out[0]["score"] == pytest.approx(1.0, abs=1e-3)


def test_stranger_is_not_named():
    """명부에 없는 사람 — 점수가 낮으면 이름을 붙이지 않는다."""
    sb, _ = _fixture()
    stranger = np.asarray([_unit([0.0, 0.0, 1.0] + [0.0] * 509)], dtype=np.float32)
    out = face_index.match_embeddings(sb, stranger)
    assert out[0]["name"] is None
    assert out[0]["confident"] is False


def test_ambiguous_between_two_is_not_named(monkeypatch):
    """1등과 2등이 붙어 있으면(여유 부족) 이름을 붙이지 않는다."""
    sb, _ = _fixture()
    monkeypatch.setattr(face_index.settings, "face_cos_accept_open", 0.3, raising=False)
    monkeypatch.setattr(face_index.settings, "face_cos_margin", 0.2, raising=False)
    mid = np.asarray([_unit([1.0, 1.0] + [0.0] * 510)], dtype=np.float32)  # 두 사람 한가운데
    out = face_index.match_embeddings(sb, mid)
    assert out[0]["confident"] is False
    assert out[0]["margin"] == pytest.approx(0.0, abs=1e-3)


def test_empty_gallery_returns_placeholder_rows():
    """명부가 비어도 **호출부가 읽는 열쇠를 모두** 갖춰 돌려준다.

    2026-09-16 운영 장애: party·district 가 빠져 얼굴 식별이 KeyError 로 500 이었다.
    적재 직후 캐시가 아직 빈 5분 동안만 나타나 재현이 어려웠다.
    """
    sb = _Supabase([], [])
    out = face_index.match_embeddings(sb, np.zeros((2, 512), dtype=np.float32))
    assert len(out) == 2
    required = {"councilor_id", "name", "party", "district", "score", "margin",
                "confident", "restricted", "candidates"}
    for row in out:
        assert required <= set(row), required - set(row)
        assert row["name"] is None


def test_every_result_row_has_the_same_keys():
    """정상 경로와 빈 경로의 열쇠가 어긋나면 화면이 통째로 죽는다."""
    sb, vecs = _fixture()
    filled = face_index.match_embeddings(sb, vecs[:1])[0]
    blank = face_index.match_embeddings(_Supabase([], []), np.zeros((1, 512), dtype=np.float32))[0]
    assert set(filled) == set(blank)


def test_gallery_stats_reports_missing_members():
    sb, _ = _fixture()
    sb._faces = [sb._faces[0]]  # 나의원 얼굴 없음
    stats = face_index.gallery_stats(sb)
    assert stats["councilors_with_face"] == 1
    assert "나의원" in stats["missing"]
