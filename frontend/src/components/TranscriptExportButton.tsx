'use client';

import React, { useState } from 'react';

import { KMS_EXPORT_ENABLED } from '../config/features';
import { logAccess } from '../hooks/useAccessLog';
import { downloadTranscript, downloadVideoMinutes } from '../lib/api';
import Button from './ui/Button';

interface TranscriptExportButtonProps {
  meetingId: string;
  meetingTitle: string;
}

type TranscriptFormat = 'markdown' | 'srt' | 'json' | 'official' | 'html' | 'hwpx' | 'docx';
type ExportValue = TranscriptFormat | 'video-minutes';

const FORMAT_OPTIONS: { value: ExportValue; label: string; desc: string }[] = [
  { value: 'hwpx', label: '전자회의록 (HWPX)', desc: 'KMS 공식 회의록 양식 · 한글' },
  { value: 'video-minutes', label: '영상회의록 (HTML)', desc: 'KMS 안건시간 등록용 · 생성에 수 초' },
  { value: 'official', label: '공식 회의록', desc: '발언자 중심 텍스트 포맷' },
  { value: 'html', label: '회의록 (HTML)', desc: 'HTML 형식 · 인쇄→PDF 지원' },
  { value: 'docx', label: '워드 (DOCX)', desc: '한글·MS워드에서 모두 열림' },
  { value: 'markdown', label: '회의록 (MD)', desc: 'Markdown 형식 회의록' },
  { value: 'srt', label: '자막 (SRT)', desc: '표준 자막 파일' },
  { value: 'json', label: '데이터 (JSON)', desc: '시스템 연계용' },
];

export default function TranscriptExportButton({
  meetingId,
  meetingTitle,
}: TranscriptExportButtonProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [loadingLabel, setLoadingLabel] = useState('다운로드 중...');
  const [error, setError] = useState<string | null>(null);

  const handleExport = async (format: ExportValue) => {
    logAccess('download', { meetingId });  // 접속 통계(2026-09-16)
    try {
      setIsLoading(true);
      setError(null);
      if (format === 'video-minutes') {
        setLoadingLabel('영상회의록 생성 중...');
        await downloadVideoMinutes(meetingId);
      } else {
        setLoadingLabel('다운로드 중...');
        await downloadTranscript(meetingId, format);
      }
      setIsOpen(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : '다운로드에 실패했습니다.');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="relative mt-2">
      <Button
        variant="outline"
        onClick={() => setIsOpen(!isOpen)}
        loading={isLoading}
        className="w-full"
      >
        {!isLoading && (
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
          </svg>
        )}
        {isLoading ? loadingLabel : '회의록 내보내기'}
      </Button>

      {isOpen && !isLoading && (
        <div className="absolute bottom-full left-0 right-0 mb-1 bg-white border border-gray-200 rounded-lg shadow-lg overflow-hidden z-10">
          <div className="px-3 py-2 bg-gray-50 border-b border-gray-100">
            <p className="text-xs text-gray-500 truncate">{meetingTitle}</p>
          </div>
          {FORMAT_OPTIONS.filter(
            (opt) => KMS_EXPORT_ENABLED || opt.value !== 'video-minutes',
          ).map((opt) => (
            <button
              key={opt.value}
              onClick={() => handleExport(opt.value)}
              className="w-full text-left px-3 py-2.5 hover:bg-primary-5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-inset transition-colors border-b border-gray-50 last:border-b-0"
            >
              <span className="text-sm font-medium text-gray-800">{opt.label}</span>
              <span className="block text-xs text-gray-400 mt-0.5">{opt.desc}</span>
            </button>
          ))}
        </div>
      )}

      {error && (
        <p className="mt-1 text-xs text-error text-center">{error}</p>
      )}
    </div>
  );
}
