"""FastAPI 애플리케이션 진입점"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager

import httpx

# 애플리케이션 로거 설정 (uvicorn 기본 로깅에 app.* 포함)
logging.basicConfig(level=logging.INFO, format="%(levelname)s:     %(name)s - %(message)s")

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.ai import router as ai_router
from app.api.final_transcript import router as final_transcript_router
from app.api.auth import router as auth_router
from app.api.qr_login import router as qr_login_router
from app.api.sso_login import router as sso_login_router
from app.api.admin import router as admin_router
from app.api.agenda_files import router as agenda_files_router
from app.api.bills import router as bills_router
from app.api.dictionary import router as dictionary_router
from app.api.channels import router as channels_router
from app.api.clips import router as clips_router
from app.api.councilors import router as councilors_router
from app.api.collaborative import router as collaborative_router
from app.api.exports import router as exports_router
from app.api.material_requests import router as material_requests_router
from app.api.meetings import router as meetings_router
from app.api.meeting_documents import router as meeting_documents_router
from app.api.minutes import router as minutes_router
from app.api.notifications import router as notifications_router
from app.api.schedule import router as schedule_router
from app.api.search import router as search_router
from app.api.speakers import router as speakers_router
from app.api.stats import router as stats_router
from app.api.stenography import dashboard_router as stenography_dashboard_router
from app.api.stenography import router as stenography_router
from app.api.subtitles import router as subtitles_router
from app.api.tools import router as tools_router
from app.api.voiceprints import router as voiceprints_router
from app.api.websocket import router as websocket_router
from app.core.config import settings
from app.services.auto_stt import get_auto_stt_manager
from app.services.diarize_service import diarize_service
from app.services.live_corrector import live_corrector

logger = logging.getLogger(__name__)


async def _self_ping() -> None:
    """상시 호스트 keepalive용 자기 자신 헬스체크 (idle sleep/reclaim 방지)."""
    port = os.environ.get("PORT", "8000")
    url = f"http://0.0.0.0:{port}/health"
    async with httpx.AsyncClient() as client:
        while True:
            await asyncio.sleep(300)  # 5분
            try:
                await client.get(url, timeout=10)
                logger.debug("Self-ping OK")
            except Exception as e:
                logger.warning("Self-ping failed: %s", e)


# 기동 뒤 첫 등록까지 — 예전엔 한 주기를 통째로 기다려 배포·06시 전원 켜짐 뒤 60분 동안
# 아무것도 안 봤다(2026-09-10). 3분이면 배포 검증(40)이 끝나고 파드가 자리를 잡는다.
_KMS_FIRST_RUN_DELAY_SEC = 180


def _vod_auto_stt_active() -> bool:
    """VOD 등록 직후 AI 자막 자동 생성이 켜져 있는가 — OpenAI 키가 없으면 생성이 불가하다."""
    return bool(settings.vod_auto_stt_enabled and settings.openai_api_key)


async def _kms_auto_register_loop() -> None:
    """KMS 최근회의영상 자동 등록 루프 — 의회 홈페이지와의 실질적 '연동'.

    방송 직후에는 KMS 측 MP4 변환이 몇 시간 걸려 수동 [VOD 일괄 등록]을 기억해
    눌러야 했다(2026-07-07 제392회 1차 본회의 실측). 주기적으로 등록만(regenerate 없음,
    AI 비용 0) 재시도해 변환이 끝나는 대로 새 회기 영상이 자동으로 목록에 나타난다.

    한 바퀴 끝날 때마다 AI 자막 자동 생성을 찔러 본다(`vod_auto_stt.kick`, 2026-09-10 사용자 결정
    "VOD 가 등록되면 바로") — 생성은 백그라운드라 이 루프는 막히지 않고, 배치가 돌고 있으면 다음 주기에 본다.
    """
    from app.core.database import get_supabase_client

    interval = max(10, settings.kms_auto_register_interval_minutes) * 60
    delay = _KMS_FIRST_RUN_DELAY_SEC
    while True:
        await asyncio.sleep(delay)
        delay = interval
        try:
            from app.services.kms_bulk_matcher import match_and_update

            result = await match_and_update(
                get_supabase_client(), regenerate_subtitles=False, pages=2
            )
            created = len(result.get("created") or [])
            matched = len(result.get("matched") or [])
            if created or matched:
                logger.info(
                    "KMS 자동 등록: 신규 %d건, 기존 매칭 %d건", created, matched
                )
        except Exception as e:
            logger.warning("KMS 자동 등록 실패 (다음 주기에 재시도): %s", e)
        # 등록이 실패해도 찔러 본다 — 지난 주기에 붙었는데 배치가 돌고 있어 못 잡은 회의가 있을 수 있다
        if _vod_auto_stt_active():
            try:
                from app.services.vod_auto_stt import kick

                kick(get_supabase_client)
            except Exception as e:
                logger.warning("AI 자막 자동 생성 시작 실패 (다음 주기에 재시도): %s", e)


async def _summary_pregen_loop() -> None:
    """요약 미리 만들기 루프(2026-09-15 담당자 결정) — AI 자막이 끝난 회의를 골라 요약해 둔다.

    대상 선별·하루 상한·실패 1회 규칙은 services/summary_pregen. 첫 바퀴는 기동 3분 뒤(배포 검증 40 이 끝난 뒤).
    """
    from app.core.database import get_supabase_client
    from app.services.summary_pregen import run_once

    interval = max(5, settings.summary_pregen_interval_minutes) * 60
    delay = _KMS_FIRST_RUN_DELAY_SEC
    while True:
        await asyncio.sleep(delay)
        delay = interval
        try:
            result = await run_once(get_supabase_client())
            if result["made"] or result["failed"]:
                logger.info(
                    "요약 미리 만들기: 완료 %d건, 실패 %d건, 상한으로 미룸 %d건",
                    len(result["made"]), len(result["failed"]), result["skipped_limit"],
                )
        except Exception as e:
            logger.warning("요약 미리 만들기 실패 (다음 주기에 재시도): %s", e)


async def _embed_pregen_loop() -> None:
    """자막 조각 임베딩 채우기 루프(2026-09-15) — AI 대화의 뜻으로 찾기용. 규칙은 services/embedding_pregen."""
    from app.core.database import get_supabase_client
    from app.services.embedding_pregen import run_once

    interval = max(5, settings.embed_pregen_interval_minutes) * 60
    delay = _KMS_FIRST_RUN_DELAY_SEC
    while True:
        await asyncio.sleep(delay)
        delay = interval
        try:
            result = await run_once(get_supabase_client())
            if result["indexed"] or result["failed"]:
                logger.info("조각 임베딩: 완료 %d건, 실패 %d건", len(result["indexed"]), len(result["failed"]))
        except Exception as e:
            logger.warning("조각 임베딩 루프 실패 (다음 주기에 재시도): %s", e)


async def _assembly_schedule_loop() -> None:
    """의사일정 수집 루프 — 의회 홈페이지 의정캘린더를 주기적으로 다시 맞춘다.

    ★한 번 긁고 끝내면 안 된다. **안건은 회기 중 수시로 바뀐다**(사용자 요구, 2026-08-31).
      매 주기마다 다시 받아, 내용이 같으면 '확인 시각'만, 달라졌으면 '변경 시각'까지
      갱신한다. 달력에서 사라진 회의는 지우지 않고 취소로 표시한다.
    기동 직후 1회 먼저 돌린다 — 재시작하자마자 화면이 비어 있으면 안 된다.
    """
    from app.services.assembly_schedule_sync import sync as sync_schedule

    interval = max(5, settings.assembly_schedule_sync_interval_minutes) * 60
    days = settings.assembly_schedule_days_ahead
    first = True
    while True:
        if not first:
            await asyncio.sleep(interval)
        first = False
        try:
            stat = await sync_schedule(days_ahead=days)
            if stat.get("added") or stat.get("changed") or stat.get("cancelled"):
                logger.info(
                    "의사일정 동기화: 신규 %d · 변경 %d · 취소 %d · 그대로 %d",
                    stat.get("added", 0),
                    stat.get("changed", 0),
                    stat.get("cancelled", 0),
                    stat.get("unchanged", 0),
                )
        except Exception as e:
            logger.warning("의사일정 동기화 실패 (다음 주기에 재시도): %s", e)


async def _recording_prune_loop() -> None:
    """녹음·접속기록 보존기간 정리 루프(일 1회) — live_recorder 의 prune 을 재사용한다."""
    from app.core.database import get_supabase_client
    from app.services.access_stats_service import purge_old
    from app.services.live_recorder import _prune_old_recordings

    while True:
        await asyncio.sleep(86400)
        try:
            await asyncio.to_thread(_prune_old_recordings)
        except Exception as e:
            logger.warning("녹음 보존기간 정리 실패 (다음 주기에 재시도): %s", e)
        try:
            # 접속 기록 보존 180일 (2026-09-16). 표가 없으면 서비스가 조용히 넘긴다
            await asyncio.to_thread(purge_old, get_supabase_client())
        except Exception as e:
            logger.warning("접속 기록 정리 실패 (다음 주기에 재시도): %s", e)



async def _clip_store_sweep_loop() -> None:
    """클립 저장소 정리 루프 — 보존 7일 + 바이트 상한(오래된 것부터). 기동 직후 1회, 이후 주기."""
    from app.core.database import get_supabase_client
    from app.repositories.clip_job_repository import ClipJobRepository
    from app.services.clip_job_service import sweep_store

    interval = max(5, settings.clip_store_sweep_interval_minutes) * 60
    first = True
    while True:
        if not first:
            await asyncio.sleep(interval)
        first = False
        try:
            stat = await asyncio.to_thread(sweep_store, ClipJobRepository(get_supabase_client()))
            if stat["evicted"] or stat["orphans"]:
                logger.info("클립 저장소 정리: %d건 %.1fMB 회수 · 고아 %d (사용 %.2f/%.2fGB)",
                            len(stat["evicted"]),
                            sum(e["bytes"] for e in stat["evicted"]) / 1024**2,
                            len(stat["orphans"]),
                            stat["used_bytes"] / 1024**3, stat["max_bytes"] / 1024**3)
        except Exception as e:
            logger.warning("클립 저장소 정리 실패 (다음 주기에 재시도): %s", e)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """애플리케이션 수명주기 관리 (startup/shutdown)."""
    # --- Startup ---
    # JWT 시크릿 키 검증 (하드코딩 폴백 사용 경고)
    from app.core.config import settings as _cfg
    if not _cfg.jwt_secret_key:
        raise RuntimeError(
            "JWT_SECRET_KEY 가 비어 있습니다. 토큰 위조를 막기 위해 기동을 중단합니다. "
            "`openssl rand -hex 32` 로 만들어 환경변수(운영은 k8s Secret)로 주세요."
        )

    # 고아 'processing' 회의 복구 — 재시작으로 죽은 VOD STT가 'AI 자막 생성 중'
    # 상태로 영원히 남는 것 방지 (1회-처리 가드가 영구히 막히는 것도 방지)
    try:
        from app.core.database import get_supabase_client
        from app.services.vod_stt_service import reset_orphaned_processing
        await asyncio.to_thread(reset_orphaned_processing, get_supabase_client())
    except Exception as e:
        logger.warning("고아 processing 복구 스킵: %s", e)

    auto_stt = get_auto_stt_manager()
    await auto_stt.start()

    # 화자 구분(diarize) 경로 — 경로 A(OpenAI Realtime 전사)가 디코딩한 PCM을 받아
    # gpt-4o-transcribe-diarize 배치로 화자 라벨을 비동기로 부여한다.
    await diarize_service.start()

    # 라이브 자막 GPT 사후 교정 — 확정 자막을 글로서리 바이어스로 교정해 정확도 향상 +
    # 프런트 '교정 중'→'교정됨' 전환.
    await live_corrector.start()

    # 상시 호스트(PORT 주입 환경: Docker/OCI/NCP 등)에서 idle sleep 방지용 self-ping
    self_ping_task = None
    if os.environ.get("PORT"):
        self_ping_task = asyncio.create_task(_self_ping(), name="self-ping")
        logger.info("Self-ping task started (PORT=%s)", os.environ.get("PORT"))

    # KMS 최근회의영상 자동 등록 (등록 자체는 AI 비용 0) — 새 회기 영상 자동 유입.
    # 한 바퀴마다 AI 자막 자동 생성을 찔러 본다(상한·기간·검토본 보존 가드는 services/vod_auto_stt).
    kms_auto_task = None
    if settings.kms_auto_register_interval_minutes > 0 and settings.supabase_url:
        kms_auto_task = asyncio.create_task(
            _kms_auto_register_loop(), name="kms-auto-register"
        )
        if _vod_auto_stt_active():
            auto_desc = (
                f"켜짐 — 하루 {settings.vod_auto_stt_daily_limit}건"
                f" · 최근 {settings.vod_auto_stt_max_age_days}일"
            )
        else:
            auto_desc = "꺼짐"
        logger.info(
            "KMS 자동 등록 루프 시작 (주기 %d분, 첫 실행 기동 %d초 뒤) · 등록 직후 AI 자막 자동 생성 %s",
            settings.kms_auto_register_interval_minutes, _KMS_FIRST_RUN_DELAY_SEC, auto_desc,
        )

    # 녹음 보존기간 정리 — 기존 트리거는 '새 녹음 시작 시'뿐이라(new-start piggyback)
    # 방송 없는 연휴에는 정리가 안 돌아 디스크가 찬 채로 진입할 수 있다. 일 1회 보강.
    record_prune_task = None
    if settings.live_record_enabled and settings.live_record_retention_days > 0:
        record_prune_task = asyncio.create_task(
            _recording_prune_loop(), name="recording-prune"
        )

    # 발언영상 클립 워크벤치 — 중단된 잡 복구 + 저장소 정리 루프 (DB 가 있을 때만)
    clip_sweep_task = None
    if settings.supabase_url:
        try:
            from app.core.database import get_supabase_client
            from app.repositories.clip_job_repository import ClipJobRepository
            from app.services.clip_job_service import clip_job_service

            clip_job_service.configure(lambda: ClipJobRepository(get_supabase_client()))
            await clip_job_service.recover_interrupted()
        except Exception as e:
            logger.warning("클립 잡 복구 스킵: %s", e)
        clip_sweep_task = asyncio.create_task(_clip_store_sweep_loop(), name="clip-store-sweep")
    # 의사일정 수집 — 라이브 회의에 회기·차수를 붙이고 '다가오는 일정'을 채운다.
    schedule_task = None
    if settings.assembly_schedule_sync_interval_minutes > 0 and settings.supabase_url:
        schedule_task = asyncio.create_task(
            _assembly_schedule_loop(), name="assembly-schedule-sync"
        )
        logger.info(
            "의사일정 동기화 루프 시작 (주기 %d분, %d일치)",
            settings.assembly_schedule_sync_interval_minutes,
            settings.assembly_schedule_days_ahead,
        )

    # 요약 미리 만들기 — AI 자막이 끝난 회의의 요약을 담당자가 누르기 전에 만들어 둔다(2026-09-15)
    summary_pregen_task = None
    if settings.summary_pregen_enabled and settings.openai_api_key and settings.supabase_url:
        summary_pregen_task = asyncio.create_task(_summary_pregen_loop(), name="summary-pregen")
        logger.info(
            "요약 미리 만들기 루프 시작 (주기 %d분 · 하루 %d건 · 최근 %d일)",
            settings.summary_pregen_interval_minutes, settings.summary_pregen_daily_limit,
            settings.summary_pregen_max_age_days,
        )

    # 자막 조각 임베딩 — AI 대화의 뜻으로 찾기(벡터+키워드 혼합). 생중계 중이면 그 바퀴는 쉰다(2026-09-15)
    embed_pregen_task = None
    if settings.embed_pregen_enabled and settings.openai_api_key and settings.supabase_url:
        embed_pregen_task = asyncio.create_task(_embed_pregen_loop(), name="embed-pregen")
        logger.info("조각 임베딩 루프 시작 (주기 %d분 · 하루 %d건 · 모델 %s)",
                    settings.embed_pregen_interval_minutes, settings.embed_pregen_daily_limit, settings.rag_embedding_model)

    logger.info("Application startup complete (auto_stt enabled=%s)", auto_stt.enabled)

    yield

    # --- Shutdown ---
    for task in (self_ping_task, kms_auto_task, record_prune_task, schedule_task, summary_pregen_task, embed_pregen_task):
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    await auto_stt.stop()

    await diarize_service.stop()

    await live_corrector.stop()

    # 클립 잡: running 을 queued 로 되돌려 재기동 후 이어서 돈다
    if clip_sweep_task and not clip_sweep_task.done():
        clip_sweep_task.cancel()
        try:
            await clip_sweep_task
        except asyncio.CancelledError:
            pass
    try:
        from app.services.clip_job_service import clip_job_service as _cjs
        await _cjs.stop()
    except Exception as e:
        logger.warning("클립 잡 정지 실패(무시): %s", e)

    logger.info("Application shutdown complete")


app = FastAPI(
    title="경기도의회 실시간 자막 서비스",
    description="경기도의회 회의 영상에 실시간/VOD 자막을 제공하는 API",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS 설정 (라우터 등록 전에 추가)
# NOTE: allow_origins=["*"] + allow_credentials=True 조합은 CORS 스펙 위반.
# allow_origin_regex를 사용하면 요청 origin을 그대로 반사하여 credentials와 호환.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_origin_regex=settings.cors_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API 라우터 등록
app.include_router(ai_router)
app.include_router(final_transcript_router)
app.include_router(auth_router)
app.include_router(qr_login_router)
app.include_router(sso_login_router)
app.include_router(admin_router)
app.include_router(agenda_files_router)
app.include_router(bills_router)
app.include_router(dictionary_router)
app.include_router(collaborative_router)
app.include_router(channels_router)
app.include_router(clips_router)
app.include_router(councilors_router)
app.include_router(exports_router)
app.include_router(material_requests_router)
app.include_router(meeting_documents_router)
app.include_router(meetings_router)
app.include_router(minutes_router)
app.include_router(notifications_router)
app.include_router(schedule_router)
app.include_router(search_router, prefix="/api")
app.include_router(speakers_router)
app.include_router(stats_router)
app.include_router(stenography_router)
app.include_router(stenography_dashboard_router)
app.include_router(subtitles_router)
app.include_router(tools_router)
app.include_router(voiceprints_router)
app.include_router(websocket_router)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """미처리 예외를 잡아 CORS 헤더가 포함된 JSON 응답을 반환합니다."""
    logger.error("Unhandled error: %s %s - %s", request.method, request.url.path, exc)
    origin = request.headers.get("origin", "")
    headers: dict[str, str] = {}
    if origin:
        headers["access-control-allow-origin"] = origin
        headers["access-control-allow-credentials"] = "true"
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
        headers=headers,
    )


@app.get("/")
async def root() -> dict[str, str]:
    """루트 엔드포인트 - 서비스 상태 확인"""
    return {"message": "경기도의회 실시간 자막 서비스 API", "status": "running"}


@app.get("/health")
async def health_check() -> dict[str, str]:
    """헬스체크 엔드포인트"""
    return {"status": "healthy"}
