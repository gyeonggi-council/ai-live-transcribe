'use client';

import { useState } from 'react';

import type { MinutesEdit } from '@/lib/minutesLocalEdits';

function formatTime(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  if (h > 0) {
    return `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
  }
  return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
}

type DiffPart = { type: 'eq' | 'del' | 'add'; text: string };

/** 단어 단위 LCS diff — 원문 대비 추가(add)/삭제(del)/유지(eq) 토큰을 계산. */
function wordDiff(orig: string, edited: string): DiffPart[] {
  const a = orig.split(/\s+/).filter(Boolean);
  const b = edited.split(/\s+/).filter(Boolean);
  const n = a.length;
  const m = b.length;
  const dp: number[][] = [];
  for (let i = 0; i <= n; i++) dp.push(new Array(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--) {
    const row = dp[i]!;
    const next = dp[i + 1]!;
    for (let j = m - 1; j >= 0; j--) {
      row[j] = a[i] === b[j] ? next[j + 1]! + 1 : Math.max(next[j]!, row[j + 1]!);
    }
  }
  const parts: DiffPart[] = [];
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (a[i] === b[j]) {
      parts.push({ type: 'eq', text: a[i]! });
      i++;
      j++;
    } else if (dp[i + 1]![j]! >= dp[i]![j + 1]!) {
      parts.push({ type: 'del', text: a[i]! });
      i++;
    } else {
      parts.push({ type: 'add', text: b[j]! });
      j++;
    }
  }
  while (i < n) {
    parts.push({ type: 'del', text: a[i]! });
    i++;
  }
  while (j < m) {
    parts.push({ type: 'add', text: b[j]! });
    j++;
  }
  return parts;
}

export interface EditableTranscriptBlockProps {
  speaker: string;
  startTime: number;
  endTime: number;
  /** 원본(AI 자막) 텍스트 */
  originalText: string;
  /** 이 문단에 저장된 로컬 수정(있으면 수정본을 표시) */
  edit?: MinutesEdit;
  isContinuation?: boolean;
  isActive?: boolean;
  showPlayButton?: boolean;
  isPlaying?: boolean;
  onPlay?: () => void;
  /** 수정 저장 콜백 (수정된 텍스트, 수정된 화자) */
  onSave: (editedText: string, editedSpeaker: string) => void;
  /** 원본 복원 콜백 */
  onReset: () => void;
  registerRef?: (el: HTMLDivElement | null) => void;
}

/**
 * 회의록 화자 발언 문단.
 * - 수정은 "수정" 버튼으로만 진입(텍스트 클릭으로는 안 됨)
 * - 텍스트 + 화자를 모두 수정 가능
 * - 수정되면 경고색(warning) 강조 + "✎ 수정됨" 배지, "변경 보기"를 누르면 같은 문단에서
 *   인라인으로 변경 표시(error=삭제, primary=추가) — 별도 블록을 만들지 않음
 * - 저장 시 localStorage에 기록
 */
export default function EditableTranscriptBlock({
  speaker,
  startTime,
  endTime,
  originalText,
  edit,
  isContinuation = false,
  isActive = false,
  showPlayButton = false,
  isPlaying = false,
  onPlay,
  onSave,
  onReset,
  registerRef,
}: EditableTranscriptBlockProps) {
  const isEdited = !!edit;
  const displayText = edit?.edited ?? originalText;
  const displaySpeaker = edit?.editedSpeaker ?? speaker;
  const speakerChanged = !!edit?.editedSpeaker && edit.editedSpeaker !== speaker;
  const textChanged = !!edit && edit.edited !== edit.original;

  const [isEditing, setIsEditing] = useState(false);
  const [draft, setDraft] = useState(displayText);
  const [draftSpeaker, setDraftSpeaker] = useState(displaySpeaker);
  const [showDiff, setShowDiff] = useState(false);

  const startEdit = () => {
    setDraft(edit?.edited ?? originalText);
    setDraftSpeaker(edit?.editedSpeaker ?? speaker);
    setIsEditing(true);
  };

  const handleSave = () => {
    const t = draft.trim();
    const sp = draftSpeaker.trim() || speaker;
    if (t && (t !== originalText || sp !== speaker)) {
      onSave(t, sp);
    }
    setIsEditing(false);
  };

  const containerClass = isEdited
    ? 'border-l-4 border-l-warning-bg bg-warning-bg/10'
    : isActive
      ? 'border-l-4 border-l-primary bg-primary-5/60'
      : 'border-l-4 border-l-transparent';

  return (
    <div
      ref={registerRef}
      data-testid="transcript-block"
      className={`border-b border-gray-100 pb-3 last:border-b-0 print:break-inside-avoid pl-3 transition-colors ${containerClass}`}
    >
      <div className="flex items-center gap-2 mb-1 flex-wrap">
        {showPlayButton && (
          <button
            onClick={onPlay}
            className="w-6 h-6 flex-shrink-0 flex items-center justify-center rounded-full text-gray-400 hover:text-primary hover:bg-gray-100 transition-colors print:hidden"
            title={`${formatTime(startTime)}부터 재생`}
          >
            {isPlaying && isActive ? (
              <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
                <path d="M6 4h4v16H6V4zm8 0h4v16h-4V4z" />
              </svg>
            ) : (
              <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
                <path d="M8 5v14l11-7z" />
              </svg>
            )}
          </button>
        )}
        {/* 화자 라벨 — 화자구분이 없으면(transcribe 자막) 시각으로 대체해 표시 */}
        {displaySpeaker && (
          <span className="text-sm font-semibold text-primary">
            {displaySpeaker}
            {isContinuation && <span className="text-xs text-gray-400 ml-1">(계속)</span>}
          </span>
        )}
        {!displaySpeaker && (
          <span className="text-sm font-semibold text-gray-500">
            발언 {formatTime(startTime)}
            {isContinuation && <span className="text-xs text-gray-400 ml-1">(계속)</span>}
          </span>
        )}
        {speakerChanged && (
          <span className="text-[11px] text-gray-400">
            (원래: <span className="line-through">{speaker}</span>)
          </span>
        )}
        <span className="text-xs text-gray-400">
          {formatTime(startTime)} ~ {formatTime(endTime)}
        </span>
        {isEdited && (
          <span className="px-1.5 py-0.5 bg-warning-bg/20 text-warning text-[11px] font-medium rounded print:hidden">
            ✎ 수정됨
          </span>
        )}
        {isEdited && textChanged && !isEditing && (
          <button
            onClick={() => setShowDiff((v) => !v)}
            className="text-xs text-warning hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary rounded print:hidden"
          >
            {showDiff ? '변경 숨기기' : '변경 보기'}
          </button>
        )}
        {!isEditing && (
          <button
            onClick={startEdit}
            className="ml-auto text-xs font-medium text-gray-500 hover:text-primary border border-gray-200 hover:border-primary rounded px-2 py-0.5 transition-colors print:hidden"
            title="이 발언의 내용·화자를 수정합니다 (이 브라우저에 저장)"
          >
            수정
          </button>
        )}
      </div>

      {isEditing ? (
        <div className="space-y-2 print:hidden">
          <div className="flex items-center gap-2">
            <label className="text-xs text-gray-500 flex-shrink-0">화자</label>
            <input
              data-testid="transcript-edit-speaker"
              value={draftSpeaker}
              onChange={(e) => setDraftSpeaker(e.target.value)}
              placeholder="화자 이름 (예: 김시용 위원장)"
              className="flex-1 text-sm text-gray-800 border border-primary-30 rounded-md px-2 py-1 focus:outline-none focus:border-primary focus:ring-2 focus:ring-primary/30"
            />
          </div>
          <textarea
            data-testid="transcript-edit-textarea"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            rows={Math.min(12, Math.max(3, Math.ceil(draft.length / 60)))}
            className="w-full text-sm text-gray-800 leading-relaxed border border-primary-30 rounded-md p-2 focus:outline-none focus:border-primary focus:ring-2 focus:ring-primary/30"
            autoFocus
          />
          <div className="flex items-center gap-2">
            <button
              onClick={handleSave}
              className="px-3 py-1 text-xs font-medium bg-primary text-white rounded hover:bg-primary-dark transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
            >
              저장
            </button>
            <button
              onClick={() => setIsEditing(false)}
              className="px-3 py-1 text-xs font-medium bg-gray-100 text-gray-700 rounded hover:bg-gray-200 transition-colors"
            >
              취소
            </button>
            {isEdited && (
              <button
                onClick={() => {
                  onReset();
                  setIsEditing(false);
                }}
                className="px-3 py-1 text-xs font-medium text-error hover:bg-error/5 rounded transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
              >
                원본 복원
              </button>
            )}
          </div>
        </div>
      ) : isEdited && showDiff && textChanged && edit ? (
        // 변경 보기: 같은 자리에서 인라인 diff로 표시 (별도 블록 없음)
        <p className="text-sm leading-relaxed whitespace-pre-wrap">
          {wordDiff(edit.original, edit.edited).map((p, idx) =>
            p.type === 'eq' ? (
              <span key={idx} className="text-gray-800">
                {p.text}{' '}
              </span>
            ) : p.type === 'add' ? (
              <span key={idx} className="text-primary-dark font-semibold">
                {p.text}{' '}
              </span>
            ) : (
              <span key={idx} className="text-error line-through">
                {p.text}{' '}
              </span>
            ),
          )}
        </p>
      ) : (
        // 재생 중인 문장은 폰트 색(primary)+굵게로 강조 — '지금 어디 읽는지' 한눈에.
        <p
          className={`text-sm leading-relaxed whitespace-pre-wrap transition-colors ${
            isActive ? 'text-primary font-semibold' : 'text-gray-800'
          }`}
        >
          {displayText}
        </p>
      )}
    </div>
  );
}
