'use client';

/**
 * 전자회의록 미리보기·편집 모달
 *
 * 백엔드 마크다운 중간층(GET /minutes-markdown)을 불러와 간단 렌더로 미리보고,
 * 편집(textarea) 후 kordoc 공문서 서식 hwpx(POST /export/hwpx-from-markdown)로
 * 다운로드한다. 기본 서식(native) hwpx 다운로드도 함께 제공.
 */

import React, { useEffect, useRef, useState } from 'react';

import { Button } from '@/components/ui';
import { downloadHwpx, downloadHwpxFromMarkdown, getMinutesMarkdown } from '@/lib/api';

interface MinutesPreviewModalProps {
  meetingId: string;
  isOpen: boolean;
  onClose: () => void;
}

/** '**굵게**' 인라인 구문을 <strong> React 요소로 변환 (dangerouslySetInnerHTML 미사용) */
function renderInline(text: string): React.ReactNode[] {
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  return parts.map((part, i) => {
    if (part.startsWith('**') && part.endsWith('**') && part.length > 4) {
      return <strong key={i}>{part.slice(2, -2)}</strong>;
    }
    return <React.Fragment key={i}>{part}</React.Fragment>;
  });
}

/** 마크다운을 줄 단위로 파싱해 React 요소로 렌더 (헤딩 #~###, 굵게, ○ 발언 단락) */
function renderMarkdown(markdown: string): React.ReactNode[] {
  return markdown.split('\n').map((line, i) => {
    if (line.startsWith('### ')) {
      return (
        <h4 key={i} className="text-sm font-semibold text-gray-900 mt-4 mb-1">
          {renderInline(line.slice(4))}
        </h4>
      );
    }
    if (line.startsWith('## ')) {
      return (
        <h3 key={i} className="text-base font-semibold text-gray-900 mt-5 mb-1.5">
          {renderInline(line.slice(3))}
        </h3>
      );
    }
    if (line.startsWith('# ')) {
      return (
        <h2 key={i} className="text-lg font-bold text-gray-900 mt-2 mb-2 text-center">
          {renderInline(line.slice(2))}
        </h2>
      );
    }
    if (line.trim() === '') {
      return <div key={i} className="h-2" aria-hidden="true" />;
    }
    // '○' 발언 단락 — 공식 회의록의 발언 시작 표기
    if (line.trimStart().startsWith('○')) {
      return (
        <p key={i} className="text-sm text-gray-800 leading-relaxed mt-2 pl-2 -indent-2">
          {renderInline(line)}
        </p>
      );
    }
    return (
      <p key={i} className="text-sm text-gray-700 leading-relaxed">
        {renderInline(line)}
      </p>
    );
  });
}

export default function MinutesPreviewModal({
  meetingId,
  isOpen,
  onClose,
}: MinutesPreviewModalProps) {
  const [markdown, setMarkdown] = useState<string | null>(null);
  const [kordocAvailable, setKordocAvailable] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [mode, setMode] = useState<'preview' | 'edit'>('preview');
  const [busy, setBusy] = useState<'edited' | 'native' | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  // 진행 중 중복 요청 방지 (state 대신 ref — effect 재실행/cleanup 에 휘둘리지 않음)
  const inFlightRef = useRef(false);

  // 열릴 때 마크다운 로드 (한 번 로드하면 편집 내용 보존을 위해 재요청하지 않음)
  useEffect(() => {
    if (!isOpen || markdown !== null || inFlightRef.current) return;
    inFlightRef.current = true;
    setIsLoading(true);
    setLoadError(null);
    getMinutesMarkdown(meetingId)
      .then((res) => {
        setMarkdown(res.markdown);
        setKordocAvailable(res.kordoc_available);
      })
      .catch((err) => {
        setLoadError(
          err instanceof Error ? err.message : '회의록 마크다운을 불러오지 못했습니다.'
        );
      })
      .finally(() => {
        inFlightRef.current = false;
        setIsLoading(false);
      });
  }, [isOpen, markdown, meetingId]);

  if (!isOpen) return null;

  const handleDownloadEdited = async () => {
    if (markdown === null) return;
    try {
      setBusy('edited');
      setActionError(null);
      await downloadHwpxFromMarkdown(meetingId, markdown);
    } catch (err) {
      setActionError(
        err instanceof Error ? err.message : '수정본 HWPX 다운로드에 실패했습니다.'
      );
    } finally {
      setBusy(null);
    }
  };

  const handleDownloadNative = async () => {
    try {
      setBusy('native');
      setActionError(null);
      await downloadHwpx(meetingId);
    } catch (err) {
      setActionError(
        err instanceof Error ? err.message : '기본 서식 HWPX 다운로드에 실패했습니다.'
      );
    } finally {
      setBusy(null);
    }
  };

  const editedDisabled =
    busy !== null || isLoading || markdown === null || !kordocAvailable;
  const editedDisabledReason = !kordocAvailable
    ? 'kordoc 엔진을 사용할 수 없습니다 — 서버에 Node.js(npx)가 필요합니다.'
    : '편집된 마크다운을 kordoc 공문서 서식 HWPX로 다운로드합니다.';

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
      role="dialog"
      aria-label="전자회의록 미리보기·편집"
    >
      <div className="mx-4 w-full max-w-4xl rounded-lg bg-white shadow-xl flex flex-col max-h-[90vh]">
        {/* Header */}
        <div className="flex items-center justify-between border-b px-6 py-4">
          <div className="flex items-center gap-4">
            <h2 className="text-lg font-semibold text-gray-900">
              전자회의록 미리보기·편집
            </h2>
            <div className="inline-flex rounded-md border border-gray-200 overflow-hidden">
              <button
                type="button"
                data-testid="mode-preview-button"
                onClick={() => setMode('preview')}
                className={`px-3 py-1 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary ${
                  mode === 'preview'
                    ? 'bg-primary text-white'
                    : 'bg-white text-gray-600 hover:bg-gray-50'
                }`}
              >
                미리보기
              </button>
              <button
                type="button"
                data-testid="mode-edit-button"
                onClick={() => setMode('edit')}
                className={`px-3 py-1 text-xs font-medium border-l border-gray-200 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary ${
                  mode === 'edit'
                    ? 'bg-primary text-white'
                    : 'bg-white text-gray-600 hover:bg-gray-50'
                }`}
              >
                편집
              </button>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary rounded"
            aria-label="닫기"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-6">
          {isLoading && (
            <div className="flex items-center justify-center py-12" role="status">
              <span className="inline-block h-6 w-6 animate-spin rounded-full border-2 border-primary border-t-transparent" />
              <span className="ml-2 text-sm text-gray-500">회의록 마크다운 불러오는 중...</span>
            </div>
          )}

          {loadError && !isLoading && (
            <p className="text-sm text-error py-4" role="alert">
              {loadError}
            </p>
          )}

          {markdown !== null && !isLoading && (
            mode === 'edit' ? (
              <textarea
                data-testid="markdown-editor"
                aria-label="회의록 마크다운 편집"
                value={markdown}
                onChange={(e) => setMarkdown(e.target.value)}
                spellCheck={false}
                className="w-full min-h-[60vh] font-mono text-sm text-gray-800 border border-gray-300 rounded-md p-3 focus:outline-none focus:border-primary focus:ring-2 focus:ring-primary resize-y"
              />
            ) : (
              <div data-testid="markdown-preview">{renderMarkdown(markdown)}</div>
            )
          )}
        </div>

        {/* Footer */}
        <div className="border-t px-6 py-4">
          {actionError && (
            <p className="text-sm text-error mb-2" role="alert">
              {actionError}
            </p>
          )}
          <div className="flex items-center justify-between gap-3 flex-wrap">
            <p className="text-xs text-gray-500">
              수정본은 kordoc 공문서 서식으로 생성됩니다. 한글(HWP)에서 열림 확인 후 사용하세요.
            </p>
            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                size="md"
                data-testid="download-native-hwpx-button"
                onClick={handleDownloadNative}
                disabled={busy !== null}
                loading={busy === 'native'}
                title="기본(native) 서식의 전자회의록 HWPX를 다운로드합니다."
              >
                {busy === 'native' ? '생성 중...' : '기본 서식 HWPX'}
              </Button>
              <Button
                variant="primary"
                size="md"
                data-testid="download-edited-hwpx-button"
                onClick={handleDownloadEdited}
                disabled={editedDisabled}
                loading={busy === 'edited'}
                title={editedDisabledReason}
              >
                {busy === 'edited' ? '생성 중...' : '수정본 HWPX 다운로드'}
              </Button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
