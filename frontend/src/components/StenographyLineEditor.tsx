'use client';

import React, { useCallback, useEffect, useRef, useState } from 'react';

import type { StenographyLine } from '../types';

export interface StenographyLineEditorProps {
  line: StenographyLine;
  isActive: boolean;
  speakerOptions: string[];
  onTextChange: (id: string, text: string) => void;
  onSpeakerChange: (id: string, speaker: string | null) => void;
  onTimingChange: (id: string, field: 'start_ms' | 'end_ms', value: number | null) => void;
  onParagraphToggle: (id: string, value: boolean) => void;
  onSeek: (timeMs: number) => void;
  onFocus?: (id: string) => void;
}

function msToTimeStr(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return '--:--.-';
  const totalSeconds = ms / 1000;
  const m = Math.floor(totalSeconds / 60);
  const s = totalSeconds % 60;
  return `${m.toString().padStart(2, '0')}:${s.toFixed(1).padStart(4, '0')}`;
}

function timeStrToMs(str: string): number | null {
  const match = str.trim().match(/^(\d{1,3}):(\d{1,2}(?:\.\d{0,3})?)$/);
  if (!match) return null;
  const minutes = parseInt(match[1] || '0', 10);
  const secs = parseFloat(match[2] || '0');
  if (isNaN(minutes) || isNaN(secs) || secs >= 60) return null;
  return Math.round((minutes * 60 + secs) * 1000);
}

const StenographyLineEditor = React.memo(function StenographyLineEditor({
  line,
  isActive,
  speakerOptions,
  onTextChange,
  onSpeakerChange,
  onTimingChange,
  onParagraphToggle,
  onSeek,
  onFocus,
}: StenographyLineEditorProps) {
  const [localText, setLocalText] = useState(line.text);
  const [localStart, setLocalStart] = useState(msToTimeStr(line.start_ms));
  const [localEnd, setLocalEnd] = useState(msToTimeStr(line.end_ms));
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Sync local state when props change
  useEffect(() => {
    setLocalText(line.text);
  }, [line.text]);

  useEffect(() => {
    setLocalStart(msToTimeStr(line.start_ms));
  }, [line.start_ms]);

  useEffect(() => {
    setLocalEnd(msToTimeStr(line.end_ms));
  }, [line.end_ms]);

  // Auto-resize textarea
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = `${textareaRef.current.scrollHeight}px`;
    }
  }, [localText]);

  const handleTextBlur = useCallback(() => {
    if (localText !== line.text) {
      onTextChange(line.id, localText);
    }
  }, [localText, line.text, line.id, onTextChange]);

  const handleStartBlur = useCallback(() => {
    const parsed = timeStrToMs(localStart);
    if (parsed !== line.start_ms) {
      onTimingChange(line.id, 'start_ms', parsed);
    }
    // Re-format to ensure consistent display
    setLocalStart(msToTimeStr(parsed !== null ? parsed : line.start_ms));
  }, [localStart, line.start_ms, line.id, onTimingChange]);

  const handleEndBlur = useCallback(() => {
    const parsed = timeStrToMs(localEnd);
    if (parsed !== line.end_ms) {
      onTimingChange(line.id, 'end_ms', parsed);
    }
    // Re-format to ensure consistent display
    setLocalEnd(msToTimeStr(parsed !== null ? parsed : line.end_ms));
  }, [localEnd, line.end_ms, line.id, onTimingChange]);

  const handleStartClick = useCallback(() => {
    if (line.start_ms !== null) {
      onSeek(line.start_ms);
    }
  }, [line.start_ms, onSeek]);

  const handleFocus = useCallback(() => {
    if (onFocus) {
      onFocus(line.id);
    }
  }, [line.id, onFocus]);

  const baseStyles = "flex items-start gap-2 px-2 py-1.5 transition-colors min-h-[40px]";
  const activeStyles = isActive ? "bg-primary-5 border-l-4 border-l-primary" : "bg-white hover:bg-gray-50 border-l-4 border-l-transparent";
  const paragraphStyles = line.starts_new_paragraph ? "border-t-2 border-gray-300 mt-2 pt-2" : "";

  return (
    <div 
      className={`${baseStyles} ${activeStyles} ${paragraphStyles}`}
      data-testid={`steno-line-${line.id}`}
    >
      {/* Sequence Number */}
      <div className="w-8 flex-shrink-0 text-xs text-gray-400 text-right pt-1 select-none">
        {line.sequence_no}
      </div>

      {/* Start Time */}
      <div className="flex items-center gap-1 pt-0.5">
        <button 
          type="button"
          onClick={handleStartClick}
          className="text-[10px] text-primary hover:text-primary-dark"
          title="시작 시점으로 이동"
        >
          ▶
        </button>
        <input
          type="text"
          value={localStart}
          onChange={(e) => setLocalStart(e.target.value)}
          onBlur={handleStartBlur}
          className="w-[70px] font-mono text-xs text-gray-500 bg-transparent border border-transparent hover:border-gray-300 focus:border-primary focus-visible:ring-2 focus-visible:ring-primary rounded px-1 py-0.5 outline-none transition-colors"
          data-testid={`steno-start-${line.id}`}
          title="시작"
        />
      </div>

      {/* End Time */}
      <div className="flex items-center gap-1 pt-0.5">
        <span className="text-gray-400 text-xs">—</span>
        <input
          type="text"
          value={localEnd}
          onChange={(e) => setLocalEnd(e.target.value)}
          onBlur={handleEndBlur}
          className="w-[70px] font-mono text-xs text-gray-500 bg-transparent border border-transparent hover:border-gray-300 focus:border-primary focus-visible:ring-2 focus-visible:ring-primary rounded px-1 py-0.5 outline-none transition-colors"
          data-testid={`steno-end-${line.id}`}
          title="종료"
        />
      </div>

      {/* Speaker Dropdown */}
      <div className="pt-0.5">
        <select
          value={line.speaker || ''}
          onChange={(e) => onSpeakerChange(line.id, e.target.value || null)}
          className="w-[100px] text-sm border-gray-300 rounded shadow-sm focus:border-primary focus-visible:ring-2 focus-visible:ring-primary py-0.5 px-1"
          data-testid={`steno-speaker-${line.id}`}
        >
          <option value="">(미지정)</option>
          {speakerOptions.map((speaker) => (
            <option key={speaker} value={speaker}>
              {speaker}
            </option>
          ))}
        </select>
      </div>

      {/* Text Input */}
      <div className="flex-grow flex flex-col justify-center min-w-0">
        <textarea
          ref={textareaRef}
          value={localText}
          onChange={(e) => setLocalText(e.target.value)}
          onBlur={handleTextBlur}
          onFocus={handleFocus}
          rows={1}
          className="w-full font-mono text-sm bg-transparent border-0 border-b border-transparent focus:border-primary focus:ring-0 resize-none overflow-hidden py-1 px-1 outline-none"
          data-testid={`steno-text-${line.id}`}
        />
      </div>

      {/* Paragraph Toggle */}
      <div className="pt-1 pr-1">
        <button
          type="button"
          onClick={() => onParagraphToggle(line.id, !line.starts_new_paragraph)}
          className={`p-1 rounded transition-colors ${
            line.starts_new_paragraph 
              ? 'text-primary bg-primary-10 hover:bg-primary-20'
              : 'text-gray-400 hover:bg-gray-200 hover:text-gray-600'
          }`}
          title="문단 나누기"
          data-testid={`steno-paragraph-${line.id}`}
        >
          ¶
        </button>
      </div>
    </div>
  );
});

export default StenographyLineEditor;
