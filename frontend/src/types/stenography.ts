import type { StenographyLine } from './index';

/** Batch save request item (no id for new lines) */
export interface StenographyLineSaveItem {
  id?: string;
  sequence_no: number;
  text: string;
  speaker?: string | null;
  start_ms?: number | null;
  end_ms?: number | null;
  starts_new_paragraph?: boolean;
}

/** Batch save request body */
export interface StenographyLinesBatchSaveRequest {
  lines: StenographyLineSaveItem[];
}

/** Bootstrap from subtitles response */
export interface StenographyBootstrapResponse {
  lines: StenographyLine[];
  count: number;
}

/** Import from text request */
export interface StenographyImportFromTextRequest {
  text: string;
  delimiter?: string;
}

/** Editor dirty state — tracks which lines have been modified */
export type StenographyChangesMap = Map<string, Partial<StenographyLineSaveItem>>;

/** Draft state for localStorage persistence */
export interface StenographyDraftState {
  recordId: string;
  lines: StenographyLineSaveItem[];
  savedAt: number; // Date.now() timestamp
}
