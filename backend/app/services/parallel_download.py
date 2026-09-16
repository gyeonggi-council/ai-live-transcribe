# -*- coding: utf-8 -*-
"""병렬 Range 다운로더 — KMS의 '연결당 스로틀'을 우회한다.

실측: KMS는 단일 연결을 ~0.3MB/s로 스로틀하지만 연결당 독립적이라, 8~12개 병렬
Range 연결의 집계 처리량이 ~9배(0.3→3MB/s)가 된다. 1.6GB VOD가 ~2.5시간→~9분.

설계:
  - 전체 파일을 작은 task(기본 16MB)로 쪼개 큐에 넣고, N개 워커가 각자 Range로 받아
    파일의 해당 오프셋에 쓴다(워커풀 = 자동 부하분산 + 실패 task만 재시도).
  - 파일을 미리 전체 크기로 truncate → 워커들이 비겹침 구간에 독립적으로 기록.
  - 모든 task 성공 + 최종 크기 일치 검증(불완전 다운로드 방지).
"""

from __future__ import annotations

import logging
import os
import queue
import threading
import time
import urllib.request

logger = logging.getLogger(__name__)

_DEFAULT_HEADERS = {
    "Referer": "https://kms.ggc.go.kr/",
    "User-Agent": "Mozilla/5.0",
}


def _probe_size(url: str) -> int:
    """Content-Range로 전체 크기를 얻는다(HEAD 미지원 서버 대비 GET Range 1바이트)."""
    req = urllib.request.Request(url, headers={**_DEFAULT_HEADERS, "Range": "bytes=0-0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        ctype = (r.headers.get("Content-Type") or "").lower()
        if "text/html" in ctype:
            raise RuntimeError("서버가 영상 대신 HTML(에러 페이지)을 반환했습니다.")
        cr = r.headers.get("Content-Range")  # "bytes 0-0/1613..."
        if cr and "/" in cr:
            tail = cr.rsplit("/", 1)[-1].strip()
            if tail.isdigit():
                return int(tail)
        cl = r.headers.get("Content-Length")
        # Range 미지원(200 전체응답)이면 병렬 불가 신호로 0 반환
        if r.status == 200 and cl:
            return -int(cl)  # 음수 = Range 미지원 표시
    return 0


def download_parallel(
    url: str,
    out_path: str,
    connections: int = 12,
    task_size: int = 16 * 1024 * 1024,
    max_retries: int = 5,
    progress_cb=None,
) -> int:
    """url을 out_path로 병렬 Range 다운로드. 반환: 받은 바이트 수.

    Range 미지원이면 RuntimeError(호출자가 단일연결로 폴백). 일부 task가 끝내 실패하면
    RuntimeError(불완전 파일을 성공으로 위장하지 않음).
    """
    size = _probe_size(url)
    if size < 0:
        raise RuntimeError("서버가 Range를 지원하지 않습니다(병렬 불가).")
    if size == 0:
        raise RuntimeError("파일 크기를 확인할 수 없습니다.")

    with open(out_path, "wb") as f:  # 전체 크기로 미리 확보
        f.truncate(size)

    q: "queue.Queue[tuple[int, int]]" = queue.Queue()
    off = 0
    while off < size:
        end = min(off + task_size, size) - 1
        q.put((off, end))
        off = end + 1
    total_tasks = q.qsize()

    errors: list[tuple[int, int]] = []
    done = [0]
    lock = threading.Lock()

    def worker() -> None:
        while True:
            try:
                start, end = q.get_nowait()
            except queue.Empty:
                return
            ok = False
            for attempt in range(max_retries):
                try:
                    req = urllib.request.Request(
                        url, headers={**_DEFAULT_HEADERS, "Range": f"bytes={start}-{end}"}
                    )
                    with urllib.request.urlopen(req, timeout=120) as r:
                        data = r.read()
                    if len(data) != (end - start + 1):
                        raise OSError(f"부분 응답 {len(data)}/{end - start + 1}")
                    with open(out_path, "r+b") as f:
                        f.seek(start)
                        f.write(data)
                    ok = True
                    break
                except Exception as e:
                    if attempt == max_retries - 1:
                        logger.warning("병렬 task 실패 %d-%d: %s", start, end, e)
                    time.sleep(min(2 ** attempt, 15))
            with lock:
                if not ok:
                    errors.append((start, end))
                done[0] += 1
                if progress_cb:
                    progress_cb(done[0], total_tasks)

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(connections)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    if errors:
        raise RuntimeError(f"병렬 다운로드 {len(errors)}개 구간 실패")
    actual = os.path.getsize(out_path)
    if actual != size:
        raise RuntimeError(f"다운로드 크기 불일치 {actual}/{size}")
    return size
