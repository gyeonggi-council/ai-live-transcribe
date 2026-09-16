"""MP4 → HLS 실시간 테스트 스트리밍 스크립트

KMS VOD MP4를 ffmpeg로 HLS 라이브 스트림으로 변환하여
로컬에서 실시간 자막 파이프라인을 테스트합니다.

사용법:
    python backend/scripts/hls_test_stream.py --mp4-url "https://example.com/video.mp4"
    python backend/scripts/hls_test_stream.py --mp4-url "C:/path/to/local.mp4" --port 8088

동작:
    1. ffmpeg가 MP4를 실시간 속도(-re)로 읽어 HLS 세그먼트 출력
    2. threading HTTP 서버가 HLS 파일 서빙 (CORS 허용)
    3. http://localhost:8088/playlist.m3u8 로 접근
"""

import argparse
import http.server
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

HLS_OUTPUT_DIR = Path(__file__).parent / "hls_output"


class CORSRequestHandler(http.server.SimpleHTTPRequestHandler):
    """CORS 헤더를 추가하는 HTTP 요청 핸들러"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(HLS_OUTPUT_DIR), **kwargs)

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.end_headers()

    def log_message(self, format, *args):
        # 짧은 로그 형식
        sys.stdout.write(f"[HTTP] {args[0]}\n")


def start_http_server(port: int) -> http.server.HTTPServer:
    """HLS 파일 서빙 HTTP 서버 시작 (별도 스레드)

    ★ThreadingHTTPServer 필수: 단일 스레드면 [브라우저 플레이어 + 백엔드 STT
    피더 + 검증 스크립트]가 직렬화되어 세그먼트 공급이 수십 초씩 밀린다
    (실제 CDN에는 없는 가짜 병목 — 동기화 검증을 오염시킴).
    """
    server = http.server.ThreadingHTTPServer(("0.0.0.0", port), CORSRequestHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"[HTTP] HLS 서버 시작: http://localhost:{port}/playlist.m3u8")
    return server


def start_ffmpeg(
    mp4_url: str,
    hls_time: int,
    ffmpeg_bin: str = "ffmpeg",
    with_video: bool = False,
    list_size: int = 12,
    seek: int = 0,
) -> subprocess.Popen:
    """ffmpeg 서브프로세스 시작: MP4 → HLS 변환

    with_video=True면 비디오 스트림을 그대로 복사(h264 가정)해 /live 플레이어로
    영상-자막 동기화를 눈으로 검증할 수 있다. 기본은 오디오 전용(STT 테스트).
    list_size 기본 12 (4초 세그먼트 × 12 = 48초 윈도우) — 플레이어가 자막 동기화용
    깊은 라이브 지연(~28초)을 잡을 수 있도록 충분히 길게 유지한다.
    """
    # 이전 실행 잔재 제거 — append_list 플래그가 낡은 플레이리스트에 이어붙여
    # 시퀀스가 뒤섞이는 것을 방지 (정상 종료 못 한 경우 대비)
    cleanup()
    HLS_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    cmd = [ffmpeg_bin]
    if seek > 0:
        cmd += ["-ss", str(seek)]   # 시작 오프셋 (회의 초반 무음 스킵용)
    cmd += [
        "-re",                      # 실시간 속도 시뮬레이션
        "-i", mp4_url,              # 입력 MP4 (URL 또는 로컬 경로)
    ]
    if with_video:
        cmd += ["-c:v", "copy"]     # 비디오 복사 (재인코딩 없음, KMS MP4는 h264)
    else:
        cmd += ["-vn"]              # 비디오 제거 (오디오만)
    cmd += [
        "-c:a", "aac",              # AAC 코덱
        "-b:a", "128k",             # 비트레이트
        "-ac", "1",                 # 모노
        "-ar", "16000",             # 16kHz
        "-f", "hls",                # HLS 출력
        "-hls_time", str(hls_time), # 세그먼트 길이 (초)
        "-hls_list_size", str(list_size),  # 슬라이딩 윈도우 크기
        "-hls_flags", "delete_segments+append_list",  # 라이브 시뮬레이션
        "-hls_segment_filename", str(HLS_OUTPUT_DIR / "segment_%03d.ts"),
        str(HLS_OUTPUT_DIR / "playlist.m3u8"),
    ]

    print(f"[ffmpeg] 시작: {mp4_url}")
    print(f"[ffmpeg] 세그먼트 길이: {hls_time}초")
    print(f"[ffmpeg] 출력: {HLS_OUTPUT_DIR / 'playlist.m3u8'}")

    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return process


def cleanup():
    """임시 HLS 파일 정리"""
    if HLS_OUTPUT_DIR.exists():
        shutil.rmtree(HLS_OUTPUT_DIR, ignore_errors=True)
        print("[정리] hls_output/ 디렉토리 삭제 완료")


def main():
    parser = argparse.ArgumentParser(
        description="MP4 → HLS 실시간 테스트 스트리밍"
    )
    parser.add_argument(
        "--mp4-url",
        required=True,
        help="MP4 파일 URL 또는 로컬 경로",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8088,
        help="HTTP 서버 포트 (기본값: 8088)",
    )
    parser.add_argument(
        "--hls-time",
        type=int,
        default=4,
        help="HLS 세그먼트 길이 (초, 기본값: 4)",
    )
    parser.add_argument(
        "--with-video",
        action="store_true",
        help="비디오 스트림 포함 (영상-자막 동기화 검증용, h264 복사)",
    )
    parser.add_argument(
        "--list-size",
        type=int,
        default=12,
        help="플레이리스트 슬라이딩 윈도우 세그먼트 수 (기본값: 12 = 48초)",
    )
    parser.add_argument(
        "--seek",
        type=int,
        default=0,
        help="입력 시작 오프셋 초 (회의 초반 무음 스킵, 기본값: 0)",
    )
    args = parser.parse_args()

    # ffmpeg 설치 확인 (PATH 또는 well-known 경로)
    ffmpeg_bin = shutil.which("ffmpeg")
    if ffmpeg_bin is None:
        # well-known 경로 탐색
        for candidate in [
            r"C:\ffmpeg\ffmpeg-8.0.1-essentials_build\bin\ffmpeg.exe",
            r"C:\ffmpeg\bin\ffmpeg.exe",
            r"C:\Program Files\FFmpeg\bin\ffmpeg.exe",
        ]:
            if os.path.isfile(candidate):
                ffmpeg_bin = candidate
                break
    if ffmpeg_bin is None:
        print("오류: ffmpeg가 설치되어 있지 않습니다.")
        print("  Windows: choco install ffmpeg  또는  scoop install ffmpeg")
        sys.exit(1)
    print(f"[ffmpeg] 바이너리: {ffmpeg_bin}")

    ffmpeg_proc = None
    http_server = None

    def signal_handler(signum, frame):
        print("\n[종료] Ctrl+C 감지, 정리 중...")
        if ffmpeg_proc and ffmpeg_proc.poll() is None:
            ffmpeg_proc.kill()
            ffmpeg_proc.wait()
        if http_server:
            http_server.shutdown()
        cleanup()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        # 1. HTTP 서버 시작
        http_server = start_http_server(args.port)

        # 2. ffmpeg 시작
        ffmpeg_proc = start_ffmpeg(
            args.mp4_url,
            args.hls_time,
            ffmpeg_bin,
            with_video=args.with_video,
            list_size=args.list_size,
            seek=args.seek,
        )

        print(f"\n{'='*50}")
        print(f"HLS 테스트 스트림 준비 완료!")
        print(f"  URL: http://localhost:{args.port}/playlist.m3u8")
        print(f"  종료: Ctrl+C")
        print(f"{'='*50}\n")

        # ffmpeg stderr 모니터링 (별도 스레드)
        def monitor_ffmpeg():
            for line in ffmpeg_proc.stderr:
                decoded = line.decode("utf-8", errors="replace").strip()
                if decoded:
                    sys.stderr.write(f"[ffmpeg] {decoded}\n")

        monitor_thread = threading.Thread(target=monitor_ffmpeg, daemon=True)
        monitor_thread.start()

        # ffmpeg 종료 대기
        ffmpeg_proc.wait()
        print("\n[ffmpeg] 변환 완료 (MP4 끝까지 재생됨)")
        print("[대기] HTTP 서버 유지 중... Ctrl+C로 종료")

        # ffmpeg 끝나도 서버는 유지 (마지막 세그먼트 접근 가능)
        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        signal_handler(None, None)
    finally:
        if ffmpeg_proc and ffmpeg_proc.poll() is None:
            ffmpeg_proc.kill()
        if http_server:
            http_server.shutdown()
        cleanup()


if __name__ == "__main__":
    main()
