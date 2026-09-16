"""무거운 하위 프로세스를 생중계 STT 뒤로 보내는 명령 접두어.

생중계 STT(ffmpeg 디코드)·클립 추출·VOD AI 자막 생성이 **같은 파드(CPU 한도 2코어)** 에서 돈다.
경합이 생기면 생중계 자막이 먼저다 — CPU(nice 19)·디스크(ionice idle) 둘 다 뒤로 보낸다.
클립 추출(2026-09-08)에 먼저 붙였고, VOD 등록 직후 AI 자막을 낮에 자동으로 만들게 되면서
(2026-09-10) VOD 쪽 ffmpeg·화자 임베딩 워커에도 같은 값을 쓴다.

    asyncio.create_subprocess_exec(*LOW_PRIORITY, "ffmpeg", ...)
"""

LOW_PRIORITY = ["nice", "-n", "19", "ionice", "-c", "3"]
