/**
 * API 클라이언트
 *
 * 환경변수 NEXT_PUBLIC_API_URL을 기본 URL로 사용하며,
 * 설정되지 않은 경우 localhost:8000을 사용합니다.
 */

import { guestHeaders } from '@/lib/guest';
import type {
  AgendaType,
  BillCreateData,
  BillDetail,
  BillsResponse,
  ClipJobStatusType,
  CouncilorType,
  EditSession,
  ExtractorVersionType,
  MaterialRequestType,
  MeetingSummaryType,
  MinutesByAgendaResponse,
  ParticipantType,
  ParagraphSuggestion,
  ProofreadCorrection,
  PublicationType,
  ReviewQueueResponse,
  SpeakerSegmentsResponseType,
  SpeakerSuggestion,
  SpeakersTimelineResponse,
  StenographyComparison,
  StenographyDashboardItem,
  StenographyEditHistoryResponse,
  StenographyLine,
  StenographyLineUpdate,
  StenographyRecord,
  SubtitleComment,
  SubtitleHistoryType,
  SubtitleType,
  VerificationStatsType,
 AgendaFileType ,
  NotificationType,
  StatsMeetingByMonth,
  StatsOverviewType,
  StatsSpeakerItem,
  VisitorStatsType,
  AccessEventKind,
  AccessStatsType,
  AiChatResponse,
  AiConversationItem,
  AiConversationSession,
  ApiStatusResponse,
  ClipIndexType,
  ClipJobCreateRequestType,
  ClipJobType,
  ClipJobListResponseType,
  AutoClipListResponseType,
} from '@/types';

// 브라우저에서는 same-origin(basePath 접두) 으로 호출 → k3s 에선 Ingress 가,
// Vercel 에선 Next.js rewrite 가 백엔드로 중계 (CORS 사전요청 회피).
// 서버측 렌더링에서는 절대 URL(NEXT_PUBLIC_API_URL) 을 사용한다.
export const API_BASE_URL =
  typeof window === 'undefined'
    ? process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
    : process.env.NEXT_PUBLIC_BASE_PATH || '';

/**
 * API 에러 클래스
 */
export class ApiError extends Error {
  public detail?: Record<string, unknown>;

  constructor(
    public status: number,
    message: string,
    detail?: Record<string, unknown>
  ) {
    super(message);
    this.name = 'ApiError';
    this.detail = detail;
  }
}

/**
 * API 클라이언트 함수
 *
 * @param endpoint - API 엔드포인트 (예: '/api/meetings')
 * @param options - fetch 옵션
 * @returns API 응답 데이터
 * @throws ApiError - API 에러 발생 시
 * @throws Error - 네트워크 에러 발생 시
 */
export async function apiClient<T>(
  endpoint: string,
  options?: RequestInit
): Promise<T> {
  const url = `${API_BASE_URL}${endpoint}`;

  // JWT 토큰 자동 첨부
  const token = typeof window !== 'undefined' ? localStorage.getItem('auth_token') : null;

  const defaultHeaders: HeadersInit = {
    'Content-Type': 'application/json',
    // ngrok 무료 터널의 브라우저 경고 인터스티셜 우회 (다른 호스트에선 무해)
    'ngrok-skip-browser-warning': '1',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    // 로그인하지 않은 의회망 방문자의 브라우저 표식 — 추출 기록을 브라우저별로 가른다(2026-09-11)
    ...guestHeaders(token),
  };

  const mergedOptions: RequestInit = {
    ...options,
    headers: {
      ...defaultHeaders,
      ...(options?.headers || {}),
    },
  };

  const response = await fetch(url, mergedOptions);

  if (!response.ok) {
    throw await readApiError(response);
  }

  return response.json() as Promise<T>;
}

/** 실패 응답을 ApiError 로 — FastAPI 의 detail(문자열 또는 객체)을 메시지로 쓴다 */
async function readApiError(response: Response): Promise<ApiError> {
  let errorMessage = `API Error: ${response.status}`;
  let errorDetail: Record<string, unknown> | undefined;

  try {
    const errorData = await response.json();
    if (errorData.detail) {
      if (typeof errorData.detail === 'string') {
        errorMessage = errorData.detail;
      } else {
        errorDetail = errorData.detail as Record<string, unknown>;
        errorMessage = typeof errorData.detail.message === 'string' ? errorData.detail.message : JSON.stringify(errorData.detail);
      }
    } else if (errorData.message) {
      errorMessage = errorData.message;
    }
  } catch {
    // JSON 파싱 실패 시 기본 메시지 사용
  }

  return new ApiError(response.status, errorMessage, errorDetail);
}

/**
 * 회의록 내보내기 다운로드
 *
 * @param meetingId - 회의 ID
 * @param format - 내보내기 형식 ('markdown' | 'srt' | 'json' | 'official')
 */
export async function downloadTranscript(
  meetingId: string,
  format: 'markdown' | 'srt' | 'json' | 'official' | 'html' | 'hwpx' | 'docx' = 'markdown'
): Promise<void> {
  const url = `${API_BASE_URL}/api/meetings/${meetingId}/export?format=${format}`;
  const token = typeof window !== 'undefined' ? localStorage.getItem('auth_token') : null;
  const response = await fetch(url, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });

  if (!response.ok) {
    let errorMessage = `다운로드 실패: ${response.status}`;
    try {
      const errorData = await response.json();
      if (errorData.detail) {
        errorMessage = typeof errorData.detail === 'string' ? errorData.detail : (errorData.detail.message || JSON.stringify(errorData.detail));
      }
    } catch {
      // ignore
    }
    throw new ApiError(response.status, errorMessage);
  }

  const blob = await response.blob();
  const disposition = response.headers.get('Content-Disposition') || '';
  const filenameMatch = disposition.match(/filename="?(.+?)"?$/);
  const ext = format === 'markdown' ? 'md' : format === 'official' ? 'txt' : format;
  const filename = filenameMatch?.[1] || `회의록.${ext}`;

  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(a.href);
}

/** Content-Disposition 헤더에서 파일명 추출 (RFC5987 filename*=UTF-8'' 우선). */
function _filenameFromDisposition(disposition: string, fallback: string): string {
  const star = disposition.match(/filename\*=UTF-8''([^;]+)/i);
  if (star?.[1]) {
    try {
      return decodeURIComponent(star[1].trim());
    } catch {
      /* ignore */
    }
  }
  const plain = disposition.match(/filename="?([^";]+)"?/i);
  return plain?.[1] || fallback;
}

/**
 * 영상회의록(KMS 등록용) 안건시간 HTML 다운로드.
 *
 * 자막에서 챕터(회의 개의/안건/제안설명/검토보고/질의답변)를 LLM으로 도출하므로
 * 수 초가 걸릴 수 있고 로그인이 필요합니다(401). 자막이 없으면 409.
 *
 * @param meetingId - 회의 ID
 */
export async function downloadVideoMinutes(meetingId: string): Promise<void> {
  const url = `${API_BASE_URL}/api/meetings/${meetingId}/video-minutes?format=html`;
  const token = typeof window !== 'undefined' ? localStorage.getItem('auth_token') : null;
  const response = await fetch(url, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });

  if (!response.ok) {
    let errorMessage = `다운로드 실패: ${response.status}`;
    try {
      const errorData = await response.json();
      if (errorData.detail) {
        errorMessage =
          typeof errorData.detail === 'string'
            ? errorData.detail
            : errorData.detail.message || JSON.stringify(errorData.detail);
      }
    } catch {
      /* ignore */
    }
    throw new ApiError(response.status, errorMessage);
  }

  const blob = await response.blob();
  const disposition = response.headers.get('Content-Disposition') || '';
  const filename = _filenameFromDisposition(disposition, '영상회의록.html');

  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(a.href);
}

/**
 * KMS 영상회의록 편집기 자동입력용 JS 콘솔 스크립트 다운로드 (.js).
 *
 * 자막에서 챕터(안건시간)를 LLM으로 도출하므로 수 초가 걸릴 수 있고 로그인이 필요합니다(401).
 * 자막이 없으면 409. 다운받은 .js를 KMS 편집기 콘솔에 붙여넣으면 안건시간이 자동 입력됩니다.
 *
 * @param meetingId - 회의 ID
 */
export async function downloadKmsScript(meetingId: string): Promise<void> {
  const url = `${API_BASE_URL}/api/meetings/${meetingId}/video-minutes?format=js`;
  const token = typeof window !== 'undefined' ? localStorage.getItem('auth_token') : null;
  const response = await fetch(url, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });

  if (!response.ok) {
    let errorMessage = `다운로드 실패: ${response.status}`;
    try {
      const errorData = await response.json();
      if (errorData.detail) {
        errorMessage =
          typeof errorData.detail === 'string'
            ? errorData.detail
            : errorData.detail.message || JSON.stringify(errorData.detail);
      }
    } catch {
      /* ignore */
    }
    throw new ApiError(response.status, errorMessage);
  }

  const blob = await response.blob();
  const disposition = response.headers.get('Content-Disposition') || '';
  const filename = _filenameFromDisposition(disposition, '영상회의록_KMS등록.js');

  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(a.href);
}

// =============================================================================
// 전자회의록 마크다운 미리보기/편집 (kordoc 중간층)
// =============================================================================

/** 회의록 마크다운(미리보기/편집용) 응답 */
export interface MinutesMarkdownResponse {
  markdown: string;
  kordoc_available: boolean;
}

/**
 * 전자회의록 마크다운 조회 (미리보기/편집용).
 *
 * 공식 전자회의록과 동일한 구조의 마크다운 중간층을 반환합니다.
 * 로그인이 필요하며(401), 자막이 없으면 409 — ApiError 로 전파됩니다.
 *
 * @param meetingId - 회의 ID
 */
export async function getMinutesMarkdown(
  meetingId: string
): Promise<MinutesMarkdownResponse> {
  return apiClient<MinutesMarkdownResponse>(
    `/api/meetings/${meetingId}/minutes-markdown`
  );
}

/**
 * 편집된 회의록 마크다운 → 공문서 서식(kordoc) hwpx 재생성 다운로드.
 *
 * 로그인이 필요하며(401), kordoc 사용 불가 시 503, 마크다운 2MB 초과 시 413.
 *
 * @param meetingId - 회의 ID
 * @param markdown - 편집된 회의록 마크다운 전문
 */
export async function downloadHwpxFromMarkdown(
  meetingId: string,
  markdown: string
): Promise<void> {
  const url = `${API_BASE_URL}/api/meetings/${meetingId}/export/hwpx-from-markdown`;
  const token = typeof window !== 'undefined' ? localStorage.getItem('auth_token') : null;
  const response = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({ markdown }),
  });

  if (!response.ok) {
    let errorMessage = `다운로드 실패: ${response.status}`;
    try {
      const errorData = await response.json();
      if (errorData.detail) {
        errorMessage =
          typeof errorData.detail === 'string'
            ? errorData.detail
            : errorData.detail.message || JSON.stringify(errorData.detail);
      }
    } catch {
      /* ignore */
    }
    throw new ApiError(response.status, errorMessage);
  }

  const blob = await response.blob();
  const disposition = response.headers.get('Content-Disposition') || '';
  const filename = _filenameFromDisposition(disposition, '전자회의록_edited.hwpx');

  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(a.href);
}

/**
 * 전자회의록(hwpx) 다운로드 — 엔진 선택.
 *
 * native(기본, 자체 OWPML 라이터)는 비로그인도 가능,
 * kordoc(공문서 서식)은 로그인이 필요합니다(401).
 *
 * @param meetingId - 회의 ID
 * @param engine - hwpx 생성 엔진 ('native' | 'kordoc', 기본 'native')
 */
export async function downloadHwpx(
  meetingId: string,
  engine: 'native' | 'kordoc' = 'native'
): Promise<void> {
  const url = `${API_BASE_URL}/api/meetings/${meetingId}/export?format=hwpx&engine=${engine}`;
  const token = typeof window !== 'undefined' ? localStorage.getItem('auth_token') : null;
  const response = await fetch(url, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });

  if (!response.ok) {
    let errorMessage = `다운로드 실패: ${response.status}`;
    try {
      const errorData = await response.json();
      if (errorData.detail) {
        errorMessage =
          typeof errorData.detail === 'string'
            ? errorData.detail
            : errorData.detail.message || JSON.stringify(errorData.detail);
      }
    } catch {
      /* ignore */
    }
    throw new ApiError(response.status, errorMessage);
  }

  const blob = await response.blob();
  const disposition = response.headers.get('Content-Disposition') || '';
  const filename = _filenameFromDisposition(disposition, '전자회의록.hwpx');

  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(a.href);
}

// =============================================================================
// VOD STT Processing
// =============================================================================

export interface SttTaskResponse {
  task_id: string | null;
  meeting_id: string;
  status: string;
  message: string;
}

export interface SttStatusResponse {
  task_id?: string | null;
  meeting_id: string;
  status: 'none' | 'pending' | 'running' | 'completed' | 'failed';
  progress: number;
  message: string;
  error: string | null;
}

/**
 * VOD STT 처리 시작
 *
 * @param meetingId - 회의 ID
 * @returns STT 태스크 정보
 */
export async function startSttProcessing(
  meetingId: string
): Promise<SttTaskResponse> {
  return apiClient<SttTaskResponse>(`/api/meetings/${meetingId}/stt`, {
    method: 'POST',
  });
}

/**
 * VOD STT 처리 상태 조회
 *
 * @param meetingId - 회의 ID
 * @returns STT 처리 상태 정보
 */
export async function getSttStatus(
  meetingId: string
): Promise<SttStatusResponse> {
  return apiClient<SttStatusResponse>(`/api/meetings/${meetingId}/stt/status`);
}

/**
 * 회의 단일 재생성 — VOD 자동 매칭 + 자막 삭제 + VOD STT + AI 교정
 * (admin 전용, 백그라운드 실행)
 */
export interface RegenerateResponse {
  meeting_id: string;
  status: 'started' | 'no_vod_match';
  vod_url?: string;
  matched_from_kms?: boolean;
  message: string;
}

export async function regenerateMeeting(
  meetingId: string
): Promise<RegenerateResponse> {
  return apiClient<RegenerateResponse>(
    `/api/meetings/${meetingId}/regenerate`,
    { method: 'POST' }
  );
}

// =============================================================================
// Subtitle Edit API
// =============================================================================

/**
 * 자막 수정 데이터 (단건)
 */
export interface SubtitleUpdateData {
  text?: string;
  speaker?: string;
}

/**
 * 배치 수정 아이템
 */
export interface SubtitleBatchItem {
  id: string;
  text?: string;
  speaker?: string;
}

/**
 * 배치 수정 응답
 */
export interface SubtitleBatchResponse {
  updated: number;
  items: SubtitleType[];
}

/**
 * 단건 자막 수정
 *
 * @param meetingId - 회의 ID
 * @param subtitleId - 자막 ID
 * @param data - 수정할 데이터 (text, speaker)
 * @returns 수정된 자막 객체
 */
export async function updateSubtitle(
  meetingId: string,
  subtitleId: string,
  data: SubtitleUpdateData
): Promise<SubtitleType> {
  return apiClient<SubtitleType>(
    `/api/meetings/${meetingId}/subtitles/${subtitleId}`,
    {
      method: 'PATCH',
      body: JSON.stringify(data),
    }
  );
}

/**
 * 배치 자막 수정
 *
 * @param meetingId - 회의 ID
 * @param items - 수정할 자막 배열
 * @returns 배치 수정 결과
 */
export async function updateSubtitlesBatch(
  meetingId: string,
  items: SubtitleBatchItem[]
): Promise<SubtitleBatchResponse> {
  return apiClient<SubtitleBatchResponse>(
    `/api/meetings/${meetingId}/subtitles`,
    {
      method: 'PATCH',
      body: JSON.stringify({ items }),
    }
  );
}

// =============================================================================
// Global Search API
// =============================================================================

/**
 * 검색 파라미터
 */
export interface SearchParams {
  q: string;
  date_from?: string;
  date_to?: string;
  speaker?: string;
  limit?: number;
  offset?: number;
}

/**
 * 검색 결과 아이템
 */
export interface SearchResultItem {
  subtitle_id: string;
  meeting_id: string;
  meeting_title: string;
  meeting_date: string;
  text: string;
  start_time: number;
  end_time: number;
  speaker: string | null;
  confidence: number | null;
}

/**
 * 검색 응답
 */
export interface SearchResponse {
  items: SearchResultItem[];
  total: number;
  limit: number;
  offset: number;
  query: string;
}

/**
 * 통합 검색
 *
 * @param params - 검색 파라미터
 * @returns 검색 결과
 */
export async function globalSearch(
  params: SearchParams
): Promise<SearchResponse> {
  const searchParams = new URLSearchParams({ q: params.q });
  if (params.date_from) searchParams.set('date_from', params.date_from);
  if (params.date_to) searchParams.set('date_to', params.date_to);
  if (params.speaker) searchParams.set('speaker', params.speaker);
  if (params.limit) searchParams.set('limit', params.limit.toString());
  if (params.offset) searchParams.set('offset', params.offset.toString());

  return apiClient<SearchResponse>(`/api/search?${searchParams.toString()}`);
}

// =============================================================================
// Bills API
// =============================================================================

/**
 * 의안 목록 조회 파라미터
 */
export interface GetBillsParams {
  committee?: string;
  status?: 'received' | 'reviewing' | 'decided' | 'promulgated';
  q?: string;
  limit?: number;
  offset?: number;
}

/**
 * 의안 목록 조회
 *
 * @param params - 검색/필터 파라미터
 * @returns 의안 목록 응답
 */
export async function getBills(
  params: GetBillsParams
): Promise<BillsResponse> {
  const searchParams = new URLSearchParams();
  if (params.committee) searchParams.set('committee', params.committee);
  if (params.status) searchParams.set('status', params.status);
  if (params.q) searchParams.set('q', params.q);
  if (params.limit) searchParams.set('limit', params.limit.toString());
  if (params.offset) searchParams.set('offset', params.offset.toString());

  return apiClient<BillsResponse>(`/api/bills?${searchParams.toString()}`);
}

/**
 * 의안 상세 조회 (관련 회의 포함)
 *
 * @param billId - 의안 ID
 * @returns 의안 상세 정보
 */
export async function getBill(billId: string): Promise<BillDetail> {
  return apiClient<BillDetail>(`/api/bills/${billId}`);
}

/**
 * 의안 등록
 *
 * @param data - 의안 생성 데이터
 * @returns 생성된 의안 정보
 */
export async function createBill(
  data: BillCreateData
): Promise<BillDetail> {
  return apiClient<BillDetail>('/api/bills', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

// =============================================================================
// Phase 6A: Meeting Management Extension
// =============================================================================

export interface MeetingUpdateData {
  title?: string;
  meeting_type?: string;
  committee?: string;
  meeting_date?: string;
}

export async function updateMeeting(
  meetingId: string,
  data: MeetingUpdateData
): Promise<Record<string, unknown>> {
  return apiClient(`/api/meetings/${meetingId}`, {
    method: 'PATCH',
    body: JSON.stringify(data),
  });
}

// Participants

export async function getParticipants(
  meetingId: string
): Promise<ParticipantType[]> {
  return apiClient<ParticipantType[]>(`/api/meetings/${meetingId}/participants`);
}

export async function addParticipant(
  meetingId: string,
  data: { councilor_id: string; name?: string; role?: string }
): Promise<ParticipantType> {
  return apiClient<ParticipantType>(`/api/meetings/${meetingId}/participants`, {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export async function removeParticipant(
  meetingId: string,
  participantId: string
): Promise<void> {
  await apiClient(`/api/meetings/${meetingId}/participants/${participantId}`, {
    method: 'DELETE',
  });
}

// Agendas

export async function getAgendas(
  meetingId: string
): Promise<AgendaType[]> {
  return apiClient<AgendaType[]>(`/api/meetings/${meetingId}/agendas`);
}

export async function addAgenda(
  meetingId: string,
  data: { order_num: number; title: string; description?: string }
): Promise<AgendaType> {
  return apiClient<AgendaType>(`/api/meetings/${meetingId}/agendas`, {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export async function updateAgenda(
  meetingId: string,
  agendaId: string,
  data: { order_num?: number; title?: string; description?: string }
): Promise<AgendaType> {
  return apiClient<AgendaType>(`/api/meetings/${meetingId}/agendas/${agendaId}`, {
    method: 'PATCH',
    body: JSON.stringify(data),
  });
}

export async function deleteAgenda(
  meetingId: string,
  agendaId: string
): Promise<void> {
  await apiClient(`/api/meetings/${meetingId}/agendas/${agendaId}`, {
    method: 'DELETE',
  });
}

export interface AgendaDraftResult {
  meeting_id: string;
  agendas: AgendaType[];
  agenda_summaries: { order_num: number; title: string; summary: string }[];
  summary_text: string;
  key_decisions: string[];
  action_items: string[];
  order_of_business_markdown: string;
  created_agendas: number;
}

/** AI 자막에서 안건 + 의사일정 내용 초안을 생성합니다(수동 트리거). */
export async function generateAgendaDraft(
  meetingId: string
): Promise<AgendaDraftResult> {
  return apiClient<AgendaDraftResult>(`/api/meetings/${meetingId}/agenda-draft`, {
    method: 'POST',
  });
}

// Material Requests (요구자료 — 의원 자료 제출 요구 감지 목록)

export async function getMaterialRequests(
  meetingId: string
): Promise<MaterialRequestType[]> {
  return apiClient<MaterialRequestType[]>(
    `/api/meetings/${meetingId}/material-requests`
  );
}

/** 회의 전체 자막을 AI로 스캔해 요구자료를 감지합니다 (VOD/사후 분석). */
export async function scanMaterialRequests(meetingId: string): Promise<{
  meeting_id: string;
  count: number;
  items: MaterialRequestType[];
}> {
  return apiClient(`/api/meetings/${meetingId}/material-requests/scan`, {
    method: 'POST',
  });
}

export async function updateMaterialRequest(
  meetingId: string,
  requestId: string,
  updates: Partial<
    Pick<MaterialRequestType, 'status' | 'summary' | 'councilor_name' | 'department'>
  >
): Promise<MaterialRequestType> {
  return apiClient(`/api/meetings/${meetingId}/material-requests/${requestId}`, {
    method: 'PATCH',
    body: JSON.stringify(updates),
  });
}

export async function createMaterialRequest(
  meetingId: string,
  body: {
    summary: string;
    councilor_name?: string;
    department?: string;
    request_text?: string;
    start_time?: number;
  }
): Promise<MaterialRequestType> {
  return apiClient(`/api/meetings/${meetingId}/material-requests`, {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

// Subtitle History

export async function getSubtitleHistory(
  meetingId: string,
  subtitleId: string
): Promise<SubtitleHistoryType[]> {
  return apiClient<SubtitleHistoryType[]>(
    `/api/meetings/${meetingId}/subtitles/${subtitleId}/history`
  );
}

// PII Masking

export interface PiiDetectResult {
  items: Array<{
    id: string;
    original_text: string;
    masked_text: string;
    pii_found: Array<{ type: string; original: string; masked: string }>;
  }>;
  total_pii_count: number;
}

export async function detectPii(
  meetingId: string
): Promise<PiiDetectResult> {
  return apiClient<PiiDetectResult>(
    `/api/meetings/${meetingId}/subtitles/detect-pii`,
    { method: 'POST' }
  );
}

export interface PiiApplyResult {
  updated: number;
  items: Array<{
    id: string;
    original_text: string;
    masked_text: string;
    pii_count: number;
  }>;
}

export async function applyPiiMask(
  meetingId: string,
  subtitleIds?: string[]
): Promise<PiiApplyResult> {
  return apiClient<PiiApplyResult>(
    `/api/meetings/${meetingId}/subtitles/apply-pii-mask`,
    {
      method: 'POST',
      body: JSON.stringify(subtitleIds ?? null),
    }
  );
}

// Transcript Status

export async function updateTranscriptStatus(
  meetingId: string,
  transcriptStatus: 'draft' | 'reviewing' | 'final'
): Promise<Record<string, unknown>> {
  return apiClient(`/api/meetings/${meetingId}/transcript-status`, {
    method: 'PATCH',
    body: JSON.stringify({ transcript_status: transcriptStatus }),
  });
}

// Publications

export async function getPublications(
  meetingId: string
): Promise<PublicationType[]> {
  return apiClient<PublicationType[]>(
    `/api/meetings/${meetingId}/publications`
  );
}

export async function createPublication(
  meetingId: string,
  data: { status: string; published_by?: string; notes?: string }
): Promise<PublicationType> {
  return apiClient<PublicationType>(
    `/api/meetings/${meetingId}/publications`,
    {
      method: 'POST',
      body: JSON.stringify(data),
    }
  );
}

// =============================================================================
// Phase 6B: Terminology Check + Grammar Check
// =============================================================================

// Terminology

export interface TermIssue {
  subtitle_id: string;
  wrong_term: string;
  correct_term: string;
  category: string | null;
}

export interface TermCheckResult {
  issues: TermIssue[];
  total_issues: number;
}

export async function checkTerminology(
  meetingId: string
): Promise<TermCheckResult> {
  return apiClient<TermCheckResult>(
    `/api/meetings/${meetingId}/subtitles/check-terminology`,
    { method: 'POST' }
  );
}

export interface TermApplyResult {
  updated: number;
  items: Array<{
    id: string;
    original_text: string;
    corrected_text: string;
  }>;
}

export async function applyTerminology(
  meetingId: string
): Promise<TermApplyResult> {
  return apiClient<TermApplyResult>(
    `/api/meetings/${meetingId}/subtitles/apply-terminology`,
    { method: 'POST' }
  );
}

// Grammar Check (AI)

export interface GrammarIssue {
  subtitle_id: string;
  original_text: string;
  corrected_text: string;
  changes: string[];
}

export interface GrammarCheckResult {
  issues: GrammarIssue[];
  total_issues: number;
}

export async function checkGrammar(
  meetingId: string
): Promise<GrammarCheckResult> {
  return apiClient<GrammarCheckResult>(
    `/api/meetings/${meetingId}/subtitles/check-grammar`,
    { method: 'POST' }
  );
}

export async function applyGrammarCorrections(
  meetingId: string,
  corrections: Array<{ subtitle_id: string; corrected_text: string }>
): Promise<{ updated: number }> {
  return apiClient<{ updated: number }>(
    `/api/meetings/${meetingId}/subtitles/apply-grammar`,
    {
      method: 'POST',
      body: JSON.stringify(corrections),
    }
  );
}

// =============================================================================
// Speaker Timeline
// =============================================================================

/**
 * 화자별 발언 타임라인 조회
 *
 * @param meetingId - 회의 ID
 * @returns 화자별 발언 통계 및 구간 목록
 */
export async function getSpeakersTimeline(
  meetingId: string
): Promise<SpeakersTimelineResponse> {
  return apiClient<SpeakersTimelineResponse>(
    `/api/meetings/${meetingId}/speakers`
  );
}

// =============================================================================
// Phase 7: Verification (대조관리)
// =============================================================================

/**
 * 대조관리 통계 조회
 *
 * @param meetingId - 회의 ID
 * @returns 검증 통계 정보
 */
export async function getVerificationStats(
  meetingId: string
): Promise<VerificationStatsType> {
  return apiClient<VerificationStatsType>(
    `/api/meetings/${meetingId}/subtitles/verification-stats`
  );
}

/**
 * 검토 대기열 조회
 *
 * @param meetingId - 회의 ID
 * @param params - 필터 파라미터 (신뢰도 임계값, 페이지네이션)
 * @returns 검토 대기 자막 목록
 */
export async function getReviewQueue(
  meetingId: string,
  params?: { confidence_threshold?: number; limit?: number; offset?: number }
): Promise<ReviewQueueResponse> {
  const searchParams = new URLSearchParams();
  if (params?.confidence_threshold !== undefined)
    searchParams.set('confidence_threshold', params.confidence_threshold.toString());
  if (params?.limit) searchParams.set('limit', params.limit.toString());
  if (params?.offset) searchParams.set('offset', params.offset.toString());
  const qs = searchParams.toString();
  return apiClient<ReviewQueueResponse>(
    `/api/meetings/${meetingId}/subtitles/review-queue${qs ? `?${qs}` : ''}`
  );
}

/**
 * 단건 자막 검증 상태 변경
 *
 * @param meetingId - 회의 ID
 * @param subtitleId - 자막 ID
 * @param status - 검증 상태 ('verified' | 'flagged' | 'unverified')
 * @returns 업데이트된 자막 객체
 */
export async function verifySubtitle(
  meetingId: string,
  subtitleId: string,
  status: 'verified' | 'flagged' | 'unverified'
): Promise<SubtitleType> {
  return apiClient<SubtitleType>(
    `/api/meetings/${meetingId}/subtitles/${subtitleId}/verify`,
    {
      method: 'PATCH',
      body: JSON.stringify({ status }),
    }
  );
}

/**
 * 배치 자막 검증
 *
 * @param meetingId - 회의 ID
 * @param subtitleIds - 자막 ID 배열
 * @param status - 검증 상태 (기본: 'verified')
 * @returns 배치 검증 결과
 */
export async function batchVerifySubtitles(
  meetingId: string,
  subtitleIds: string[],
  status: 'verified' | 'flagged' = 'verified'
): Promise<{ updated: number; items: SubtitleType[] }> {
  return apiClient(
    `/api/meetings/${meetingId}/subtitles/batch-verify`,
    {
      method: 'POST',
      body: JSON.stringify({ subtitle_ids: subtitleIds, status }),
    }
  );
}

// =============================================================================
// Phase 7: Meeting Summary (AI 요약)
// =============================================================================

/**
 * 회의록 AI 요약 생성
 *
 * @param meetingId - 회의 ID
 * @returns 생성된 요약 정보
 */
export async function generateSummary(
  meetingId: string,
  /** true = 앞부분만 본 옛 요약(complete=false)을 회의 전체로 다시 만든다. 완전한 요약에는 서버가 무시한다 */
  refresh = false
): Promise<MeetingSummaryType> {
  return apiClient<MeetingSummaryType>(
    `/api/meetings/${meetingId}/summary${refresh ? '?refresh=1' : ''}`,
    { method: 'POST' }
  );
}

/**
 * 회의록 요약 조회
 *
 * @param meetingId - 회의 ID
 * @returns 요약 정보
 */
export async function getSummary(
  meetingId: string
): Promise<MeetingSummaryType> {
  return apiClient<MeetingSummaryType>(
    `/api/meetings/${meetingId}/summary`
  );
}

/**
 * 회의록 요약 삭제
 *
 * @param meetingId - 회의 ID
 */
export async function deleteSummary(
  meetingId: string
): Promise<void> {
  await apiClient(
    `/api/meetings/${meetingId}/summary`,
    { method: 'DELETE' }
  );
}

// =============================================================================
// Phase 10: Minutes Management
// =============================================================================

/**
 * 회의 상태 업데이트 (회의록 작성 상태)
 *
 * @param meetingId - 회의 ID
 * @param status - 회의록 상태 ('draft' | 'reviewing' | 'final')
 * @returns 업데이트된 회의 정보
 */
export async function updateMeetingStatus(
  meetingId: string,
  status: 'draft' | 'reviewing' | 'final'
): Promise<Record<string, unknown>> {
  return apiClient(`/api/meetings/${meetingId}`, {
    method: 'PATCH',
    body: JSON.stringify({ transcript_status: status }),
  });
}

/**
 * 안건별 회의록 조회
 *
 * @param meetingId - 회의 ID
 * @returns 안건별로 분류된 자막 및 화자 그룹
 */
export async function getMinutesByAgenda(
  meetingId: string
): Promise<MinutesByAgendaResponse> {
  return apiClient(`/api/meetings/${meetingId}/minutes/by-agenda`);
}

// =============================================================================
// Phase 11: Agenda File Management
// =============================================================================



/**
 * 안건 첨부파일 목록 조회
 */
export async function getAgendaFiles(
  meetingId: string,
  agendaId: string
): Promise<AgendaFileType[]> {
  return apiClient<AgendaFileType[]>(
    `/api/meetings/${meetingId}/agendas/${agendaId}/files`
  );
}

/**
 * 안건 첨부파일 업로드
 */
export async function uploadAgendaFile(
  meetingId: string,
  agendaId: string,
  file: File
): Promise<AgendaFileType> {
  const formData = new FormData();
  formData.append('file', file);

  const url = `${API_BASE_URL}/api/meetings/${meetingId}/agendas/${agendaId}/files`;
  const response = await fetch(url, {
    method: 'POST',
    body: formData,
  });

  if (!response.ok) {
    let errorMessage = `업로드 실패: ${response.status}`;
    try {
      const errorData = await response.json();
      if (errorData.detail) {
        errorMessage = typeof errorData.detail === 'string' ? errorData.detail : (errorData.detail.message || JSON.stringify(errorData.detail));
      }
    } catch {
      // ignore
    }
    throw new ApiError(response.status, errorMessage);
  }

  return response.json() as Promise<AgendaFileType>;
}

/**
 * 안건 첨부파일 삭제
 */
export async function deleteAgendaFile(
  meetingId: string,
  agendaId: string,
  fileId: string
): Promise<void> {
  await apiClient(
    `/api/meetings/${meetingId}/agendas/${agendaId}/files/${fileId}`,
    { method: 'DELETE' }
  );
}

// =============================================================================
// Phase 11: Statistics Dashboard
// =============================================================================



/**
 * 통계 개요 조회
 */
export async function getStatsOverview(): Promise<StatsOverviewType> {
  return apiClient<StatsOverviewType>('/api/stats/overview');
}

/**
 * 화자별 통계 조회
 */
export async function getStatsSpeakers(): Promise<StatsSpeakerItem[]> {
  return apiClient<StatsSpeakerItem[]>('/api/stats/speakers');
}

/**
 * 월별 회의 통계 조회
 */
export async function getStatsMeetings(): Promise<StatsMeetingByMonth[]> {
  return apiClient<StatsMeetingByMonth[]>('/api/stats/meetings');
}

/**
 * 접속자 수 조회 (오늘 / 누적) — 집계만, 증가 없음
 */
export async function getVisitorStats(): Promise<VisitorStatsType> {
  return apiClient<VisitorStatsType>('/api/stats/visits');
}

/**
 * 접속 기록 (방문자 +1) 후 갱신된 접속자 수 반환.
 * 브라우저당 하루 1회만 호출할 것 (localStorage 중복 제거).
 */
export async function recordVisit(): Promise<VisitorStatsType> {
  return apiClient<VisitorStatsType>('/api/stats/visit', { method: 'POST' });
}

/**
 * 접속 통계 (2026-09-16) — 접속처·시간대·회의·기능.
 * site 를 주면 그 접속처만(드릴다운).
 */
export async function getAccessStats(days = 30, site?: string): Promise<AccessStatsType> {
  const params = new URLSearchParams({ days: String(days) });
  if (site) params.set('site', site);
  return apiClient<AccessStatsType>(`/api/stats/access?${params.toString()}`);
}

/**
 * 접속·시청 신호 1건 기록. IP 는 서버가 저장하지 않고 접속처 이름으로만 바꾼다.
 * 본 기능을 막지 않도록 실패는 조용히 삼킨다.
 */
export async function recordAccess(event: {
  kind: AccessEventKind;
  meetingId?: string | null;
  path?: string;
  visitorKey?: string | null;
}): Promise<void> {
  try {
    await apiClient('/api/stats/access', {
      method: 'POST',
      body: JSON.stringify({
        kind: event.kind,
        meeting_id: event.meetingId ?? null,
        path: event.path ?? null,
        visitor_key: event.visitorKey ?? null,
      }),
      keepalive: true,
    });
  } catch {
    // 통계는 부가 기능 — 실패해도 화면은 그대로 쓴다
  }
}

/**
 * 통계 리포트 내보내기
 */
export async function getStatsReport(
  dateFrom: string,
  dateTo: string,
  format: 'markdown' = 'markdown'
): Promise<void> {
  const url = `${API_BASE_URL}/api/stats/report?date_from=${dateFrom}&date_to=${dateTo}&format=${format}`;
  const response = await fetch(url);

  if (!response.ok) {
    let errorMessage = `리포트 생성 실패: ${response.status}`;
    try {
      const errorData = await response.json();
      if (errorData.detail) {
        errorMessage = typeof errorData.detail === 'string' ? errorData.detail : (errorData.detail.message || JSON.stringify(errorData.detail));
      }
    } catch {
      // ignore
    }
    throw new ApiError(response.status, errorMessage);
  }

  const blob = await response.blob();
  const disposition = response.headers.get('Content-Disposition') || '';
  const filenameMatch = disposition.match(/filename="?(.+?)"?$/);
  const filename = filenameMatch?.[1] || `통계리포트.md`;

  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(a.href);
}

// =============================================================================
// Phase 11: Notification
// =============================================================================

/**
 * 알림 목록 조회
 */
export async function getNotifications(
  limit = 20
): Promise<NotificationType[]> {
  return apiClient<NotificationType[]>(`/api/notifications?limit=${limit}`);
}

/**
 * 알림 읽음 처리
 */
export async function markNotificationRead(id: string): Promise<void> {
  await apiClient(`/api/notifications/${id}/read`, { method: 'PATCH' });
}

// =============================================================================
// Phase 12: Stenography Management
// =============================================================================

/**
 * 속기록 목록 조회
 */
export async function getStenographyRecords(
  meetingId: string
): Promise<StenographyRecord[]> {
  return apiClient<StenographyRecord[]>(
    `/api/meetings/${meetingId}/stenography`
  );
}

/**
 * 속기록 등록 (텍스트 또는 파일)
 */
export async function createStenographyRecord(
  meetingId: string,
  data: FormData
): Promise<StenographyRecord> {
  const url = `${API_BASE_URL}/api/meetings/${meetingId}/stenography`;
  const response = await fetch(url, {
    method: 'POST',
    body: data,
  });

  if (!response.ok) {
    let errorMessage = `등록 실패: ${response.status}`;
    try {
      const errorData = await response.json();
      if (errorData.detail) {
        errorMessage = typeof errorData.detail === 'string' ? errorData.detail : (errorData.detail.message || JSON.stringify(errorData.detail));
      }
    } catch {
      // ignore
    }
    throw new ApiError(response.status, errorMessage);
  }

  return response.json() as Promise<StenographyRecord>;
}

/**
 * 속기록 수정
 */
export async function updateStenographyRecord(
  meetingId: string,
  recordId: string,
  data: Partial<StenographyRecord>
): Promise<StenographyRecord> {
  return apiClient<StenographyRecord>(
    `/api/meetings/${meetingId}/stenography/${recordId}`,
    {
      method: 'PATCH',
      body: JSON.stringify(data),
    }
  );
}

/**
 * 속기록 삭제
 */
export async function deleteStenographyRecord(
  meetingId: string,
  recordId: string
): Promise<void> {
  await apiClient(`/api/meetings/${meetingId}/stenography/${recordId}`, {
    method: 'DELETE',
  });
}

/**
 * 속기록-STT 자막 비교
 */
export async function compareStenography(
  meetingId: string,
  recordId: string
): Promise<StenographyComparison> {
  return apiClient<StenographyComparison>(
    `/api/meetings/${meetingId}/stenography/${recordId}/compare`
  );
}

/**
 * 속기록 수정 이력 조회
 */
export async function getStenographyHistory(
  meetingId: string,
  recordId: string,
  limit = 50,
  offset = 0
): Promise<StenographyEditHistoryResponse> {
  return apiClient<StenographyEditHistoryResponse>(
    `/api/meetings/${meetingId}/stenography/${recordId}/history?limit=${limit}&offset=${offset}`
  );
}

/**
 * AI 화자 자동 구분
 */
export async function aiDetectSpeakers(
  meetingId: string,
  recordId: string
): Promise<{ suggestions: SpeakerSuggestion[]; count: number }> {
  return apiClient<{ suggestions: SpeakerSuggestion[]; count: number }>(
    `/api/meetings/${meetingId}/stenography/${recordId}/ai/speakers`,
    { method: 'POST' }
  );
}

/**
 * AI 맞춤법 교정
 */
export async function aiProofread(
  meetingId: string,
  recordId: string
): Promise<{ corrections: ProofreadCorrection[]; count: number }> {
  return apiClient<{ corrections: ProofreadCorrection[]; count: number }>(
    `/api/meetings/${meetingId}/stenography/${recordId}/ai/proofread`,
    { method: 'POST' }
  );
}

/**
 * AI 문단 자동 구분
 */
export async function aiDetectParagraphs(
  meetingId: string,
  recordId: string
): Promise<{ paragraphs: ParagraphSuggestion[]; count: number }> {
  return apiClient<{ paragraphs: ParagraphSuggestion[]; count: number }>(
    `/api/meetings/${meetingId}/stenography/${recordId}/ai/paragraphs`,
    { method: 'POST' }
  );
}

/**
 * 전체 속기록 목록 (대시보드)
 */
export async function getAllStenographyRecords(
  statusFilter?: string,
  limit = 50,
  offset = 0
): Promise<{ items: StenographyDashboardItem[]; total: number }> {
  const params = new URLSearchParams();
  if (statusFilter) params.set('status_filter', statusFilter);
  params.set('limit', String(limit));
  params.set('offset', String(offset));
  return apiClient<{ items: StenographyDashboardItem[]; total: number }>(
    `/api/stenography?${params.toString()}`
  );
}

/**
 * 속기록 라인 목록 조회
 */
export async function getStenographyLines(
  meetingId: string,
  recordId: string
): Promise<StenographyLine[]> {
  return apiClient<StenographyLine[]>(
    `/api/meetings/${meetingId}/stenography/${recordId}/lines`
  );
}

/**
 * 속기록 라인 배치 수정
 */
export async function updateStenographyLines(
  meetingId: string,
  recordId: string,
  items: StenographyLineUpdate[]
): Promise<{ updated: number; items: StenographyLine[] }> {
  return apiClient<{ updated: number; items: StenographyLine[] }>(
    `/api/meetings/${meetingId}/stenography/${recordId}/lines`,
    {
      method: 'PATCH',
      body: JSON.stringify({ items }),
    }
  );
}

/**
 * STT 자막에서 속기록 라인 생성
 */
export async function bootstrapStenographyFromSubtitles(
  meetingId: string,
  recordId: string
): Promise<{ lines: StenographyLine[]; count: number }> {
  return apiClient<{ lines: StenographyLine[]; count: number }>(
    `/api/meetings/${meetingId}/stenography/${recordId}/lines/from-subtitles`,
    { method: 'POST' }
  );
}

/**
 * 텍스트에서 속기록 라인 임포트
 */
export async function importStenographyFromText(
  meetingId: string,
  recordId: string,
  text: string,
  delimiter = '\n'
): Promise<{ lines: StenographyLine[]; count: number }> {
  return apiClient<{ lines: StenographyLine[]; count: number }>(
    `/api/meetings/${meetingId}/stenography/${recordId}/lines/import-from-text`,
    {
      method: 'POST',
      body: JSON.stringify({ text, delimiter }),
    }
  );
}

// =============================================================================
// Phase 12: Collaborative Editing
// =============================================================================

/**
 * 편집 세션 목록 조회
 */
export async function getEditSessions(
  meetingId: string
): Promise<EditSession[]> {
  return apiClient<EditSession[]>(`/api/meetings/${meetingId}/edit-sessions`);
}

/**
 * 편집 세션 생성 (편집 시작)
 */
export async function createEditSession(
  meetingId: string,
  editorName: string
): Promise<EditSession> {
  return apiClient<EditSession>(`/api/meetings/${meetingId}/edit-sessions`, {
    method: 'POST',
    body: JSON.stringify({ editor_name: editorName }),
  });
}

/**
 * 편집 세션 Heartbeat (last_active_at 갱신)
 */
export async function updateEditSession(
  meetingId: string,
  sessionId: string
): Promise<void> {
  await apiClient(`/api/meetings/${meetingId}/edit-sessions/${sessionId}`, {
    method: 'PATCH',
  });
}

/**
 * 편집 세션 종료
 */
export async function deleteEditSession(
  meetingId: string,
  sessionId: string
): Promise<void> {
  await apiClient(`/api/meetings/${meetingId}/edit-sessions/${sessionId}`, {
    method: 'DELETE',
  });
}

/**
 * 자막 코멘트 목록 조회
 */
export async function getSubtitleComments(
  meetingId: string,
  subtitleId?: string
): Promise<SubtitleComment[]> {
  const qs = subtitleId ? `?subtitle_id=${subtitleId}` : '';
  return apiClient<SubtitleComment[]>(
    `/api/meetings/${meetingId}/subtitle-comments${qs}`
  );
}

/**
 * 자막 코멘트 생성
 */
export async function createSubtitleComment(
  meetingId: string,
  subtitleId: string,
  authorName: string,
  content: string
): Promise<SubtitleComment> {
  return apiClient<SubtitleComment>(
    `/api/meetings/${meetingId}/subtitle-comments`,
    {
      method: 'POST',
      body: JSON.stringify({ subtitle_id: subtitleId, author_name: authorName, content }),
    }
  );
}

/**
 * 코멘트 해결 상태 토글
 */
export async function toggleCommentResolved(
  meetingId: string,
  commentId: string,
  resolved: boolean
): Promise<void> {
  await apiClient(`/api/meetings/${meetingId}/subtitle-comments/${commentId}`, {
    method: 'PATCH',
    body: JSON.stringify({ resolved }),
  });
}

// =============================================================================
// Phase 11B: AI Assistant
// =============================================================================



/**
 * AI 채팅 - RAG Q&A
 */
export interface AiSearchScope {
  /** 여러 회의 검색 범위(일). 기본 30 */
  days?: number;
  /** 위원회 이름 일부(예: 도시환경) */
  committee?: string;
}

export async function aiChat(
  question: string,
  sessionId?: string,
  meetingContextId?: string,
  scope?: AiSearchScope
): Promise<AiChatResponse> {
  return apiClient<AiChatResponse>('/api/ai/chat', {
    method: 'POST',
    body: JSON.stringify({
      question,
      session_id: sessionId || null,
      meeting_context_id: meetingContextId || null,
      scope: !meetingContextId && scope ? scope : null,
    }),
  });
}

export interface AiChatStreamOptions {
  /** 글자 조각이 올 때마다 — 마크다운 정리 전 원문이다(최종 정리본은 반환값의 answer) */
  onDelta: (text: string) => void;
  /** 에이전트가 도구로 찾는 중("자막 검색 중… '보안'") */
  onStatus?: (text: string) => void;
  /** 흘려보낸 반쪽 글을 지우라(도구 호출로 바뀜) */
  onReset?: () => void;
  signal?: AbortSignal;
  /** 회의를 고르지 않은 질문의 검색 범위(화면에서는 2026-09-15 에 없앴다 — 호환용) */
  scope?: AiSearchScope;
}

/** SSE 한 덩어리("event: x\ndata: {...}") → {event, data} */
export function parseSseBlock(block: string): { event: string; data: unknown } | null {
  let event = 'message';
  const dataLines: string[] = [];
  for (const line of block.split('\n')) {
    if (line.startsWith('event:')) event = line.slice(6).trim();
    else if (line.startsWith('data:')) dataLines.push(line.slice(5).trimStart());
  }
  if (!dataLines.length) return null;
  try {
    return { event, data: JSON.parse(dataLines.join('\n')) };
  } catch {
    return null;
  }
}

/**
 * AI 답을 글자 조각으로 받는다 — POST /api/ai/chat/stream (text/event-stream, 2026-09-15 "AI 답변 속도").
 * 한 번에 받던 aiChat 은 1,000~2,500자 답이 끝날 때까지 아무것도 안 보였다.
 * 한도(429)·세션·회의 오류는 흐름이 열리기 전에 일반 오류(ApiError)로 온다. 도중 실패는 error 이벤트 → ApiError(502).
 */
export async function aiChatStream(
  question: string,
  sessionId: string | undefined,
  meetingContextId: string | undefined,
  { onDelta, onStatus, onReset, signal, scope }: AiChatStreamOptions
): Promise<AiChatResponse> {
  const token = typeof window !== 'undefined' ? localStorage.getItem('auth_token') : null;
  const response = await fetch(`${API_BASE_URL}/api/ai/chat/stream`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
      'ngrok-skip-browser-warning': '1',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...guestHeaders(token),
    },
    body: JSON.stringify({
      question,
      session_id: sessionId || null,
      meeting_context_id: meetingContextId || null,
      scope: !meetingContextId && scope ? scope : null,
    }),
    signal,
  });
  if (!response.ok) throw await readApiError(response);
  if (!response.body) throw new ApiError(502, 'AI 응답을 받을 수 없는 브라우저입니다. 다시 시도해 주세요.');

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let final: AiChatResponse | null = null;
  // 한 덩어리를 처리하고, done 이면 최종 응답을 돌려준다
  const handle = (block: string): AiChatResponse | null => {
    const ev = parseSseBlock(block);
    if (!ev) return null;
    const data = ev.data as Record<string, unknown>;
    if (ev.event === 'delta' && typeof data.t === 'string') onDelta(data.t);
    else if (ev.event === 'status' && typeof data.t === 'string') onStatus?.(data.t);
    else if (ev.event === 'reset') onReset?.();
    else if (ev.event === 'done') return data as unknown as AiChatResponse;
    else if (ev.event === 'error') {
      throw new ApiError(502, typeof data.detail === 'string' ? data.detail : 'AI 응답 생성 중 오류가 발생했습니다.');
    }
    return null;
  };
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n');
    let cut = buffer.indexOf('\n\n');
    while (cut >= 0) {
      final = handle(buffer.slice(0, cut)) ?? final;
      buffer = buffer.slice(cut + 2);
      cut = buffer.indexOf('\n\n');
    }
  }
  if (buffer.trim()) final = handle(buffer) ?? final;
  if (!final) throw new ApiError(502, 'AI 응답이 중간에 끊겼습니다. 다시 시도해 주세요.');
  return final;
}

// ── 부서별 회의 문서(2026-09-15) — 모니터링·자료요구 목록·요구자료 표지·보도자료 HWPX, 버튼으로만 ──
export type MeetingDocumentKind = 'monitoring' | 'datareq-list' | 'datareq-cover' | 'press';

export interface MeetingDocumentOptions {
  committee_short: string;
  departments: string[];
  material_requests: { id: string; councilor: string; summary: string | null; department: string }[];
  has_summary: boolean;
  has_subtitles: boolean;
}

export function getMeetingDocumentOptions(meetingId: string): Promise<MeetingDocumentOptions> {
  return apiClient<MeetingDocumentOptions>(`/api/meetings/${meetingId}/documents/options`);
}

/** 문서를 만들어 내려받는다(HWPX, 표지 묶음은 ZIP). 파일 이름은 서버 Content-Disposition 을 따른다. */
export async function downloadMeetingDocument(
  meetingId: string,
  kind: MeetingDocumentKind,
  opts: { department?: string; requestId?: string } = {}
): Promise<string> {
  const params = new URLSearchParams();
  if (opts.department) params.set('department', opts.department);
  if (opts.requestId) params.set('request_id', opts.requestId);
  const token = typeof window !== 'undefined' ? localStorage.getItem('auth_token') : null;
  const response = await fetch(
    `${API_BASE_URL}/api/meetings/${meetingId}/documents/${kind}${params.toString() ? `?${params}` : ''}`,
    {
      method: 'POST',
      headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}), ...guestHeaders(token) },
    }
  );
  if (!response.ok) throw await readApiError(response);
  const blob = await response.blob();
  const fallback = kind === 'datareq-cover' && !opts.requestId ? '요구자료 표지.zip' : '회의 문서.hwpx';
  const filename = _filenameFromDisposition(response.headers.get('Content-Disposition') || '', fallback);
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(a.href);
  return filename;
}

// GET /api/ai/conversations/shared(전체 공개 이력)는 2026-09-14 에 없앴다 — 본인 세션만 getAiConversations 로 본다.

// aiSummary(/api/ai/summary)는 2026-09-14 에 없앴다 — 요약은 generateSummary/getSummary(/api/meetings/{id}/summary)가 정본.

/**
 * 본인 AI 대화 세션 목록 (로그인 AI 역할 또는 의회망 손님 — 손님은 브라우저 표식 X-Guest-Id 기준)
 */
export async function getAiConversations(): Promise<AiConversationSession[]> {
  return apiClient<AiConversationSession[]>('/api/ai/conversations');
}

/**
 * 본인 AI 대화 세션 이력(출처 포함). 남의 세션은 404
 */
export async function getAiConversation(
  sessionId: string
): Promise<AiConversationItem[]> {
  return apiClient<AiConversationItem[]>(
    `/api/ai/conversations/${sessionId}`
  );
}

// =============================================================================
// Admin: External API Status
// =============================================================================



/**
 * 외부 API 상태 조회
 */
export async function getApiStatus(): Promise<ApiStatusResponse> {
  return apiClient<ApiStatusResponse>('/api/admin/api-status');
}

/**
 * 채널 STT 시작
 */
export async function startChannelStt(channelId: string, options?: { streamUrl?: string }): Promise<{ message: string; status?: string }> {
  const params = new URLSearchParams();
  if (options?.streamUrl) params.set('stream_url', options.streamUrl);
  const query = params.toString() ? `?${params.toString()}` : '';
  return apiClient<{ message: string; status?: string }>(`/api/channels/${channelId}/stt/start${query}`, {
    method: 'POST',
  });
}

/**
 * 채널 STT 중지
 */
export async function stopChannelStt(channelId: string): Promise<{ message: string }> {
  return apiClient<{ message: string }>(`/api/channels/${channelId}/stt/stop`, { method: 'POST' });
}

/**
 * 자막 분할
 */
export async function splitSubtitle(meetingId: string, subtitleId: string, splitTime: number): Promise<{ original: SubtitleType; new: SubtitleType }> {
  return apiClient<{ original: SubtitleType; new: SubtitleType }>(`/api/meetings/${meetingId}/subtitles/${subtitleId}/split`, {
    method: 'POST',
    body: JSON.stringify({ split_time: splitTime }),
  });
}

/**
 * 자막 병합
 */
export async function mergeSelectedSubtitles(meetingId: string, subtitleIds: string[]): Promise<{ merged: SubtitleType }> {
  return apiClient<{ merged: SubtitleType }>(`/api/meetings/${meetingId}/subtitles/merge`, {
    method: 'POST',
    body: JSON.stringify({ subtitle_ids: subtitleIds }),
  });
}

/**
 * 화자 병합
 */
export async function mergeSpeakers(meetingId: string, fromSpeaker: string, toSpeaker: string): Promise<{ updated: number }> {
  return apiClient<{ updated: number }>(`/api/meetings/${meetingId}/speakers/merge`, {
    method: 'POST',
    body: JSON.stringify({ from_speaker: fromSpeaker, to_speaker: toSpeaker }),
  });
}

/**
 * 의원 목록 조회
 */
// ── 얼굴로 의원 찾기 (2026-09-16) ────────────────────────────────────────────
export interface FaceMatchType {
  /** 화면 대비 비율 [x, y, w, h] — 보낸 그림과 화면 크기가 달라도 그대로 쓸 수 있다 */
  box: [number, number, number, number];
  det_score: number;
  face_px: number;
  score: number;
  margin: number;
  councilor_id: string | null;
  name: string | null;
  party: string | null;
  district: string | null;
  confident: boolean;
  /** face = 얼굴만으로, face+speaker = 지금 발언자와 일치 */
  basis: 'face' | 'face+speaker';
  reason?: string;
}

export interface FaceIdentifyResponse {
  faces: FaceMatchType[];
  width?: number;
  height?: number;
  committee?: string | null;
  elapsed_ms?: number;
  error?: string;
}

/** 캡처한 화면 한 장을 보내 의원을 식별한다. */
export async function identifyFaces(
  image: Blob,
  opts: { channelId?: string; speakerHint?: string | null } = {}
): Promise<FaceIdentifyResponse> {
  const form = new FormData();
  form.append('file', image, 'frame.jpg');
  if (opts.channelId) form.append('channel_id', opts.channelId);
  if (opts.speakerHint) form.append('speaker_hint', opts.speakerHint);
  // FormData 는 Content-Type 을 브라우저가 경계문자와 함께 직접 정해야 해서 apiClient 를 쓰지 않는다
  const token = typeof window !== 'undefined' ? localStorage.getItem('auth_token') : null;
  const response = await fetch(`${API_BASE_URL}/api/faces/identify`, {
    method: 'POST',
    body: form,
    headers: {
      'ngrok-skip-browser-warning': '1',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...guestHeaders(token),
    },
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    throw new Error(detail.detail || '의원을 찾지 못했습니다.');
  }
  return response.json();
}

/** 브라우저가 화면을 못 뜰 때(iOS 네이티브 HLS 등) 서버가 직접 떠서 식별한다. */
export async function identifyFacesOnChannel(
  channelId: string,
  speakerHint?: string | null
): Promise<FaceIdentifyResponse> {
  const q = speakerHint ? `?speaker_hint=${encodeURIComponent(speakerHint)}` : '';
  return apiClient<FaceIdentifyResponse>(`/api/channels/${channelId}/identify-faces${q}`, {
    method: 'POST',
  });
}

export interface CouncilorSpeechType {
  subtitle_id: string;
  meeting_id: string;
  meeting_title: string | null;
  committee: string | null;
  meeting_date: string | null;
  start_time: number | null;
  speaker: string | null;
  text: string;
}

export interface CouncilorDetailType {
  councilor: CouncilorType & {
    district_detail?: string | null;
    term?: number | null;
    office_number?: string | null;
    email?: string | null;
    homepage_url?: string | null;
  };
  career: string[];
  positions: string[];
  recent_speeches: CouncilorSpeechType[];
}

/** 의원 상세 — 약력·소속 위원회·최근 발언. */
export function getCouncilorDetail(
  councilorId: string,
  speeches = 8
): Promise<CouncilorDetailType> {
  return apiClient<CouncilorDetailType>(
    `/api/councilors/${councilorId}/detail?speeches=${speeches}`
  );
}

export async function getCouncilors(params?: { committee?: string; committeeCode?: string; q?: string }): Promise<CouncilorType[]> {
  const searchParams = new URLSearchParams();
  if (params?.committee) searchParams.set('committee', params.committee);
  // 예산결산특별위원회·윤리특별위원회는 의원정보 API 에 없어 코드로 홈페이지 명단을 읽는다
  if (params?.committeeCode) searchParams.set('committee_code', params.committeeCode);
  if (params?.q) searchParams.set('q', params.q);
  const query = searchParams.toString();
  const result = await apiClient<{ items: CouncilorType[] } | CouncilorType[]>(`/api/councilors${query ? `?${query}` : ''}`);
  return Array.isArray(result) ? result : result.items;
}

/**
 * AI 화자 이름 제안
 */
export async function suggestSpeakerNames(meetingId: string): Promise<{ suggestions: Array<{ speaker: string; suggested_name: string; confidence: number }> }> {
  return apiClient(`/api/meetings/${meetingId}/speakers/suggest`, { method: 'POST' });
}

// ─── 의원 목소리 샘플 (실명 화자 식별) ──────────────────────────────────

export interface VoiceprintType {
  councilor_id: string;
  councilor_name: string;
  committee: string | null;
  duration_ms: number | null;
  source: string;
  is_chair?: boolean;
  created_at?: string;
  updated_at?: string;
}

/** 등록된 목소리 목록 */
export async function getVoiceprints(): Promise<{ voiceprints: VoiceprintType[]; total: number; max_per_committee: number }> {
  return apiClient('/api/voiceprints');
}

/** 의원 목소리 등록 (음성 파일 업로드, 16kHz wav로 정규화·2~10초) */
export async function enrollVoiceprint(councilorId: string, file: File): Promise<{ status: string; councilor_name: string; duration_ms: number }> {
  const formData = new FormData();
  formData.append('file', file);
  const token = typeof window !== 'undefined' ? localStorage.getItem('auth_token') : null;
  const response = await fetch(`${API_BASE_URL}/api/councilors/${councilorId}/voiceprint`, {
    method: 'POST',
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body: formData,
  });
  if (!response.ok) {
    let msg = `등록 실패: ${response.status}`;
    try {
      const e = await response.json();
      if (e.detail) msg = typeof e.detail === 'string' ? e.detail : JSON.stringify(e.detail);
    } catch { /* ignore */ }
    throw new ApiError(response.status, msg);
  }
  return response.json();
}

/** 의원 목소리 삭제 */
export async function deleteVoiceprint(councilorId: string): Promise<{ status: string }> {
  return apiClient(`/api/councilors/${councilorId}/voiceprint`, { method: 'DELETE' });
}

/** 위원회 위원장 지정/해제 (위원회당 1명, 실시간 식별 시 항상 포함) */
export async function setVoiceprintChair(councilorId: string, isChair: boolean): Promise<{ status: string; is_chair: boolean }> {
  return apiClient(`/api/councilors/${councilorId}/voiceprint/chair`, {
    method: 'PATCH',
    body: JSON.stringify({ is_chair: isChair }),
  });
}

// =============================================================================
// Final Transcript (AI 최종본)
// =============================================================================

/**
 * AI 최종본 생성 시작 (백그라운드 태스크)
 *
 * @param meetingId - 회의 ID
 * @param preciseMode - 정밀 모드 여부 (기본: false)
 * @returns 생성 시작 결과
 */
export async function generateFinalTranscript(
  meetingId: string,
  preciseMode = false
): Promise<{ status: string; meeting_id: string }> {
  return apiClient<{ status: string; meeting_id: string }>(
    `/api/meetings/${meetingId}/final-transcript`,
    {
      method: 'POST',
      body: JSON.stringify({ precise_mode: preciseMode }),
    }
  );
}

export interface FinalTranscriptStatus {
  status: 'idle' | 'pending' | 'running' | 'completed' | 'failed';
  progress: number;
  message: string;
  error?: string | null;
  record_id: string | null;
}

/**
 * AI 최종본 생성 상태 조회
 *
 * @param meetingId - 회의 ID
 * @returns 생성 상태 정보
 */
export async function getFinalTranscriptStatus(
  meetingId: string
): Promise<FinalTranscriptStatus> {
  return apiClient<FinalTranscriptStatus>(
    `/api/meetings/${meetingId}/final-transcript/status`
  );
}

export default apiClient;

// =============================================================================
// AI 자막 일괄 생성 (서버 측 순차 큐 — 페이지를 닫아도 계속 처리)
// =============================================================================

export interface SttBatchStatus {
  running: boolean;
  current: string | null;
  /** 처리 중인 회의의 세부 진행률 — 다운로드/청크 전사/저장 단계와 0~1 진행도 */
  current_progress?: {
    progress: number;
    message: string;
    status: string;
  } | null;
  pending: string[];
  done: string[];
  failed: { meeting_id: string; reason: string }[];
}

export async function startSttBatch(meetingIds: string[]): Promise<{ status: string; total: number }> {
  return apiClient(`/api/meetings/stt-batch`, {
    method: 'POST',
    body: JSON.stringify({ meeting_ids: meetingIds }),
  });
}

export async function getSttBatchStatus(): Promise<SttBatchStatus> {
  return apiClient(`/api/meetings/stt-batch/status`);
}

// =============================================================================
// API 사용량·비용 추정 (관리자)
// =============================================================================

export interface UsageCostRow {
  committee: string;
  meetings: number;
  live_minutes: number;
  vod_minutes: number;
  live_cost_usd: number;
  vod_cost_usd: number;
  live_cost_krw: number;
  vod_cost_krw: number;
  total_cost_krw: number;
  live_api_calls_est: number;
  vod_api_calls_est: number;
}

export interface UsageCostsResponse {
  period_days: number;
  since: string;
  usd_krw: number;
  rates: { live_per_hour_usd: number; vod_per_hour_usd: number };
  committees: UsageCostRow[];
  totals: UsageCostRow;
  note: string;
}

export async function getUsageCosts(days = 30): Promise<UsageCostsResponse> {
  return apiClient(`/api/admin/usage-costs?days=${days}`);
}

// =============================================================================
// 발언영상 추출 (의원별 발언 구간 클립)
// =============================================================================

/**
 * 화자별 발언 구간 목록 조회 (클립 추출용 병합 구간)
 *
 * @param meetingId - 회의 ID
 */
export async function getSpeakerSegments(
  meetingId: string
): Promise<SpeakerSegmentsResponseType> {
  return apiClient<SpeakerSegmentsResponseType>(
    `/api/meetings/${meetingId}/speakers/segments`
  );
}

/**
 * 발언 구간 단일 클립(mp4) 다운로드.
 *
 * KMS 원본에서 구간을 잘라 전송하므로 구간 길이만큼 시간이 걸릴 수 있습니다.
 * 로그인이 필요합니다(401).
 *
 * @param meetingId - 회의 ID
 * @param start - 시작 시각 (초)
 * @param end - 종료 시각 (초)
 */
export async function downloadSpeechClip(
  meetingId: string,
  start: number,
  end: number
): Promise<void> {
  const url = `${API_BASE_URL}/api/meetings/${meetingId}/speakers/clip?start=${start}&end=${end}`;
  const token = typeof window !== 'undefined' ? localStorage.getItem('auth_token') : null;
  const response = await fetch(url, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });

  if (!response.ok) {
    let errorMessage = `다운로드 실패: ${response.status}`;
    try {
      const errorData = await response.json();
      if (errorData.detail) {
        errorMessage =
          typeof errorData.detail === 'string'
            ? errorData.detail
            : errorData.detail.message || JSON.stringify(errorData.detail);
      }
    } catch {
      /* ignore */
    }
    throw new ApiError(response.status, errorMessage);
  }

  const blob = await response.blob();
  const disposition = response.headers.get('Content-Disposition') || '';
  const filename = _filenameFromDisposition(
    disposition,
    `발언영상_${Math.floor(start)}-${Math.floor(end)}.mp4`
  );

  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(a.href);
}

/**
 * 선택 구간 병합 클립 작업 생성 (백그라운드 처리)
 *
 * @param meetingId - 회의 ID
 * @param segments - 병합할 구간 목록 (초 단위 start/end)
 */
export async function createClipJob(
  meetingId: string,
  segments: Array<{ start: number; end: number }>
): Promise<{ job_id: string }> {
  return apiClient<{ job_id: string }>(
    `/api/meetings/${meetingId}/speakers/clip-jobs`,
    {
      method: 'POST',
      body: JSON.stringify({ segments, merge: true }),
    }
  );
}

/**
 * 병합 클립 작업 상태 조회
 *
 * @param meetingId - 회의 ID
 * @param jobId - 작업 ID
 */
export async function getClipJob(
  meetingId: string,
  jobId: string
): Promise<ClipJobStatusType> {
  return apiClient<ClipJobStatusType>(
    `/api/meetings/${meetingId}/speakers/clip-jobs/${jobId}`
  );
}

/**
 * 병합 클립 작업 결과(mp4) 다운로드
 *
 * @param meetingId - 회의 ID
 * @param jobId - 작업 ID
 */
export async function downloadClipJobResult(
  meetingId: string,
  jobId: string
): Promise<void> {
  const url = `${API_BASE_URL}/api/meetings/${meetingId}/speakers/clip-jobs/${jobId}/download`;
  const token = typeof window !== 'undefined' ? localStorage.getItem('auth_token') : null;
  const response = await fetch(url, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });

  if (!response.ok) {
    let errorMessage = `다운로드 실패: ${response.status}`;
    try {
      const errorData = await response.json();
      if (errorData.detail) {
        errorMessage =
          typeof errorData.detail === 'string'
            ? errorData.detail
            : errorData.detail.message || JSON.stringify(errorData.detail);
      }
    } catch {
      /* ignore */
    }
    throw new ApiError(response.status, errorMessage);
  }

  const blob = await response.blob();
  const disposition = response.headers.get('Content-Disposition') || '';
  const filename = _filenameFromDisposition(disposition, '발언영상_병합.mp4');

  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(a.href);
}

// =============================================================================
// 영상추출기 배포 (Tools — exe 배포/자동업데이트 채널)
// =============================================================================

/**
 * 영상추출기 최신 배포 버전 조회 (공개).
 *
 * @returns 배포 매니페스트 — 배포된 버전이 없으면(404) null
 */
// =============================================================================
// 발언영상 클립 워크벤치 (2026-09) — /api/meetings/{id}/clip-index · clip-offset · clip-jobs · /api/clip-jobs
// 기존 speakers/clip* 함수(위)는 /vod/[id]/speaker 화면이 아직 쓴다 — 정리는 후속.
// =============================================================================

/** 의원별 발언 구간 인덱스 — 공식(KMS) → AI 자막(잠정) → 실시간 자막(초안) */
export async function getClipIndex(meetingId: string): Promise<ClipIndexType> {
  return apiClient<ClipIndexType>(`/api/meetings/${meetingId}/clip-index`);
}

/** 초안 인덱스 시간축 보정 저장 (회의당 1회) */
export async function updateClipOffset(
  meetingId: string,
  timeOffset: number
): Promise<{ meeting_id: string; time_offset: number }> {
  return apiClient(`/api/meetings/${meetingId}/clip-offset`, {
    method: 'PUT',
    body: JSON.stringify({ time_offset: timeOffset }),
  });
}

/** 클립 추출 잡 생성 (영속 · 7일 보관) → 202 */
export async function createClipJobV2(
  meetingId: string,
  body: ClipJobCreateRequestType
): Promise<{ job_id: string; status: string; queue_position: number }> {
  return apiClient(`/api/meetings/${meetingId}/clip-jobs`, {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

export async function getClipJobV2(meetingId: string, jobId: string): Promise<ClipJobType> {
  return apiClient<ClipJobType>(`/api/meetings/${meetingId}/clip-jobs/${jobId}`);
}

export async function deleteClipJob(
  meetingId: string,
  jobId: string
): Promise<{ job_id: string; status: string }> {
  return apiClient(`/api/meetings/${meetingId}/clip-jobs/${jobId}`, { method: 'DELETE' });
}

export async function listClipJobs(p: {
  scope?: 'mine' | 'all';
  days?: number;
  meetingId?: string | null;
  limit?: number;
  offset?: number;
} = {}): Promise<ClipJobListResponseType> {
  const q = new URLSearchParams();
  q.set('scope', p.scope ?? 'mine');
  q.set('days', String(p.days ?? 7));
  q.set('limit', String(p.limit ?? 50));
  q.set('offset', String(p.offset ?? 0));
  if (p.meetingId) q.set('meeting_id', p.meetingId);
  return apiClient<ClipJobListResponseType>(`/api/clip-jobs?${q.toString()}`);
}

/** 자동 클립 — AI 자막이 끝난 회의의 의원 전원 영상을 서버가 720p 로 미리 잘라 둔다(2026-09-10) */
export async function listMeetingAutoClips(meetingId: string): Promise<AutoClipListResponseType> {
  return apiClient<AutoClipListResponseType>(`/api/meetings/${meetingId}/auto-clips`);
}

export async function listRecentAutoClips(days = 3): Promise<AutoClipListResponseType> {
  return apiClient<AutoClipListResponseType>(`/api/auto-clips?days=${days}`);
}

/**
 * 의원 이름 → 그 이름이 나온 회의 id (발언영상 회의 목록의 이름 검색, 2026-09-11).
 * AI 자막 화자 라벨 ∪ 자막 본문 호명("박상현 위원")의 합집합이라 "후보" 다 — 회의를 열면 인덱스가 정답.
 */
export async function findClipMeetingsByMember(name: string): Promise<{ name: string; meeting_ids: string[] }> {
  return apiClient(`/api/clip-meetings/by-member?name=${encodeURIComponent(name)}`);
}

/** KMS 영상 번호(midx) → 회의 ID (옛 추출기 링크 ?midx= 회수용) */
export async function resolveMeetingByMidx(midx: string): Promise<{ meeting_id: string; title?: string | null }> {
  return apiClient(`/api/clip-jobs/resolve?midx=${encodeURIComponent(midx)}`);
}

/** 인증 헤더 — JWT 가 있으면 Bearer, 없으면 의회망 손님 헤더(X-Guest-Id) */
function clipAuthHeaders(): Record<string, string> {
  const token = typeof window !== 'undefined' ? localStorage.getItem('auth_token') : null;
  return token ? { Authorization: `Bearer ${token}` } : guestHeaders(null);
}

async function _throwApiError(response: Response, fallback: string): Promise<never> {
  let errorMessage = `${fallback}: ${response.status}`;
  try {
    const errorData = await response.json();
    if (errorData.detail) {
      errorMessage =
        typeof errorData.detail === 'string'
          ? errorData.detail
          : errorData.detail.message || JSON.stringify(errorData.detail);
    }
  } catch {
    /* ignore */
  }
  throw new ApiError(response.status, errorMessage);
}

export interface ClipFileBlob {
  blob: Blob;
  /** Content-Disposition 이 준 이름 (없으면 요청한 이름) */
  filename: string;
}

/**
 * 클립 파일(mp4/srt)을 **받기만** 한다 — 저장은 saveBlob 이 따로 한다.
 *
 * 쪼갠 이유(2026-09-16): 「받기 전에 재생해 확인」 모달이 같은 바이트를 재생에 쓰고,
 * 확인한 뒤 「이 파일 받기」를 누르면 **다시 받지 않고 그 blob 을 저장**한다.
 *
 * onProgress 는 Content-Length 가 있을 때만 0~1 을 준다(없으면 부르지 않는다 —
 * 화면은 부정형 막대로 떨어진다).
 */
export async function fetchClipJobFile(
  meetingId: string,
  jobId: string,
  fileName: string,
  onProgress?: (ratio: number) => void,
  signal?: AbortSignal
): Promise<ClipFileBlob> {
  const url =
    `${API_BASE_URL}/api/meetings/${meetingId}/clip-jobs/${jobId}/download?file=` +
    encodeURIComponent(fileName);
  const response = await fetch(url, { headers: clipAuthHeaders(), signal });
  if (!response.ok) await _throwApiError(response, '다운로드 실패');

  const disposition = response.headers.get('Content-Disposition') || '';
  const filename = _filenameFromDisposition(disposition, fileName);
  const total = Number(response.headers.get('Content-Length') || 0);

  // 진행률은 총 길이를 알고 스트림을 읽을 수 있을 때만. 둘 중 하나라도 없으면
  // 통째로 받는다(jsdom 은 body.getReader 가 없어 테스트가 이 경로로 온다).
  if (!onProgress || !total || !response.body?.getReader) {
    return { blob: await response.blob(), filename };
  }
  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let received = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    if (value) {
      chunks.push(value);
      received += value.length;
      onProgress(Math.min(1, received / total));
    }
  }
  return {
    blob: new Blob(chunks as BlobPart[], {
      type: response.headers.get('Content-Type') || 'application/octet-stream',
    }),
    filename,
  };
}

/** 이미 받아 둔 blob 을 파일로 저장한다 (a[download] 한 번). */
export function saveBlob(blob: Blob, fileName: string): void {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = fileName;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(a.href);
}

/**
 * 클립 썸네일(JPEG, 약 20KB) — 서버가 필요할 때 ffmpeg 로 한 장 뽑아 캐시한다.
 * `<img src>` 로 직접 못 거는 이유는 fetchClipJobFile 과 같다(인증이 헤더라서).
 * 없으면 404 → null 을 돌려주고 화면은 자리표시로 떨어진다.
 */
export async function fetchClipThumb(
  meetingId: string,
  jobId: string,
  fileName: string,
  signal?: AbortSignal
): Promise<Blob | null> {
  const url =
    `${API_BASE_URL}/api/meetings/${meetingId}/clip-jobs/${jobId}/thumbnail?file=` +
    encodeURIComponent(fileName);
  const response = await fetch(url, { headers: clipAuthHeaders(), signal });
  if (!response.ok) return null;
  return response.blob();
}

/**
 * 클립 파일(mp4/srt) 다운로드 — JWT 가 localStorage 라 <a href> 로는 인증이 안 붙는다.
 * fetch + blob 으로 받아 저장한다 (downloadClipJobResult 와 같은 패턴).
 */
export async function downloadClipJobFile(
  meetingId: string,
  jobId: string,
  fileName: string
): Promise<void> {
  const { blob, filename } = await fetchClipJobFile(meetingId, jobId, fileName);
  saveBlob(blob, filename);
}

export async function getExtractorVersion(): Promise<ExtractorVersionType | null> {
  try {
    return await apiClient<ExtractorVersionType>(
      '/api/tools/extractor/version.json'
    );
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) return null;
    throw e;
  }
}

/**
 * 영상추출기 새 버전 배포 (admin 전용).
 *
 * 설치파일(.exe) 업로드 또는 외부 URL(GitHub Releases 등) 중 하나를 등록한다.
 * FormData 전송이므로 Content-Type 을 수동 설정하지 않는다
 * (브라우저가 multipart boundary 를 부여; apiClient 는 JSON 고정이라 raw fetch 사용).
 *
 * @param form - version, notes + file(.exe) 또는 externalUrl 중 하나
 * @returns 배포된 매니페스트
 */
export async function uploadExtractorRelease(form: {
  version: string;
  notes: string;
  file?: File;
  externalUrl?: string;
}): Promise<ExtractorVersionType> {
  const formData = new FormData();
  formData.append('version', form.version);
  formData.append('notes', form.notes);
  if (form.file) formData.append('file', form.file);
  if (form.externalUrl) formData.append('external_url', form.externalUrl);

  const token =
    typeof window !== 'undefined' ? localStorage.getItem('auth_token') : null;
  const response = await fetch(`${API_BASE_URL}/api/tools/extractor/upload`, {
    method: 'POST',
    // Content-Type 수동 설정 금지 — 브라우저가 multipart boundary 를 부여
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body: formData,
  });

  if (!response.ok) {
    let msg = `배포 실패: ${response.status}`;
    try {
      const e = await response.json();
      if (e.detail) {
        msg = typeof e.detail === 'string' ? e.detail : JSON.stringify(e.detail);
      }
    } catch {
      /* ignore */
    }
    throw new ApiError(response.status, msg);
  }

  return response.json() as Promise<ExtractorVersionType>;
}

// ─── 채널 관리 (2026-09-16) ───────────────────────────────────────────────
// 다른 의회가 자기 생중계 주소를 넣는 자리. 전부 관리자 전용이며,
// 공개 `/api/channels` 계약과 섞이지 않도록 `/api/admin/channels` 로 분리돼 있다.

export interface AdminChannel {
  id: string;
  name: string;
  code: string | null;
  stream_url: string;
  committee: string | null;
  page_url: string | null;
  status_provider: string;
  manual_status: number | null;
  manual_until: string | null;
  sort_order: number;
  is_active: boolean;
  is_test: boolean;
}

export interface CouncilPreset {
  name: string;
  region: string;
  homepage: string;
  live_page: string | null;
  vendor: string | null;
  note: string;
}

export interface DiscoveredChannel {
  suggested_id: string;
  name: string;
  m3u8_url: string;
  code: string;
  confidence: number;
  evidence: string;
  verified: boolean | null;
  http_status: number | null;
}

export interface DiscoveryResult {
  page_url: string;
  vendor: string;
  candidates: DiscoveredChannel[];
  warnings: string[];
  fetched: { url: string; status?: number; bytes?: number; error?: string }[];
}

export async function listAdminChannels(): Promise<{ items: AdminChannel[]; snapshot: Record<string, unknown> }> {
  return apiClient('/api/admin/channels');
}

export async function listCouncilPresets(): Promise<{ councils: CouncilPreset[]; generated_at: string | null }> {
  return apiClient('/api/admin/channels/presets');
}

export async function discoverChannels(pageUrl: string): Promise<DiscoveryResult> {
  return apiClient('/api/admin/channels/discover', {
    method: 'POST',
    body: JSON.stringify({ page_url: pageUrl }),
  });
}

export async function createAdminChannel(payload: Partial<AdminChannel>): Promise<AdminChannel> {
  return apiClient('/api/admin/channels', { method: 'POST', body: JSON.stringify(payload) });
}

export async function createAdminChannelsBulk(
  items: Partial<AdminChannel>[],
): Promise<{ created: string[]; skipped: string[]; errors: { id: string; detail: string }[] }> {
  return apiClient('/api/admin/channels/bulk', { method: 'POST', body: JSON.stringify({ items }) });
}

export async function updateAdminChannel(id: string, patch: Partial<AdminChannel>): Promise<AdminChannel> {
  return apiClient(`/api/admin/channels/${id}`, { method: 'PATCH', body: JSON.stringify(patch) });
}

export async function deleteAdminChannel(id: string, hard = false): Promise<void> {
  await apiClient(`/api/admin/channels/${id}?hard=${hard}`, { method: 'DELETE' });
}

export async function probeAdminChannel(
  id: string,
): Promise<{ ok: boolean; http_status?: number; detail: string; insecure_tls?: boolean }> {
  return apiClient(`/api/admin/channels/${id}/probe`, { method: 'POST' });
}
