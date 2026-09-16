/**
 * 회의록(/minutes) 자막 문단의 로컬 수정 저장소.
 *
 * 로그인/백엔드 없이 이 브라우저(localStorage)에만 수정본과 수정 이력을 보관한다.
 * - 수정본: blockKey → 최신 수정 내용 (렌더링 시 원본을 덮어씀)
 * - 이력: 모든 수정의 누적 로그 (무엇이 언제 어떻게 바뀌었는지 확인용)
 *
 * blockKey 는 회의 내에서 문단을 고유 식별하는 값(첫 자막 시작시간)을 사용한다.
 */

export interface MinutesEdit {
  /** 회의 내 문단 식별자 (그룹 시작시간 문자열) */
  blockKey: string;
  speaker: string;
  startTime: number;
  endTime: number;
  /** 최초 원본(AI 자막) 텍스트 */
  original: string;
  /** 수정된 텍스트 */
  edited: string;
  /** 수정된 화자 (화자도 변경한 경우만) */
  editedSpeaker?: string;
  /** 수정 시각 (epoch ms) */
  editedAt: number;
}

const EDITS_KEY = (meetingId: string) => `minutes_edits_v1_${meetingId}`;
const HISTORY_KEY = (meetingId: string) => `minutes_edit_history_v1_${meetingId}`;
const MAX_HISTORY = 500;

function readJson<T>(key: string, fallback: T): T {
  if (typeof window === 'undefined') return fallback;
  try {
    const raw = window.localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

/** 현재 적용 중인 수정본 맵 (blockKey → MinutesEdit) */
export function loadEdits(meetingId: string): Record<string, MinutesEdit> {
  return readJson<Record<string, MinutesEdit>>(EDITS_KEY(meetingId), {});
}

/** 수정 이력 (최신순) */
export function loadHistory(meetingId: string): MinutesEdit[] {
  return readJson<MinutesEdit[]>(HISTORY_KEY(meetingId), []);
}

/**
 * 문단 수정 저장. 수정본 맵을 갱신하고 이력에 한 건 추가한다.
 * 갱신된 수정본 맵을 반환한다(React 상태 갱신용).
 */
export function saveEdit(meetingId: string, edit: MinutesEdit): Record<string, MinutesEdit> {
  const edits = loadEdits(meetingId);
  edits[edit.blockKey] = edit;
  if (typeof window !== 'undefined') {
    try {
      window.localStorage.setItem(EDITS_KEY(meetingId), JSON.stringify(edits));
      const history = loadHistory(meetingId);
      history.unshift(edit);
      window.localStorage.setItem(
        HISTORY_KEY(meetingId),
        JSON.stringify(history.slice(0, MAX_HISTORY)),
      );
    } catch {
      // localStorage 용량 초과 등 — 무시(데모용)
    }
  }
  return { ...edits };
}

/** 특정 문단의 수정을 제거(원본 복원). 이력은 보존한다. */
export function resetEdit(meetingId: string, blockKey: string): Record<string, MinutesEdit> {
  const edits = loadEdits(meetingId);
  delete edits[blockKey];
  if (typeof window !== 'undefined') {
    try {
      window.localStorage.setItem(EDITS_KEY(meetingId), JSON.stringify(edits));
    } catch {
      // 무시
    }
  }
  return { ...edits };
}
