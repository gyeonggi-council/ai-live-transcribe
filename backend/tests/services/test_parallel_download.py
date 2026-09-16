# -*- coding: utf-8 -*-
"""병렬 Range 다운로더 단위 테스트 (네트워크 모킹)."""
import re
from pathlib import Path
from unittest.mock import patch

import pytest

from app.services import parallel_download as pd

FAKE = bytes(i % 256 for i in range(200_000))  # 알려진 200KB 블롭


class _FakeResp:
    def __init__(self, data: bytes, headers: dict, status: int = 206):
        self._data = data
        self.headers = headers
        self.status = status

    def read(self, n: int = -1) -> bytes:
        if n == -1:
            d, self._data = self._data, b""
            return d
        d, self._data = self._data[:n], self._data[n:]
        return d

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _fake_urlopen(req, timeout=None):
    rng = req.get_header("Range")
    m = re.match(r"bytes=(\d+)-(\d*)", rng)
    start = int(m.group(1))
    end = int(m.group(2)) if m.group(2) else len(FAKE) - 1
    data = FAKE[start:end + 1]
    headers = {
        "Content-Range": f"bytes {start}-{end}/{len(FAKE)}",
        "Content-Type": "video/mp4",
        "Content-Length": str(len(data)),
    }
    return _FakeResp(data, headers)


def test_parallel_download_reassembles_correctly(tmp_path):
    out = tmp_path / "out.bin"
    with patch.object(pd.urllib.request, "urlopen", _fake_urlopen):
        size = pd.download_parallel(
            "http://x/file", str(out), connections=4, task_size=32 * 1024
        )
    assert size == len(FAKE)
    assert out.read_bytes() == FAKE  # 모든 구간이 올바른 오프셋에 기록됨


def test_probe_size_parses_content_range():
    with patch.object(pd.urllib.request, "urlopen", _fake_urlopen):
        assert pd._probe_size("http://x/file") == len(FAKE)


def test_parallel_download_rejects_html_error_page():
    def html_resp(req, timeout=None):
        return _FakeResp(b"<html>error</html>",
                         {"Content-Type": "text/html"}, status=200)
    with patch.object(pd.urllib.request, "urlopen", html_resp):
        with pytest.raises(RuntimeError):
            pd.download_parallel("http://x/file", "x", connections=2)
