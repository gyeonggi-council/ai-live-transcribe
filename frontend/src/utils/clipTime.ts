/**
 * 클립 워크벤치 시간 유틸 — 데스크톱 추출기(webui/app.html) 의 fmt/parseT/fmtLen 이식
 */

/** 초 → HH:MM:SS (항상 시 단위 포함 — 회의는 2~5시간이라 자릿수가 흔들리면 읽기 어렵다) */
export function formatHMS(seconds: number): string {
  const t = Math.max(0, Math.floor(Number.isFinite(seconds) ? seconds : 0));
  const h = Math.floor(t / 3600);
  const m = Math.floor((t % 3600) / 60);
  const s = t % 60;
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

/**
 * 'HH:MM:SS' | 'MM:SS' | 'SS' | '1시간 2분' 같은 입력 → 초. 해석 불가면 null.
 * 정책지원관은 "몇 분쯤"을 알고 오므로 '12:30' 처럼 짧게 쳐도 받는다.
 */
export function parseHMS(input: string): number | null {
  const raw = (input || '').trim();
  if (!raw) return null;
  const korean = raw.match(/^(?:(\d+)\s*시간)?\s*(?:(\d+)\s*분)?\s*(?:(\d+)\s*초)?$/);
  if (korean && (korean[1] || korean[2] || korean[3])) {
    return Number(korean[1] || 0) * 3600 + Number(korean[2] || 0) * 60 + Number(korean[3] || 0);
  }
  if (!/^[\d:.\s]+$/.test(raw)) return null;
  const parts = raw.split(':').map((p) => p.trim());
  if (parts.some((p) => p === '' || Number.isNaN(Number(p)))) return null;
  const nums = parts.map(Number);
  const [a = 0, b = 0, c = 0] = nums;
  if (nums.length === 1) return Math.max(0, a);
  if (nums.length === 2) return Math.max(0, a * 60 + b);
  if (nums.length === 3) return Math.max(0, a * 3600 + b * 60 + c);
  return null;
}

/** 초 → '2분 36초' / '45초' / '1시간 02분' (사람이 읽는 길이) */
export function formatLen(seconds: number): string {
  const t = Math.max(0, Math.round(Number.isFinite(seconds) ? seconds : 0));
  const h = Math.floor(t / 3600);
  const m = Math.floor((t % 3600) / 60);
  const s = t % 60;
  if (h > 0) return `${h}시간 ${String(m).padStart(2, '0')}분`;
  if (m > 0) return `${m}분 ${String(s).padStart(2, '0')}초`;
  return `${s}초`;
}

/** 바이트 → '12.3 MB' */
export function formatBytes(bytes: number): string {
  if (!bytes || bytes <= 0) return '0 B';
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
  if (bytes >= 1024 ** 2) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${bytes} B`;
}

/** 0 ≤ t ≤ duration 으로 자른다 (duration 이 없으면 하한만) */
export function clampTime(t: number, duration?: number | null): number {
  const lo = Math.max(0, Number.isFinite(t) ? t : 0);
  return duration && duration > 0 ? Math.min(lo, duration) : lo;
}

export interface ClipSelection {
  start: number;
  end: number;
}

/** 시작 지정 — 종료가 앞에 있으면 종료를 영상 끝(또는 시작)으로 민다 (app.html markStart) */
export function withStart(sel: ClipSelection, t: number, duration?: number | null): ClipSelection {
  const start = clampTime(t, duration);
  const end = sel.end < start ? (duration && duration > 0 ? duration : start) : sel.end;
  return { start, end };
}

/** 종료 지정 — 시작이 뒤에 있으면 시작을 0 으로 (app.html markEnd) */
export function withEnd(sel: ClipSelection, t: number, duration?: number | null): ClipSelection {
  const end = clampTime(t, duration);
  const start = sel.start > end ? 0 : sel.start;
  return { start, end };
}
