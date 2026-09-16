'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

import {
  ApiError,
  getStenographyLines,
  updateStenographyLines,
} from '../lib/api';

import type {
  StenographyLine,
  StenographyLineUpdate,
} from '../types';

// ============================================================
// Types
// ============================================================

interface UseStenographyEditorOptions {
  meetingId: string;
  recordId: string;
}

interface UseStenographyEditorReturn {
  /** All lines for this record */
  lines: StenographyLine[];
  /** Whether we're loading */
  isLoading: boolean;
  /** Error, if any */
  error: Error | null;
  /** Whether there are unsaved changes */
  isDirty: boolean;
  /** Whether we're saving */
  isSaving: boolean;
  /** Currently focused line ID */
  focusedLineId: string | null;

  // Actions
  setFocusedLineId: (id: string | null) => void;
  handleTextChange: (id: string, text: string) => void;
  handleSpeakerChange: (id: string, speaker: string | null) => void;
  handleTimingChange: (id: string, field: 'start_ms' | 'end_ms', value: number | null) => void;
  handleParagraphToggle: (id: string, value: boolean) => void;
  handleSequenceChange: (id: string, sequenceNo: number) => void;
  save: () => Promise<void>;
  reload: () => Promise<void>;
  setLines: React.Dispatch<React.SetStateAction<StenographyLine[]>>;
}

// ============================================================
// Local draft recovery
// ============================================================

const DRAFT_PREFIX = 'steno_draft_';

function saveDraft(recordId: string, changes: Map<string, Partial<StenographyLineUpdate>>): void {
  try {
    const serialized = JSON.stringify(Array.from(changes.entries()));
    localStorage.setItem(`${DRAFT_PREFIX}${recordId}`, serialized);
  } catch {
    // localStorage full or unavailable — ignore
  }
}

function loadDraft(recordId: string): Map<string, Partial<StenographyLineUpdate>> | null {
  try {
    const data = localStorage.getItem(`${DRAFT_PREFIX}${recordId}`);
    if (!data) return null;
    const entries: [string, Partial<StenographyLineUpdate>][] = JSON.parse(data);
    return new Map(entries);
  } catch {
    return null;
  }
}

function clearDraft(recordId: string): void {
  try {
    localStorage.removeItem(`${DRAFT_PREFIX}${recordId}`);
  } catch {
    // ignore
  }
}

// ============================================================
// Hook
// ============================================================

export default function useStenographyEditor({
  meetingId,
  recordId,
}: UseStenographyEditorOptions): UseStenographyEditorReturn {
  const [lines, setLines] = useState<StenographyLine[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [focusedLineId, setFocusedLineId] = useState<string | null>(null);

  // Dirty tracking: Map<lineId, partial changes>
  const changesMap = useRef<Map<string, Partial<StenographyLineUpdate>>>(new Map());
  const [isDirty, setIsDirty] = useState(false);

  // --------------------------------------------------------
  // Load lines
  // --------------------------------------------------------
  const loadLines = useCallback(async () => {
    try {
      setIsLoading(true);
      setError(null);
      const response = await getStenographyLines(meetingId, recordId);
      setLines(response);

      // Restore any unsaved local draft
      const draft = loadDraft(recordId);
      if (draft && draft.size > 0) {
        changesMap.current = draft;
        setIsDirty(true);

        // Apply draft changes to loaded lines
        setLines((prev) =>
          prev.map((line) => {
            const change = draft.get(line.id);
            if (!change) return line;
            return { ...line, ...change } as StenographyLine;
          })
        );
      }
    } catch (err) {
      setError(err instanceof Error ? err : new Error('Failed to load lines'));
    } finally {
      setIsLoading(false);
    }
  }, [meetingId, recordId]);

  useEffect(() => {
    loadLines();
  }, [loadLines]);

  // --------------------------------------------------------
  // Track changes helper
  // --------------------------------------------------------
  const trackChange = useCallback(
    (id: string, field: string, value: unknown) => {
      const existing = changesMap.current.get(id) || { id };
      changesMap.current.set(id, { ...existing, [field]: value });
      setIsDirty(true);
      saveDraft(recordId, changesMap.current);
    },
    [recordId]
  );

  // --------------------------------------------------------
  // Change handlers
  // --------------------------------------------------------
  const handleTextChange = useCallback(
    (id: string, text: string) => {
      trackChange(id, 'text', text);
      setLines((prev) =>
        prev.map((l) => (l.id === id ? { ...l, text } : l))
      );
    },
    [trackChange]
  );

  const handleSpeakerChange = useCallback(
    (id: string, speaker: string | null) => {
      trackChange(id, 'speaker', speaker);
      setLines((prev) =>
        prev.map((l) => (l.id === id ? { ...l, speaker } : l))
      );
    },
    [trackChange]
  );

  const handleTimingChange = useCallback(
    (id: string, field: 'start_ms' | 'end_ms', value: number | null) => {
      trackChange(id, field, value);
      setLines((prev) =>
        prev.map((l) => (l.id === id ? { ...l, [field]: value } : l))
      );
    },
    [trackChange]
  );

  const handleParagraphToggle = useCallback(
    (id: string, value: boolean) => {
      trackChange(id, 'starts_new_paragraph', value);
      setLines((prev) =>
        prev.map((l) => (l.id === id ? { ...l, starts_new_paragraph: value } : l))
      );
    },
    [trackChange]
  );

  const handleSequenceChange = useCallback(
    (id: string, sequenceNo: number) => {
      trackChange(id, 'sequence_no', sequenceNo);
      setLines((prev) =>
        prev.map((l) => (l.id === id ? { ...l, sequence_no: sequenceNo } : l))
      );
    },
    [trackChange]
  );

  // --------------------------------------------------------
  // Reload (discard local changes)
  // --------------------------------------------------------
  const reload = useCallback(async () => {
    changesMap.current.clear();
    setIsDirty(false);
    clearDraft(recordId);
    await loadLines();
  }, [loadLines, recordId]);

  // Stable ref so save() can call reload() without it being a dep-array entry
  // (avoids the circular save→reload→loadLines→save re-creation chain).
  const reloadRef = useRef(reload);
  reloadRef.current = reload;

  // --------------------------------------------------------
  // Save
  // --------------------------------------------------------
  const save = useCallback(async () => {
    if (changesMap.current.size === 0) return;

    setIsSaving(true);
    try {
      // Capture current line versions using the functional updater (no stale closure).
      const currentVersions = new Map<string, number | undefined>();
      await new Promise<void>((resolve) => {
        setLines((prev) => {
          prev.forEach((l) => currentVersions.set(l.id, l.version));
          resolve();
          return prev; // no-op update
        });
      });

      const items: StenographyLineUpdate[] = Array.from(
        changesMap.current.entries()
      ).map(([id, changes]) => ({
        id,
        ...changes,
        // Include version for optimistic concurrency; may be undefined for new lines
        version: currentVersions.get(id),
      }));

      const result = await updateStenographyLines(meetingId, recordId, items);

      // Update local lines with server response
      if (result.items && result.items.length > 0) {
        const serverMap = new Map(result.items.map((item) => [item.id, item]));
        setLines((prev) =>
          prev.map((line) => serverMap.get(line.id) || line)
        );
      }

      changesMap.current.clear();
      setIsDirty(false);
      clearDraft(recordId);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        // Another user modified these lines — reload latest and surface a clear message
        try {
          await reloadRef.current();
        } catch {
          // reload failure is secondary; ignore and surface the conflict error
        }
        const conflictError = new Error(
          '다른 사용자가 먼저 수정했습니다. 최신 내용으로 새로고침했습니다.'
        );
        setError(conflictError);
        throw conflictError;
      }
      // Non-409 errors: re-throw so the caller can show an error toast
      throw err instanceof Error ? err : new Error('Save failed');
    } finally {
      setIsSaving(false);
    }
  }, [meetingId, recordId]);

  return {
    lines,
    isLoading,
    error,
    isDirty,
    isSaving,
    focusedLineId,
    setFocusedLineId,
    handleTextChange,
    handleSpeakerChange,
    handleTimingChange,
    handleParagraphToggle,
    handleSequenceChange,
    save,
    reload,
    setLines,
  };
}
