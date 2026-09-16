"""애플리케이션 설정"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """환경변수 기반 설정"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # 배포 환경의 부가 env var(예: 폐기된 키)에 견고하도록 무시
    )

    # 데이터베이스
    database_url: str = "postgresql://localhost:5432/ggc_subtitle"

    # Supabase
    supabase_url: str = ""
    supabase_key: str = ""
    # PostgREST 스키마 프로필. 클라우드 Supabase 는 public, k3s pgrst 브리지는 subtitle.
    # supabase-py 는 모든 요청에 Accept-Profile 헤더를 붙이므로(2.31 실측) 브리지의
    # PGRST_DB_SCHEMAS="subtitle" 와 어긋나면 전 쿼리가 PGRST106(406) 으로 죽는다.
    supabase_schema: str = "public"

    # OpenAI Whisper
    openai_api_key: str = ""

    # OpenAI 모델 (문법 검사, 회의 요약 등 공통)
    openai_model: str = "gpt-5.4-mini"

    # ─── AI 어시스턴트 모델(2026-09-15 담당자 요청 "최신·저렴·효과적") ───────────────────────────────
    # 대화는 openai_model 에서 뗐다 — openai_model 은 화자 식별·속기·영상 회의록·VOD 자막 등 7곳이 같이 써서
    # 대화 모델을 바꾸려다 대량 처리 기능까지 바뀌면 안 된다.
    # 추론 수준(reasoning_effort): 5.6 계열 기본값은 medium 이고 생각 토큰이 출력 상한에 포함된다 — 첫 글자가 늦고
    # 상한이 낮으면 답이 잘린다. 빈 문자열이면 보내지 않는다(옛 모델로 되돌릴 때 호환).
    # 단가(100만 토큰, 입력/출력): 5.4-mini $0.75/$4.50 · 5.6-luna $0.20/$1.20 · 5.6-terra $2/$12 · 5.4 $2.50/$15.
    # 대화는 gpt-5.4-mini 유지 — 2026-09-15 운영 회의 2건 × 질문 3개 비교(스트리밍 측정):
    #   mini(기본)  첫 글자 0.9초 · 전체 7.7초 · 잘림 0  · 6문항 $0.055
    #   luna low    첫 글자 1.9초 · 전체 22.4초 · 잘림 2 · $0.018   (답이 길어 3,000 토큰 상한에 걸림)
    #   terra low   첫 글자 1.6초 · 전체 17.8초 · 잘림 1 · $0.179
    # 사실관계는 셋이 비슷했다. 5.6 계열은 답이 1.4배 길고 느려 "속도" 요청과 반대라 채택하지 않았다.
    # mini 는 추론 수준을 안 보내면 생각 토큰 0 이다(실측) — 그래서 빈 값으로 둔다.
    ai_chat_model: str = "gpt-5.4-mini"
    ai_chat_reasoning_effort: str = ""
    # 옛 상한 1,500 은 "안건별로 정리" 같은 긴 답(실측 1,948 토큰)을 자를 수 있었다
    ai_chat_max_tokens: int = 3000
    # 에이전트형 대화(2026-09-15) — 첫 발췌로 모자라면 AI 가 도구로 자막을 더 찾아 읽는다(services/ai_agent). 코드 기본값 꺼짐, 운영은 k8s env.
    ai_agent_enabled: bool = False
    ai_agent_max_rounds: int = 3
    ai_agent_timeout_sec: float = 75.0
    # 요약: 2026-09-14 gpt-5.5 → gpt-5.4-mini("저렴하면서 성능 좋은 것") → 2026-09-15 gpt-5.6-luna(구간·병합 모두 low).
    # 운영 회의 2건 전체 요약 비교(7구간 57,005자 / 16구간 132,205자, 잘림·JSON 실패 0):
    #   mini·동시4   22.5초 $0.064 / 41.3초 $0.171   ← 이전
    #   mini·동시16  14.8초 $0.052 / 17.0초 $0.119   (가장 빠르나 "119안전센터 매입 예산 감액" 같은 결정을 빠뜨리고 "정회 후 재개"를 결정으로 넣음)
    #   luna low     25.5초 $0.016 / 31.3초 $0.036   ← 채택: 결정·후속조치를 가장 정확히, 비용 약 1/4~1/5
    #   luna 병합 medium 39.8초 / 45.8초 (병합이 느려짐) · terra low 28.6초 $0.235 / 31.6초 $0.525(품질 최고, 비용 3~4배)
    summary_model: str = "gpt-5.6-luna"
    summary_map_model: str = "gpt-5.6-luna"
    summary_reasoning_effort: str = "low"
    summary_map_reasoning_effort: str = "low"
    # 단일 호출로 요약하는 자막 상한(문자). 넘으면 안건·화자 경계로 청크를 나눠 맵리듀스(summary_service)
    summary_single_call_max_chars: int = 12000
    summary_chunk_chars: int = 9000
    # 구간 요약 동시 호출 수 — 4 면 16구간 회의가 4번 줄을 섰다(2026-09-15). 이 키의 한도는 분당 1만 요청·1천만 토큰
    # (응답 헤더 x-ratelimit-limit-*) 이라 16구간을 한 번에 보내도 429 없이 끝났다.
    summary_map_concurrency: int = 16
    # 출력 토큰 상한 — 추론 모델은 생각 토큰까지 여기 포함된다. 1,200 이면 청크 JSON 이 잘린다(2026-09-14 실측)
    summary_map_max_tokens: int = 4000
    summary_max_tokens: int = 8000
    # 하루 요약 생성 상한(KST, 캐시 적중은 차감 없음). 요약 라우트·안건 초안이 같은 카운터를 쓴다
    ai_summary_daily_limit: int = 20
    # 안건 추출: gpt-5.4 → gpt-5.6-luna low (2026-09-15, 의회운영위 15건·안전행정위 2건 모두 같은 목록, 비용 1/12, 4.5→6.9초)
    agenda_model: str = "gpt-5.6-luna"
    agenda_reasoning_effort: str = "low"
    # ─── 요약 미리 만들기(2026-09-15 담당자 결정) — AI 자막이 끝난 회의를 api 파드가 주기적으로 요약해 둔다 ───
    # 담당자가 누르는 요약 한도(ai_summary_daily_limit)와 따로 센다. 코드 기본값은 꺼짐, 운영은 k8s env 로 켠다.
    summary_pregen_enabled: bool = False
    summary_pregen_interval_minutes: int = 10
    summary_pregen_daily_limit: int = 10
    summary_pregen_max_age_days: int = 30
    # 자막 단계가 바뀐 뒤 이만큼 지난 회의만 — 업로드·재생성 경로는 단계를 먼저 바꾸고 문법 교정을 뒤에 돌린다
    summary_pregen_settle_minutes: int = 15
    # ─── 부서별 문서(모니터링·자료요구 목록·요구자료 표지·보도자료, 2026-09-15) — 버튼으로만 만든다 ───
    # HWPX 는 문서 엔진(ggc_doc /generate)으로. 비어 있으면 문서 만들기가 503.
    ggc_doc_internal_url: str = ""
    ggc_doc_token: str = ""
    # 모니터링·보도자료처럼 AI 로 뽑는 문서의 하루 생성 상한(KST) — 같은 회의를 부서만 바꿔 받는 것은 캐시라 차감 없음
    doc_extract_daily_limit: int = 30
    # ─── 뜻으로 찾기(벡터+키워드 혼합 검색, 2026-09-15 담당자 요청 "회의 내용을 벡터화") ─────────────────
    # 자막 조각 임베딩(migration 036 subtitle_chunks) — 질문 낱말이 자막에 그대로 없어도 뜻이 가까운 구간을 찾는다.
    # 운영 회의 시험: "휴대폰으로 쓰는 공무원 신분증 얘기" → 상위 3조각 모두 04:27~04:31 모바일 공무원증 구간(유사도 0.45~0.51),
    # 무관한 질문의 최고점은 0.34 — 그래서 문턱 0.40·최고점과의 폭 0.06. 코드 기본값은 꺼짐, 운영은 k8s env 로 켠다.
    rag_vector_enabled: bool = False
    rag_embedding_model: str = "text-embedding-3-large"   # dimensions=1536 로 줄여 받는다(pgvector 0.6.0 HNSW 상한 안)
    rag_vector_k: int = 12
    rag_vector_min_sim: float = 0.40
    rag_vector_band: float = 0.06
    # 조각 임베딩 채우기 — 끝난 회의를 10분마다 골라(생중계 중이면 그 바퀴는 쉰다) 바뀐 조각만 다시 임베딩
    embed_pregen_enabled: bool = False
    embed_pregen_interval_minutes: int = 10
    embed_pregen_daily_limit: int = 40
    embed_pregen_settle_minutes: int = 15
    # 요구자료 감지 (의원 자료 제출 요구 자동 목록화) — 정규식 프리필터 + 미니 모델로 저비용 유지
    material_request_model: str = "gpt-5.4-mini"
    material_request_enabled: bool = True
    # KMS VOD 일괄 등록 관리 시작 회기 — 이 회기 이후(≥)만 신규 등록 (과거 회기 무더기 등록 방지).
    # 392·393·394처럼 여러 회기가 동시 진행돼도 하한만 넘으면 전부 등록된다.
    kms_min_session_no: int = 391
    # KMS 자동 등록 주기(분) — 등록 자체는 AI 비용 0. 0이면 비활성(→ AI 자막 자동 생성도 멈춘다).
    # 방송 직후 MP4 변환(수 시간)이 끝나는 대로 새 영상이 자동으로 목록에 나타난다.
    # 60 → 30 (2026-09-10 사용자 결정) — 등록되자마자 AI 자막 생성이 이어지므로 주기가 곧 대기 시간이다.
    kms_auto_register_interval_minutes: int = 30
    # ─── VOD 등록 직후 AI 자막 자동 생성 (2026-09-03 새벽 1회 → 2026-09-10 등록 직후) ───────
    # 2026-06-12 에는 "등록은 자동, AI 자막은 관리자가 버튼으로" 였다(비용 폭증 사고 뒤).
    # 09-03 에 "상한부 자동(매일 새벽 1회)" 으로, 09-10 에 "VOD 가 등록되면 바로" 로 바꿨다 —
    # 새벽 1회라 아침에 붙은 VOD 가 다음 날까지 22시간 기다렸다. 등록 루프가 한 바퀴 돌 때마다
    # services/vod_auto_stt.kick 이 생성한다. 하루 상한·최근 N일·속기 검토본 보존이 그 가드다.
    # 회의당 약 $0.4·10분. 상한 10건 = 하루 최대 $4, 월 최대 $120 — OpenAI 월 하드리밋 안에 든다.
    vod_auto_stt_enabled: bool = True
    # 하루(KST) 최대 생성 건수 — 넘치는 회의는 다음 날로 밀린다(max_age_days 안이면 잡힌다).
    vod_auto_stt_daily_limit: int = 10
    # 최근 며칠 회의만 대상으로 할지 — 과거 회기 무더기 생성 방지.
    vod_auto_stt_max_age_days: int = 3
    # 의사일정 수집 주기(분) — 의회 홈페이지 의정캘린더. 0이면 비활성.
    # ★안건은 회기 중 수시로 바뀌므로 한 번 긁고 끝내지 않고 계속 다시 맞춘다.
    #   30분이면 회의 시작 전에 반영된다(회의는 통상 정시 시작).
    assembly_schedule_sync_interval_minutes: int = 30
    # 의사일정을 며칠 앞까지 볼지 — 대시보드 '다가오는 일정'과 같은 값
    assembly_schedule_days_ahead: int = 7
    # 로그인 없는 공개 AI 대화 비용 보호 — IP당 하루 최대 호출 수
    ai_chat_daily_limit: int = 10
    # 의회망은 NAT 뒤라 건물 전체가 IP 몇 개를 나눠 쓴다 — 같은 10회면 아침에 바닥난다(2026-09-11)
    ai_chat_daily_limit_council: int = 300
    # 로그인 사용자별 하루 대화 상한(IP 상한과 별개로 둘 다 적용). 일자 경계는 KST(2026-09-14)
    ai_chat_daily_limit_user: int = 100
    # 의회망 대역 — 이 대역의 비로그인 방문자에게 발언영상·AI 를 연다(core/council_network.py).
    # 값은 저장소에 두지 않는다: 클러스터 ConfigMap ggc-live-transcribe-council 이 env 로 넣는다. 비면 꺼진다.
    council_network_ranges: str = ""
    # 로그인을 요구할 대역 — 이 대역에서 온 비로그인 방문자에게는 서비스 대신
    # "모바일 의정지원서비스 앱으로 로그인하세요" 안내를 띄운다(2026-09-16 담당자 결정,
    # 그 전에는 Traefik 이 아예 차단했다). 값은 같은 ConfigMap 의 키 LOGIN_REQUIRED_RANGES.
    # 비면 아무에게도 요구하지 않는다(안전한 쪽으로 꺼진다).
    login_required_ranges: str = ""
    # 앱 설치 안내 주소 — 안내 화면과 로그인 화면이 함께 보여준다
    app_install_guide_url: str = "https://ggc-install-video.vercel.app/"
    # 접속처 이름표 — 접속 통계가 IP 를 이름으로 바꿀 때만 쓴다(core/council_network.site_label).
    # 같은 ConfigMap 의 키 COUNCIL_SITE_LABELS. 표기: "이름=대역,대역; 이름=대역".
    # 비면 모든 접속이 '외부' 로 집계된다(기능은 죽지 않는다). IP 원문은 어디에도 저장하지 않는다.
    council_site_labels: str = ""

    # ─── STT 엔진 (Phase 12: OpenAI 전면 교체, Deepgram 완전 제거) ───────────
    # 라이브: OpenAI Realtime 전사 + diarize 듀얼 파이프라인. VOD: gpt-4o-transcribe-diarize 배치.
    stt_engine: str = "openai"

    # STT 도메인 프롬프트 (services/stt_prompt.py — 의회 장면 설명 + 위원회 명부 + 용어 힌트).
    # ★879de6b 에서 추가됐다가 스쿼시 병합 0834ac8 에서 유실됐던 두 필드를 2026-09-03 복구.
    #   없는 동안 build_stt_prompt() 가 AttributeError 로 죽어 tests/services/test_stt_prompt.py
    #   8건이 실패했고, 운영 라이브 배치 경로는 glossary_service.format_glossary_prompt 를
    #   써서 영향이 없었다(그래서 아무도 몰랐다).
    stt_domain_prompt_enabled: bool = True
    stt_domain_prompt_max_chars: int = 500

    # ─── 라이브 STT 모드 선택 (비용·정확도 최적화) ─────────────────────────
    # "batch"    = 배치 윈도우 전사 (기본, 권장): N초 오디오를 모아
    #              /v1/audio/transcriptions(gpt-4o-transcribe)로 전사.
    #              · 비용 ≈ $0.006/오디오분 (~$0.36/시간/채널) — Realtime WS 대비 ~1/10
    #              · 정확도: 15초 문맥(Realtime 3초 commit 대비) + 글로서리 prompt 바이어스
    #              · 무음(정회) 윈도우는 API 호출 자체를 생략 → 비용 0
    #              · 지연 ≈ 윈도우(15초) + API(2~5초) — 허용 범위(10~20초) 내
    # "realtime" = OpenAI Realtime WS 스트리밍(이전 방식): 저지연·고비용,
    #              gpt-realtime-whisper는 prompt 미지원이라 글로서리 바이어스 불가.
    live_stt_mode: str = "batch"
    # 배치 전사 모델. 정확도 우선 gpt-4o-transcribe($0.006/분).
    # 더 저렴하게는 "gpt-4o-mini-transcribe"($0.003/분, 정확도 다소 낮음).
    live_batch_model: str = "gpt-4o-transcribe"
    # 최대 전사 윈도우(초) — 연속 발화 시 이 길이에서 강제 분절(조용한 지점 컷).
    # ★정확도 최우선(사용자 확정): 문맥이 길수록 정확. 영상 자체가 HLS 지연으로
    #   ~15초 늦게 재생되므로 자막 생성이 다소 늦어도 체감 문제 없음
    #   (프런트 표시 지연과 합쳐 자막이 영상을 살짝 뒤따르게 조정).
    live_batch_window_seconds: float = 12.0
    # 발화 멈춤(pause) 조기 flush: 버퍼 꼬리가 이 길이(초)만큼 무음이면 윈도우를
    # 기다리지 않고 즉시 전사한다 → 문장 경계 분절(절단 누락↓).
    live_batch_pause_flush_seconds: float = 0.6
    # 조기 flush 최소 버퍼 길이(초) — 너무 잘게 쪼개면 문맥 부족으로 정확도가
    # 떨어지고(파편 자막) 프롬프트 에코 중복도 늘어난다.
    live_batch_min_flush_seconds: float = 6.0
    # 무음 스킵 임계값(int16 RMS, 0~32767). 윈도우 안에 이 값 이상의 0.3초 블록이
    # 하나도 없을 때만 무음으로 보고 API 호출을 생략한다 — 평균 RMS 방식과 달리
    # 긴 무음에 묻힌 짧은 발언이 버려지지 않는다(누락 방지).
    live_batch_silence_rms: int = 250
    # 직전 윈도우 전사 꼬리를 prompt 문맥으로 이어붙일 최대 길이(자) — 경계 문맥 보강.
    live_batch_context_chars: int = 200
    # /live 영상 지연 목표(초, 라이브 엣지 기준). 프런트가 채널 상태 응답(sync_target_sec)으로 받아
    # hls.js liveSyncDuration 에 쓴다 — 재빌드 없이 env 로 조정한다(2026-09-14, 이전엔 웹 이미지에 구워져 있었다).
    # 근거 = ceil(sync_need_p99 + 1), sync_need = ready_lag + edge_lag (창마다 계측 — stt_status ·
    # GET /api/channels/{id}/stt/status). 8~60 으로 클램프. 값 변경은 파드 재시작(=STT 재시작)이라
    # 생중계 중엔 바꾸지 않는다. 매니페스트 값이 정본(k8s/ggc-live-transcribe.yaml LIVE_SYNC_TARGET_SEC).
    live_sync_target_sec: int = 20

    # 동시 STT 채널 상한 (비용 가드) — 초과 채널은 자동 STT 시작을 건너뛴다.
    # 배치 모드 기준 채널당 ~$0.4/시간. 상한 14 = 13개 상임위 전체 + 본회의 동시 커버
    # (최악 ~$5.6/시간, 전 상임위 동시 개회일에만 발생).
    # ★8이던 시절(2026-07-21): 12개 상임위 동시 방송에서 시청자 최다 채널(안행위 50명)이
    #   정회 후 속개될 때 슬롯을 시청자 0명 채널에 뺏겨 자막이 안 나오는 사고 발생 → 상향.
    stt_max_concurrent_channels: int = 14

    # 라이브 오디오 MP3 녹음 (자막 정확도 검증용) — API 비용 0, 로컬 디스크만 사용.
    # 48kbps 기준 시간당 약 21MB. 다운로드: GET /api/meetings/{id}/recording
    live_record_enabled: bool = True
    live_record_bitrate: str = "48k"
    # 상대 경로는 백엔드 루트 기준으로 고정된다 (기동 위치 무관).
    live_record_dir: str = "recordings"
    # 녹음 보존 기간(일) — 초과분은 새 녹음 시작 시 자동 삭제. 0 이하 = 무제한.
    live_record_retention_days: int = 14

    # 경로 A — OpenAI Realtime 실시간 전사 (WebSocket transcription session)
    # HLS TS를 ffmpeg로 24kHz mono PCM16으로 디코딩 → Realtime WS로 스트리밍 → interim/final 자막.
    #
    # ★모델 주의(검증 완료): gpt-realtime-2 는 speech-to-speech 대화 모델이라 transcription에 쓸 수 없다.
    #   스트리밍 전사 전용 최신 모델은 "gpt-realtime-whisper" 이다. (대안: "gpt-4o-transcribe" — server_vad 자동 분절 지원)
    # ★계약(검증 완료): WS URL ?intent=transcription, 헤더는 Authorization Bearer만(OpenAI-Beta 금지),
    #   session.update {session:{type:"transcription", audio:{input:{format:{type:"audio/pcm",rate:24000},
    #   transcription:{model,language}, turn_detection}}}}, 이벤트 delta/completed.
    openai_realtime_stt_enabled: bool = True
    openai_realtime_stt_model: str = "gpt-realtime-whisper"
    openai_realtime_ws_url: str = "wss://api.openai.com/v1/realtime?intent=transcription"
    # Realtime API 입력 오디오 샘플레이트 (PCM16 mono). API는 24kHz만 지원.
    openai_realtime_audio_rate: int = 24000
    # WS로 보낼 PCM 청크 길이(초). 너무 작으면 메시지 폭주, 너무 크면 지연 증가.
    openai_realtime_chunk_seconds: float = 0.2
    # 분절 방식: "none" = turn_detection:null + 주기적 수동 commit (whisper 필수, 모든 모델 호환).
    #           "server_vad" = 서버 자동 분절 (gpt-4o-transcribe 계열에서만 유효, 수동 commit 불필요).
    openai_realtime_turn_detection: str = "none"
    # turn_detection="none"일 때 수동 commit 주기(초) — 자막 분절 단위.
    openai_realtime_commit_seconds: float = 3.0

    # 경로 B — OpenAI 화자 구분 (gpt-4o-transcribe-diarize 배치)
    # 같은 오디오를 롤링 청크로 모아 diarize 배치 호출 → segments[].speaker → 자막에 "화자 N" 부여.
    # 실패해도 경로 A 자막은 그대로 유지(무해).
    # ★단일 패스(비용 절감) 모드: 화자구분은 별도 전사 호출이라 비용이 크다. OFF.
    #   화자 라벨이 필요하면 True로 되돌리면 됨.
    diarize_enabled: bool = False
    diarize_model: str = "gpt-4o-transcribe-diarize"
    # ★VOD AI 자막 전사 엔진 (2026-06-16):
    #   False(기본) = gpt-4o-transcribe (실시간과 동일, 정확도 높음, 화자구분 없음)
    #   True        = gpt-4o-transcribe-diarize (화자구분, 전사 정확도 다소 낮음)
    #   diarize가 짧은 응답을 영어로 환각(yeah/okay)하고 전사 품질이 낮아,
    #   정확도+이름 우선 시 transcribe 단독이 낫다. 비용은 동일 단가($0.006/분).
    vod_use_diarization: bool = False
    # ★VOD 전사 엔진 whisper-1 (2026-06-16, 기본 ON):
    #   gpt-4o-transcribe는 정확하지만 '타임스탬프를 안 줘서' 글자수 비례로 추정 →
    #   영상-자막 시간이 어긋났다(사용자 지적). whisper-1(verbose_json)은 세그먼트별
    #   '실제 시각'을 주고 한국어 정확도도 동급($0.006/분 동일) → 동기화+정확도 동시 해결.
    #   세그먼트가 곧 자연 문장이라 글자수비례 분리도 불필요. False면 gpt-4o-transcribe.
    vod_use_whisper: bool = True
    # ★VOD 2-패스 화자구분 (2026-06-16):
    #   True(기본) = 본문은 gpt-4o-transcribe(정확)로 두고, 같은 청크를
    #   gpt-4o-transcribe-diarize로 한 번 더 처리해 '화자 라벨만' 시간겹침으로
    #   덧입힌다(텍스트는 안 건드림). diarize의 낮은 전사품질·영어환각 문제를
    #   피하면서 화자구분을 얻는 방식. 오디오 처리가 2배(~+$0.6/108분 회의)지만
    #   VOD는 온디맨드라 감당 가능. 비용 절감이 우선이면 False로 끄면 본문만 생성된다.
    #   voiceprint가 등록돼 있으면 '화자 N' 대신 실제 의원명으로 라벨링된다.
    # ★기본 False(2026-06-16): 오디오 2-패스는 비용 2배 + '화자 N'(전역 비일관).
    #   대신 텍스트 기반 화자귀속(text_speaker_service)이 더 싸고(오디오 재처리 0)
    #   실명·전역일관 → 그게 기본. 오디오 diarize가 꼭 필요할 때만 True.
    vod_diarize_enable_second_pass: bool = False
    # ★텍스트 기반 화자귀속 (2026-06-16, 기본 ON):
    #   자막 본문의 호명·자기소개·직책·진행 단서 + 위원회 명부를 gpt 1회로 읽어
    #   '실제 의원명/집행부 직책'을 부여(text_speaker_service). 오디오 재처리 0,
    #   ~$0.01~0.05(diarize 대비 ~1/100), 전역 일관·실명. 화자구분의 기본 방식.
    vod_text_speaker_attribution: bool = True
    # ★VOD 음성 화자 융합 (2026-09-05): 텍스트 화자귀속 결과를 자막 창(window)별 화자 임베딩
    #   (sherpa-onnx · 3D-Speaker CAM++, CPU 워커 서브프로세스)으로 교정한다. 호명·자기소개·
    #   위원장 진행 멘트 창을 앵커로 라벨별 목소리 기준을 만들고 나머지 창을 재판정(speaker_voice_fusion).
    #   속기 대조 실측 3회의: 위원 발언 일치율 74~82% → 97~98%, 다른 위원 오귀속 107~143건 → 3~5건.
    #   회의당 CPU 3~4분(RTF 0.013). 실패·모델 없음은 fail-soft(텍스트 결과 유지).
    #   정본: docs/speaker-accuracy-eval-2026-09.md. 임계값 4개는 그 문서의 EER 보정값이다.
    vod_voice_speaker_fusion: bool = True
    voice_model_path: str = "models/speaker.onnx"   # Dockerfile 이 sha256 핀으로 굽는다
    voice_cos_override: float = 0.55
    voice_cos_override_official: float = 0.55
    voice_cos_margin: float = 0.10
    voice_cos_reject: float = 0.35
    voice_cos_purity: float = 0.45
    voice_window_max_seconds: float = 10.0
    voice_window_min_seconds: float = 1.5
    voice_threads: int = 1        # 라이브 STT 와 CPU 를 나눈다 (워커는 nice 10)
    voice_timeout_seconds: int = 1200
    # 화자 구분용 롤링 버퍼 flush 주기(초). 길수록 화자 추정 안정·지연 증가.
    diarize_buffer_seconds: float = 12.0
    # diarize segment ↔ 경로 A 자막 시간 매칭 허용 오차(초).
    diarize_match_tolerance_seconds: float = 2.0
    # diarize 입력 wav 샘플레이트(전사 충분치는 16kHz).
    diarize_audio_rate: int = 16000

    # 실명 화자 식별 (known_speaker_references) — Phase 12 후속
    # 의원 목소리 샘플을 등록해 diarize가 "화자 N" 대신 실제 의원명을 반환하게 한다.
    # ★API 제약: 호출당 최대 4명(known_speaker_references). 위원회별로 우선순위 높은 ≤4명을 등록.
    diarize_known_speakers_enabled: bool = True
    diarize_max_known_speakers: int = 4
    # 등록 목소리 샘플 길이 제약 (OpenAI: 2~10초)
    voiceprint_min_seconds: float = 2.0
    voiceprint_max_seconds: float = 10.0
    # 샘플 저장 샘플레이트 (16kHz mono wav)
    voiceprint_sample_rate: int = 16000

    # 구조 인지형 화자 추적 (상임위 회의 구조 활용)
    # 위원장 호명("OO 위원 질의") 단서로 현재 질의 위원 voiceprint를 동적 교체.
    cue_tracking_enabled: bool = True
    # 호명 이름 ↔ 위원회 명부 퍼지 매칭 임계값 (difflib ratio, 후보 ~15명이라 0.6 견고)
    cue_match_threshold: float = 0.6

    # ─── 얼굴로 의원 찾기 (2026-09-16) ──────────────────────────────────────
    # 영상 화면의 얼굴을 공식 사진 명부와 맞춰 이름을 붙인다(SCRFD 검출 + ArcFace 임베딩,
    # 모델은 Dockerfile 이 sha256 핀으로 굽는다). 임계값 정본과 실측 근거는
    # docs/face-recognition-eval-2026-09.md.
    face_recognition_enabled: bool = True
    face_det_model_path: str = "models/face/det_10g.onnx"
    face_rec_model_path: str = "models/face/w600k_r50.onnx"
    face_threads: int = 1              # 라이브 STT 와 CPU 를 나눈다
    face_det_size: int = 640           # 검출 입력 한 변
    face_det_threshold: float = 0.5    # 얼굴 검출 점수 하한
    face_max_faces: int = 12
    face_min_px: int = 48              # 이보다 작은 얼굴엔 이름을 붙이지 않는다
    # 판정 임계값 — 후보를 위원회로 좁혔을 때(accept)와 전체 명부일 때(accept_open).
    # 실측(2026-09-16 ch60): 본인 0.49~0.62 · 의원이 아닌 사람 최고 0.34.
    face_cos_accept: float = 0.42
    face_cos_accept_open: float = 0.46
    face_cos_margin: float = 0.06      # 1등과 2등의 차이가 이보다 작으면 이름을 안 붙인다
    face_hint_relief: float = 0.06     # 지금 발언자와 같은 이름이면 이만큼 완화
    face_gallery_ttl_seconds: int = 300
    face_frame_cache_seconds: float = 2.0
    # 현장 템플릿 자동 등록 — 아주 확신할 때만. 잘못 담기면 그 이름이 계속 틀린다.
    face_auto_enroll: bool = True
    face_enroll_min_score: float = 0.55
    face_enroll_min_px: int = 70
    face_enroll_min_det: float = 0.85
    face_max_video_templates: int = 5
    face_min_interval_seconds: float = 1.2   # 같은 사용자 연타 차단

    # 배치 교정 (관리자가 트리거하는 일회성 AI 문법/용어 검사) — grammar_checker가 사용. 유지.
    # 저지연보다 품질 우선 → flagship 모델 사용.
    batch_correction_model: str = "gpt-5.4"

    # 라이브 자막 GPT 사후 교정 (live_corrector) — 정확도 향상 + '교정 중'→'교정됨'.
    # 사용자 요구: "10초 정도 딜레이돼도 좋으니 정확도를 높여줘".
    # ★비용: 호출마다 글로서리를 재전송하므로 flagship(gpt-5.4)을 쓰면 시간당 $2+ 소요.
    #   mini로도 STT 오타·숫자 보정은 충분 → 시간당 ~$0.1 수준.
    live_correction_enabled: bool = True
    live_correction_model: str = "gpt-5.4-mini"
    live_correction_batch_size: int = 4       # 자막 N개 모이면 즉시 교정
    live_correction_flush_seconds: float = 7.0  # 부분 배치도 이 시간 내 교정(단건 포함)
    live_correction_max_tokens: int = 1200

    # 최종본 생성 LLM 교정 모델 (final_transcript_service)
    final_transcript_model: str = "gpt-5-mini"

    # ★VOD 예산/큰숫자 LLM 교정 — 의심 라인(무단위 긴 숫자열 등)만 골라
    #   gpt(openai_model) 배치 1회로 재구성. 결정론 정규화(numeral_normalizer)의 보완.
    vod_numeral_llm_fix: bool = True

    # 발언영상 클립 추출 (speakers/clip, ffmpeg URL-seek) — KMS는 연결당 ~0.3MB/s
    # 스로틀이라 추출 시간 ≈ 구간 길이. 단건 동기 추출 상한(초).
    clip_max_seconds: int = 900
    # 병합 클립 잡 1건당 최대 구간 수
    clip_job_max_segments: int = 20

    # ─── 발언영상 클립 워크벤치 (2026-09, 데스크톱 추출기 대체) ───────────────
    clip_store_dir: str = "clips"                 # k8s: /app/clips (PVC). 상대경로는 백엔드 루트 기준
    clip_store_ttl_days: int = 7                  # 완료 클립 보존일 (사용자 결정)
    clip_store_max_bytes: int = 8 * 1024 ** 3     # 하드 상한 — 넘으면 오래된 완료 잡부터 삭제 (vdb 78% 실측)
    clip_store_sweep_interval_minutes: int = 60
    clip_job_max_active: int = 2                  # KMS 연결당 ~0.3MB/s → 2병렬까지
    clip_job_max_queued: int = 10
    clip_job_max_total_seconds: int = 1800        # 잡 1건 총 길이 상한 (= clip_max_seconds*2)
    clip_index_cache_seconds: int = 600           # KMS 인덱스 인프로세스 캐시 (다음날 등록되므로 짧게)
    clip_bytes_per_second: int = 250_000          # 저장 공간 프리플라이트 계수 (~2Mbps, 실측 후 보정)
    # ─── 자동 클립 (2026-09-10 사용자 결정) — AI 자막이 끝난 회의의 의원 전원 영상을 서버가 미리 잘라 둔다 ───
    # 별도 작업자 파드(ggc-live-transcribe-clipper, cpu 1·mem 1Gi)가 돌린다 — 생중계 STT 가 도는 api 파드와 떼어 둔다.
    # 원본 그대로면 회의 1건 2.8~5.8GB(의원 구간이 회의의 82~95%)라 여유 19GB 가 하루면 찬다 → 720p 로 줄인다.
    clip_auto_enabled: bool = True
    clip_auto_max_age_days: int = 2               # 이 기간 안 회의만 대상(과거 회기 무더기 방지)
    clip_auto_ttl_days: int = 3                   # 자동 클립 보관일 (수동 7일보다 짧다)
    clip_auto_max_bytes: int = 5 * 1024 ** 3      # 자동분 예산 — 넘으면 오래된 자동 클립부터(수동은 안 건드림)
    clip_auto_min_free_bytes: int = 12 * 1024 ** 3   # 노드 디스크 여유가 이보다 적으면 자르지 않는다(08-18 디스크 사고)
    clip_auto_crf: int = 28                       # 720p H.264 veryfast 1스레드: 원본의 17%·실시간 5.4배(2026-09-10 실측)
    clip_auto_bytes_per_second: int = 60_000      # 압축 클립 예상 크기 계수(실측 49KB/s + 여유)
    clip_auto_scan_minutes: int = 30              # 대상 회의를 찾는 주기(VOD 등록 루프와 같게)
    clip_auto_pad_seconds: float = 1.0            # 앞뒤 여유 — 워크벤치 기본값과 같다

    # 외부 노출 백엔드 절대 URL (영상추출기 배포채널 version.json의 다운로드 URL 등).
    # 비우면 요청의 base_url에서 유도한다. 예: https://example.org
    public_base_url: str = ""

    # JWT 인증
    # 기본값을 두지 않는다 — 비면 기동에 실패한다(main.py lifespan).
    # 생성: openssl rand -hex 32
    jwt_secret_key: str = ""
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440  # 24시간

    # QR 로그인 상류 (경기도의회 모바일 로그인 서비스, 프록시 모드 → magent).
    # 명세: {ggc_login_base_url}/integrate.md — 비우면 QR 로그인 비활성(503).
    ggc_login_base_url: str = "https://ggc-mobile-login-git.vercel.app"

    # 빠른 admin PIN 로그인 (4자리)
    # 환경변수 ADMIN_QUICK_PIN 으로만 준다(운영은 Secret ggc-live-transcribe-runtime). 비우면 PIN 로그인이 꺼진다.
    # 코드에 기본값을 두지 않는다 — 저장소를 본 사람이 곧 관리자가 되는 값이 된다.
    admin_quick_pin: str = ""

    # CORS
    cors_origins: list[str] = [
        "http://localhost:3000",
        "http://localhost:3001",
        "http://localhost:3002",
        "http://localhost:3003",
        "http://localhost:3004",
        "http://localhost:3005",
    ]
    # Vercel 프리뷰 도메인 + 로컬 개발(localhost/127.0.0.1의 모든 포트)
    cors_origin_regex: str = r"https://.*\.vercel\.app|http://(localhost|127\.0\.0\.1)(:\d+)?"

    # interim 문장 병합 버퍼 (delta 조각을 문장 종결/길이 기준으로 병합 후 브로드캐스트)
    sentence_buffer_enabled: bool = True
    sentence_buffer_min_chars: int = 8

    # STT 자동 시작 (방송중 채널 감지 시 자동 STT)
    stt_auto_start: bool = True

    # 채널 상태 SSE 스트림 — 시청자당 1개 상시 점유 연결.
    # 2026-07-21 장애: ngrok Hobbyist의 TCP 연결 한도(150/분)를 시청자 재접속 폭주가
    # 초과해 임시 차단했다가, 같은 날 Pay-as-you-go($20) 상향으로 한도가 풀려 복원.
    # 터널 과부하 재발 시 환경변수 CHANNEL_SSE_ENABLED=false 로 즉시 차단 가능
    # (프론트는 404 시 30초 폴링으로 자동 폴백).
    channel_sse_enabled: bool = True

    # ─── 기관(테넌트) 설정 — 다른 의회가 쓰려면 이 값만 바꾼다 (2026-09-16) ──────────
    # 기본값은 전부 **경기도의회의 현재 값**이라 이 릴리스는 동작이 바뀌지 않는다.
    # 값을 비우면 그 기능이 조용히 꺼진다(판정은 core/features.py 한 곳에서 한다).
    # ⚠ 기본값을 비우기 전에 **운영 매니페스트에 값을 먼저 명시**한다 —
    #   k8s/ggc-live-transcribe.yaml 에 GGC_LOGIN_BASE_URL 이 없어서, 그 기본값을 먼저 비우면
    #   경기도 QR 로그인이 즉시 503 이 되고 이 서비스에는 아이디 로그인이 없다(= 아무도 못 들어온다).
    org_name: str = "경기도의회"
    kms_base_url: str = "https://kms.ggc.go.kr"
    council_calendar_url: str = "https://www.ggc.go.kr/site/main/schedule/list/{date}/ALL"
    councilor_api_base_url: str = "https://www.ggc.go.kr/site/main/api/portaltoggc/"
    council_onair_api_url: str = "https://live.ggc.go.kr/getOnairListTodayData.do"

    # ─── 채널 저장소 (2026-09-16) ─────────────────────────────────────────────
    # "db"   = subtitle.channels 표를 읽는다(기본). 관리자 화면에서 채널을 등록·수정한다.
    # "seed" = 표를 아예 안 본다 — 전환 사고 시 파드 env 하나로 되돌리는 킬스위치.
    channels_source: str = "db"
    channels_cache_ttl_seconds: int = 60
    # DB 를 못 읽을 때 코드 시드(SEED_CHANNELS)로 버틸지.
    # 다른 기관 배포에서는 false 로 둔다 — 경기도 채널 18개가 잘못 뜨면 안 된다.
    channels_seed_fallback: bool = True

    # ─── 방송상태 제공자 (2026-09-16) ────────────────────────────────────────
    # 채널마다 status_provider 로 정하고, 비어 있으면 이 기본값을 쓴다.
    #   ggc    = 경기도의회 생중계 API (기존 동작)
    #   probe  = m3u8 을 직접 받아 세그먼트가 늘면 방송중 (기관 중립 — 다른 의회의 기본)
    #   manual = 관리자가 켜고 끈다 (자동 감지가 안 되는 곳)
    default_status_provider: str = "ggc"
    probe_interval_seconds: int = 20
    probe_stale_seconds: int = 60       # 이만큼 세그먼트가 안 늘면 정회중(2)
    probe_off_seconds: int = 300        # 이만큼이면 종료(3)
    probe_concurrency: int = 5
    probe_timeout_seconds: float = 5.0

    # 등록된 채널의 호스트 외에 추가로 허용할 스트림 호스트 (콤마 구분)
    extra_stream_hosts: str = ""

    # 생중계 페이지 → 영상 주소 자동 탐지 (관리자 전용)
    discovery_enabled: bool = True
    discovery_max_bytes: int = 2_000_000
    discovery_timeout_seconds: float = 8.0

    # DB 백엔드 선택자. core/postgres.py:is_postgres_backend() 가 읽는데 필드가 없어서
    # 그 경로가 배선되는 순간 AttributeError 가 날 자리였다(호출자 미배선이라 지금은 안 터진다).
    # 값은 운영 매니페스트(DB_BACKEND=supabase)와 같다 — 동작 변화 없음.
    db_backend: str = "supabase"

    # 서버
    debug: bool = False


settings = Settings()
