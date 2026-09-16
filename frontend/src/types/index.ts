// 공통 타입 정의

export interface MeetingType {
  id: string;
  title: string;
  meeting_date: string;
  stream_url: string | null;
  vod_url: string | null;
  status: 'scheduled' | 'live' | 'processing' | 'ended';
  duration_seconds: number | null;
  meeting_type?: string | null;
  committee?: string | null;
  transcript_status?: 'draft' | 'reviewing' | 'final';
  /** 자막 워크플로우 단계 (migration 017):
   *  none → draft(라이브) → ai(OpenAI 배치) → reviewing(속기사) → final */
  subtitle_stage?: 'none' | 'draft' | 'ai' | 'reviewing' | 'final';
  /** 의회 홈페이지(KMS 최근회의영상) 목록 번호 — 정렬·대조용 */
  kms_no?: number | null;
  /** 회기 번호 (예: 391 → 제391회) — KMS 일괄 등록 시 저장, 구 데이터는 제목에서 추출 */
  session_no?: number | null;
  /** 안건 초안 생성(agenda-draft) 최초 실행 시각 — 회의당 1회 정책 마커 (migration 026) */
  agenda_draft_at?: string | null;
  created_at: string;
  updated_at: string;
}

/** 요구자료 — 자막에서 감지된 의원의 자료 제출 요구 (사무처 KMS 등록 보조 목록) */
export interface MaterialRequestType {
  id: string;
  meeting_id: string;
  subtitle_id?: string | null;
  /** 발언 시각(초) — 영상 점프용 */
  start_time?: number | null;
  speaker?: string | null;
  /** 요구 의원 실명 (추정 — 직원 수정 가능) */
  councilor_name?: string | null;
  /** 요청 자료 제목 (예: '지방채 발행 검토 자료') */
  summary: string;
  /** 핵심 요구 발언 원문 발췌 */
  request_text?: string | null;
  /** 요구 대상 부서/기관 */
  department?: string | null;
  confidence: 'high' | 'medium' | 'low';
  status: 'detected' | 'confirmed' | 'dismissed' | 'registered';
  source: 'live' | 'vod_scan' | 'manual';
  created_at?: string;
  updated_at?: string;
}

export interface SubtitleType {
  id: string;
  meeting_id: string;
  start_time: number;
  end_time: number;
  text: string;
  speaker: string | null;
  confidence: number | null;
  created_at: string;
  /** 원본 텍스트 (교정 전). 교정된 경우에만 존재 */
  original_text?: string;
  /** AI 교정 완료 여부 */
  is_corrected?: boolean;
  /** 교정 상태 */
  correction_state?: 'pending' | 'corrected' | null;
  /** 대조 상태 */
  verification_status?: 'unverified' | 'verified' | 'flagged';
}

export interface ApiResponse<T> {
  data: T;
  meta?: {
    total: number;
    page: number;
  };
}

export interface ApiError {
  error: {
    code: string;
    message: string;
  };
}

export interface ChannelType {
  id: string;
  name: string;
  code: string;
  stream_url: string;
  livestatus?: number;     // 0=방송전, 1=방송중, 2=정회중, 3=종료, 4=생중계없음
  status_text?: string;    // "방송중", "방송전" 등
  has_schedule?: boolean;  // 오늘 일정 유무
  session_no?: number;     // 회차 (예: 388 → 제388회)
  session_order?: number;  // 차수 (예: 1 → 제1차)
  stt_running?: boolean;
  viewers?: number;        // 현재 시청자 수 (자막 WS 룸 연결 수)
  sync_target_sec?: number; // /live 영상 지연 목표(초, api env LIVE_SYNC_TARGET_SEC) — 플레이어가 마운트 전에 읽는다
}

/**
 * 의사일정 한 건 — 의회 홈페이지 의정캘린더에서 수집한 것.
 * `GET /api/schedule/upcoming` (backend `app/api/schedule.py`)
 */
export interface ScheduleItemType {
  committee_code: string;   // A011(본회의) / C105 … = ChannelType.code 와 같은 값
  committee_name: string;
  start_time: string | null;
  session_no: number | null;    // 제393회
  session_order: number | null; // 제1차
  session_kind: string | null;  // 임시회 / 정례회
  agenda_items: string[];
  is_cancelled: boolean;
  changed_at: string | null;    // 안건이 '실제로 바뀐' 시각 (확인 시각과 다르다)
}

export interface ScheduleDayType {
  date: string;                 // YYYY-MM-DD
  items: ScheduleItemType[];
}

export interface UpcomingScheduleType {
  from: string;
  to: string;
  synced_at: string | null;     // 마지막으로 홈페이지를 확인한 시각
  days: ScheduleDayType[];
}

export interface VodRegisterFormType {
  url: string;
}

// Bills types
export interface BillItem {
  id: string;
  bill_number: string;
  title: string;
  proposer: string | null;
  committee: string | null;
  status: 'received' | 'reviewing' | 'decided' | 'promulgated';
  proposed_date: string | null;
  created_at: string;
  updated_at: string;
}

export interface BillMention {
  id: string;
  bill_id: string;
  meeting_id: string;
  subtitle_id: string | null;
  start_time: number | null;
  end_time: number | null;
  note: string | null;
  meeting_title?: string;
  meeting_date?: string;
  created_at: string;
}

export interface BillDetail extends BillItem {
  mentions: BillMention[];
}

export interface BillsResponse {
  items: BillItem[];
  total: number;
  limit: number;
  offset: number;
}

export interface BillCreateData {
  bill_number: string;
  title: string;
  proposer?: string;
  committee?: string;
  status?: 'received' | 'reviewing' | 'decided' | 'promulgated';
  proposed_date?: string;
}

// Phase 6A types

export interface ParticipantType {
  id: string;
  meeting_id: string;
  councilor_id: string;
  name: string | null;
  role: string | null;
  created_at: string | null;
}

export interface AgendaType {
  id: string;
  meeting_id: string;
  order_num: number;
  title: string;
  description: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface SubtitleHistoryType {
  id: string;
  subtitle_id: string;
  field_name: string;
  old_value: string | null;
  new_value: string | null;
  changed_by: string | null;
  created_at: string;
}

export interface PublicationType {
  id: string;
  meeting_id: string;
  status: 'draft' | 'reviewing' | 'final';
  published_by: string | null;
  notes: string | null;
  created_at: string;
}

// Phase 7: Verification
export interface VerificationStatsType {
  total: number;
  verified: number;
  unverified: number;
  flagged: number;
  progress: number;  // 0.0 ~ 1.0
}

export interface ReviewQueueResponse {
  items: SubtitleType[];
  total: number;
  limit: number;
  offset: number;
}

// Speaker Timeline
export interface SpeakerSegment {
  id: string;
  start_time: number;
  end_time: number;
  text: string;
  confidence: number | null;
}

export interface SpeakerSummary {
  speaker: string;
  total_time: number;
  segment_count: number;
  segments: SpeakerSegment[];
}

export interface SpeakersTimelineResponse {
  speakers: SpeakerSummary[];
  total_duration: number;
}

// Phase 7: Meeting Summary
export interface MeetingSummaryType {
  id: string;
  meeting_id: string;
  summary_text: string;
  agenda_summaries: Array<{
    order_num: number;
    title: string;
    summary: string;
  }>;
  key_decisions: string[];
  action_items: string[];
  model_used: string;
  /** 청크별 중간 요약(긴 회의, migration 034) */
  segments?: Array<{
    idx: number;
    order_num: number | null;
    title: string | null;
    start_time: number;
    end_time: number;
    summary: string;
    decisions?: string[];
    action_items?: string[];
  }> | null;
  /** 발언자별 요지 */
  speakers?: Array<{ name: string; points: string[] }> | null;
  /** 요약에 들어간 자막 글자 수 */
  source_chars?: number | null;
  /** true = 전 구간을 본 요약 · false = 앞부분만 본 옛 요약(다시 만들 수 있다) · null/undefined = 알 수 없음(034 이전) */
  complete?: boolean | null;
  generated_from?: 'ai' | 'live' | 'unknown' | null;
  created_at: string;
  updated_at: string;
}

// Phase 10: Minutes by Agenda
export interface AgendaMinutesItem {
  order_num: number;
  title: string;
  description: string | null;
  subtitles: SubtitleType[];
  speaker_groups: Array<{
    speaker: string;
    texts: string[];
    start_time: number;
    end_time: number;
  }>;
}

export interface MinutesByAgendaResponse {
  agendas: AgendaMinutesItem[];
  unassigned_subtitles: SubtitleType[];
  total_subtitles: number;
}

// Phase 11: Agenda File Management
export interface AgendaFileType {
  id: string;
  agenda_id: string;
  filename: string;
  file_size: number;
  mime_type: string;
  created_at: string;
}

// Phase 11: Statistics Dashboard
export interface StatsOverviewType {
  total_meetings: number;
  total_subtitles: number;
  total_duration: number; // seconds
  average_confidence: number; // 0.0 ~ 1.0
}

export interface StatsSpeakerItem {
  speaker: string;
  total_count: number;
  total_duration: number; // seconds
}

export interface StatsMeetingByMonth {
  month: string; // YYYY-MM
  count: number;
}

// 접속자 수 (오늘 / 누적)
export interface VisitorStatsType {
  today: number;
  total: number;
}

// 접속 통계 (2026-09-16) — 접속처는 '이름'만 온다. IP 는 서버가 저장하지 않는다
export interface AccessSiteItem {
  label: string;
  visitors: number;
  page_views: number;
  watch_seconds: number;
  login_prompts: number;
  share: number; // %
}

export interface AccessDailyItem {
  date: string;
  visitors: number;
  page_views: number;
  watch_seconds: number;
  login_prompts: number;
}

export interface AccessMeetingItem {
  meeting_id: string;
  title: string;
  meeting_date?: string | null;
  viewers: number;
  watch_seconds: number;
}

export interface AccessFeatureItem {
  kind: string;
  label: string;
  events: number;
  visitors: number;
}

export interface AccessStatsType {
  days: number;
  from: string;
  to: string;
  site: string | null;
  today: { visitors: number; page_views: number; watch_seconds: number };
  now_watching: number;
  totals: {
    visitors: number;
    page_views: number;
    watch_seconds: number;
    avg_daily_visitors: number;
    login_prompts: number;
  };
  daily: AccessDailyItem[];
  sites: AccessSiteItem[];
  hourly: Array<{ hour: number; visitors: number }>;
  weekday_hour: number[][]; // [요일 0=월][시 0~23]
  features: AccessFeatureItem[];
  devices: Array<{ device: string; visitors: number }>;
  meetings: AccessMeetingItem[];
  insights: string[];
  detail_since: string | null;
}

// 접속 기록 한 건 — 개인정보는 담기지 않는다
export type AccessEventKind =
  | 'page'
  | 'watch_live'
  | 'watch_vod'
  | 'search'
  | 'ai'
  | 'download'
  | 'record'
  | 'login_prompt';

// Phase 11: Notification
export interface NotificationType {
  id: string;
  type: 'stt_completed' | 'verification_needed' | 'summary_generated' | 'system';
  title: string;
  message: string;
  related_meeting_id: string | null;
  is_read: boolean;
  created_at: string;
}

// Phase 12: Stenography Management
export interface StenographyRecord {
  id: string;
  meeting_id: string;
  content: string;
  stenographer_name: string;
  status: 'draft' | 'submitted' | 'approved';
  kind?: 'manual' | 'ai_final';
  file_path: string | null;
  filename: string | null;
  file_size: number | null;
  created_at: string;
  updated_at: string;
}

export interface StenographyComparison {
  stenography_lines: string[];
  subtitle_texts: string[];
  total_steno_lines: number;
  total_subtitle_count: number;
}

export interface CouncilorType {
  id: string;
  name: string;
  party: string | null;
  district: string | null;
  committee: string | null;
  role: string | null;
  contact: string | null;
  active: boolean;
  profile_image_url?: string | null;
  /** 소속 위원회 목록 (제12대 명부 — 겸임 포함, role: 위원장/부위원장/위원) */
  committees?: { name: string; role: string }[];
}

// Stenography Lines (Professional Editor)
export interface StenographyLine {
  id: string;
  record_id: string;
  sequence_no: number;
  text: string;
  speaker: string | null;
  start_ms: number | null;
  end_ms: number | null;
  starts_new_paragraph: boolean;
  created_at: string;
  updated_at: string;
  /** 낙관적 동시성 제어용 버전 번호 (서버 반환, 충돌 감지에 사용) */
  version?: number;
}

export interface StenographyLineUpdate {
  id: string;
  text?: string;
  speaker?: string | null;
  start_ms?: number | null;
  end_ms?: number | null;
  starts_new_paragraph?: boolean;
  sequence_no?: number;
  /** 낙관적 동시성 제어용 버전 번호 (409 충돌 감지를 위해 전송) */
  version?: number;
}

export interface StenographyLinesResponse {
  lines: StenographyLine[];
  total: number;
  record_id: string;
}

export interface StenographyLineImportResult {
  imported: number;
  record_id: string;
  lines: StenographyLine[];
}

// Phase 12: Collaborative Editing
export interface EditSession {
  id: string;
  meeting_id: string;
  editor_name: string;
  started_at: string;
  last_active_at: string;
  status: 'active' | 'completed';
}

export interface SubtitleComment {
  id: string;
  subtitle_id: string;
  meeting_id: string;
  author_name: string;
  content: string;
  resolved: boolean;
  created_at: string;
}

// Phase 11B: AI Assistant
export interface AiChatMessage {
  role: 'user' | 'assistant';
  content: string;
  sources?: AiSourceReference[];
}

export interface AiSourceReference {
  meeting_id: string;
  meeting_title: string | null;
  start_time: number | null;
  text_snippet: string | null;
  source_type: 'subtitle' | 'bill';
}

export interface AiChatResponse {
  answer: string;
  sources: AiSourceReference[];
  session_id: string;
  /** false = 소유자를 알 수 없어(손님 표식 없음) 이력에 저장되지 않았다 — 후속 질문 맥락이 이어지지 않는다 */
  saved?: boolean;
}

export interface AiConversationSession {
  session_id: string;
  first_question: string;
  message_count: number;
  meeting_context_id: string | null;
  /** 회의 한정 대화의 회의 제목(서버 조인) */
  meeting_title?: string | null;
  created_at: string;
  last_active_at: string;
}

export interface AiConversationItem {
  id: string;
  session_id: string;
  role: 'user' | 'assistant';
  content: string;
  sources: AiSourceReference[] | null;
  meeting_context_id: string | null;
  created_at: string;
}

// API Status types (Admin dashboard)
export interface ApiStatusStats {
  calls_today: number;
  avg_latency_ms: number;
  error_rate: number;
}

export interface ApiStatusItem {
  name: string;
  description: string;
  status: 'connected' | 'disconnected' | 'unknown' | 'not_configured';
  details: Record<string, string | number | boolean | null>;
  stats: ApiStatusStats;
}

export type ApiStatusResponse = ApiStatusItem[];

// Phase 11C: Stenography Line — see StenographyLine defined above (version field added)

// Phase 11C: Stenography Edit History
export interface StenographyEditHistoryEntry {
  id: string;
  line_id: string;
  editor_name: string;
  field_changed: 'text' | 'speaker' | 'start_ms' | 'end_ms' | 'paragraph';
  old_value: string | null;
  new_value: string;
  created_at: string;
}

export interface StenographyEditHistoryResponse {
  items: StenographyEditHistoryEntry[];
  total: number;
}

// Phase 11C: AI Suggestions
export interface SpeakerSuggestion {
  line_id: string;
  suggested_speaker: string;
}

export interface ProofreadCorrection {
  line_id: string;
  original_text: string;
  corrected_text: string;
  changes: string[];
}

export interface ParagraphSuggestion {
  line_id: string;
  starts_new_paragraph: boolean;
}

// Phase 11C: Dashboard
export interface StenographyDashboardItem extends StenographyRecord {
  meetings?: {
    title: string;
    meeting_date: string;
    committee: string | null;
  };
}

// =============================================================================
// 발언영상 추출 (의원별 발언 구간 클립)
// =============================================================================

/** 화자의 연속 발언 구간 (자막 병합 단위) */
export interface SpeakerSegmentType {
  start_time: number;
  end_time: number;
  duration: number;
  subtitle_count: number;
  text_preview: string;
}

/** 화자별 발언 구간 그룹 */
export interface SpeakerSegmentGroupType {
  speaker: string;
  total_time: number;
  segment_count: number;
  segments: SpeakerSegmentType[];
}

/** GET /api/meetings/{id}/speakers/segments 응답 */
export interface SpeakerSegmentsResponseType {
  meeting_id: string;
  kms_midx: string | null;
  title: string;
  total_duration: number;
  speakers: SpeakerSegmentGroupType[];
}

/** 병합 클립 작업 상태 (GET /speakers/clip-jobs/{job_id}) — 백엔드는 queued/done, 구형 표기 병행 수용 */
export interface ClipJobStatusType {
  status: 'queued' | 'pending' | 'running' | 'done' | 'completed' | 'failed';
  progress: number;
  current_segment: number | null;
  error: string | null;
  filename: string | null;
}

// =============================================================================
// 영상추출기 배포 (Tools)
// =============================================================================

/** GET /api/tools/extractor/version.json 응답 (배포 매니페스트) */
export interface ExtractorVersionType {
  name: string;
  version: string;
  notes: string;
  published_at: string | null;
  /** 설치파일 다운로드 URL (version.json 조회 시 서버가 조립) */
  url?: string | null;
  sha256: string | null;
  size: number | null;
  /** 외부 호스팅 URL (GitHub Releases 등) — 업로드 응답에만 포함 */
  external_url?: string | null;
  min_supported_version?: string | null;
}

// =============================================================================
// 발언영상 클립 워크벤치 (2026-09, 데스크톱 추출기 대체) — /api/clip-jobs · /clip-index
// =============================================================================

/** 구간 출처: official=KMS 발언자 인덱스 · ai=AI 자막(잠정) · live=실시간 자막(초안) · manual=수동 자르기 */
export type ClipSourceKind = 'official' | 'ai' | 'live' | 'manual';

export interface ClipIndexSegmentType {
  idx: number;
  /** 초. source=live 면 STT 시계(미보정) — 표시할 때 time_offset 을 더한다 */
  start: number;
  end: number;
  seconds: number;
  time: string;
  title: string;
  /** true=이름이 명시된 실제 발언, false=같은 의원 코드의 의사진행 항목(기본 해제) */
  named: boolean;
}

export interface ClipSpeakerType {
  key: string;
  code?: string;
  name: string;
  role: string;
  party: string | null;
  district: string | null;
  photo_url: string | null;
  councilor_id: string | null;
  /** 소속 위원회(의원 명부) — 카드에 겸임 상임위를 띄운다(2026-09-11). 명부에 없으면 없다 */
  committees?: { name: string; role: string }[];
  total_seconds: number;
  segments: ClipIndexSegmentType[];
}

/** GET /api/meetings/{id}/clip-index */
export interface ClipIndexType {
  meeting_id: string;
  kms_midx: string | null;
  duration: number | null;
  source: ClipSourceKind | 'none';
  time_offset: number;
  speakers: ClipSpeakerType[];
  warnings: string[];
}

/** POST /api/meetings/{id}/clip-jobs 요청 */
export interface ClipJobCreateRequestType {
  /** no = 그 의원 구간 목록의 순번(1부터) → 파일 이름 `이름_회의명_번호` 의 번호. 수동 자르기는 없다 */
  segments: { start: number; end: number; no?: number }[];
  merge: boolean;
  pad_before: number;
  pad_after: number;
  label: string;
  speaker_name?: string | null;
  source_kind: ClipSourceKind;
  with_srt: boolean;
  time_offset: number;
}

export interface ClipJobFileType {
  name: string;
  kind: 'mp4' | 'srt';
  bytes: number;
}

export type ClipJobStatus = 'queued' | 'running' | 'done' | 'failed' | 'cancelled' | 'expired';

/** GET /api/meetings/{id}/clip-jobs/{job_id} · GET /api/clip-jobs 의 한 행 */
export interface ClipJobType {
  job_id: string;
  meeting_id: string;
  meeting_title?: string | null;
  meeting_date?: string | null;
  owner_username?: string | null;
  label: string | null;
  speaker_name: string | null;
  source_kind: ClipSourceKind;
  status: ClipJobStatus;
  progress: number;
  current_segment: number | null;
  segment_count: number;
  total_seconds: number;
  merge: boolean;
  with_srt: boolean;
  error: string | null;
  files: ClipJobFileType[];
  bytes_total: number;
  created_at: string;
  finished_at: string | null;
  expires_at: string | null;
  evicted_reason: 'ttl' | 'capacity' | 'manual' | 'restart' | null;
  /** 파일명 → 다운로드 경로 (API_BASE_URL 기준 상대) */
  download_urls: Record<string, string>;
  /** manual = 사람이 워크벤치에서 · auto = AI 자막 뒤 서버가 자동으로(2026-09-10) */
  origin?: 'manual' | 'auto';
  /** 720p 로 줄여 저장했는가(자동 클립) */
  compress?: boolean;
  /** 파일에 실제 담긴 구간(여유 포함). no = 그 의원 구간 목록 순번 = 파일 이름 끝 번호 */
  segments?: { start: number; end: number; no?: number }[];
}

export interface ClipJobListResponseType {
  jobs: ClipJobType[];
  store: { used_bytes: number; max_bytes: number; ttl_days: number };
}

/** GET /api/meetings/{id}/auto-clips · GET /api/auto-clips — 서버가 미리 잘라 둔 의원 영상 */
export interface AutoClipListResponseType {
  meeting_id?: string;
  jobs: ClipJobType[];
  ttl_days: number;
  enabled: boolean;
  /** "공유 전에 한 번 재생해 확인" 안내 — 정확도가 99% 가 아니다 */
  notice: string;
}

