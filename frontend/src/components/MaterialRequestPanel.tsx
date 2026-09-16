'use client';

/**
 * MaterialRequestPanel — 요구자료(의원 자료 제출 요구) 감지 목록 패널
 *
 * 실시간 자막 모니터링 직원용:
 * - 라이브: WS 감지 이벤트로 실시간 갱신 (새 항목 하이라이트)
 * - VOD: 'AI 스캔' 버튼으로 사후 분석
 * - 각 항목: 확인/무시 처리, KMS 등록용 제목 복사 ("OOO 의원 요구자료(제목)")
 * 의회사무처는 이 목록을 참고해 별도 시스템(KMS)에 공식 등록한다.
 */

import { useState } from 'react';

import { Button } from '@/components/ui';
import type { MaterialRequestType } from '@/types';

export interface MaterialRequestPanelProps {
  requests: MaterialRequestType[];
  isLoading?: boolean;
  /** 상태/내용 수정 콜백 */
  onUpdate: (
    requestId: string,
    updates: Partial<Pick<MaterialRequestType, 'status' | 'summary' | 'councilor_name'>>
  ) => Promise<void> | void;
  /** VOD 전체 스캔 (미지정 시 버튼 숨김 — 라이브 모드) */
  onScan?: () => Promise<number>;
  /** 발언 시각 점프 (미지정 시 시각 비활성 표시). subtitleId는 자막 패널 스크롤 연동용. */
  onJumpTo?: (seconds: number, subtitleId?: string | null) => void;
  /** 수동 추가 */
  onAddManual?: (body: { summary: string; councilor_name?: string }) => Promise<void>;
  /** 전체 화면 보기 링크 (지정 시 헤더에 새 창 링크 노출) */
  fullViewHref?: string;
  /** 전체 화면 모드 — 목록 높이 제한·인용문 줄임 없이 모두 표시 */
  fullHeight?: boolean;
  className?: string;
}

function formatTime(seconds: number | null | undefined): string {
  if (seconds == null) return '--:--';
  const s = Math.floor(seconds);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (h > 0) return `${h}:${String(m).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`;
  return `${m}:${String(s % 60).padStart(2, '0')}`;
}

/** KMS 등록 관례 제목: "이혜원 의원 요구자료(지방채 발행 검토 자료)" */
function kmsTitle(r: MaterialRequestType): string {
  const who = r.councilor_name ? `${r.councilor_name} 의원 ` : '';
  return `${who}요구자료(${r.summary})`;
}

interface ChipStyle {
  label: string;
  cls: string;
}

const CONFIDENCE_FALLBACK: ChipStyle = {
  label: '중간',
  cls: 'bg-warning-bg/20 text-warning-dark',
};
const CONFIDENCE_LABEL: Record<string, ChipStyle> = {
  high: { label: '높음', cls: 'bg-success/10 text-success' },
  medium: CONFIDENCE_FALLBACK,
  low: { label: '낮음', cls: 'bg-gray-100 text-gray-500' },
};

const STATUS_FALLBACK: ChipStyle = { label: '미확인', cls: 'bg-info/10 text-info' };
const STATUS_LABEL: Record<string, ChipStyle> = {
  detected: STATUS_FALLBACK,
  confirmed: { label: '확인됨', cls: 'bg-primary-5 text-primary-dark' },
  dismissed: { label: '무시됨', cls: 'bg-gray-100 text-gray-400 line-through' },
  registered: { label: 'KMS 등록됨', cls: 'bg-success/10 text-success' },
};

export default function MaterialRequestPanel({
  requests,
  isLoading = false,
  onUpdate,
  onScan,
  onJumpTo,
  onAddManual,
  fullViewHref,
  fullHeight = false,
  className = '',
}: MaterialRequestPanelProps) {
  const [isScanning, setIsScanning] = useState(false);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [showDismissed, setShowDismissed] = useState(false);
  const [showAddForm, setShowAddForm] = useState(false);
  const [manualSummary, setManualSummary] = useState('');
  const [manualCouncilor, setManualCouncilor] = useState('');

  const visible = showDismissed
    ? requests
    : requests.filter((r) => r.status !== 'dismissed');
  const pendingCount = requests.filter((r) => r.status === 'detected').length;
  const dismissedCount = requests.filter((r) => r.status === 'dismissed').length;

  const handleScan = async () => {
    if (!onScan) return;
    try {
      setIsScanning(true);
      await onScan();
    } catch (e) {
      alert(e instanceof Error ? e.message : '요구자료 스캔에 실패했습니다.');
    } finally {
      setIsScanning(false);
    }
  };

  const handleCopy = async (r: MaterialRequestType) => {
    try {
      await navigator.clipboard.writeText(kmsTitle(r));
      setCopiedId(r.id);
      setTimeout(() => setCopiedId(null), 1500);
    } catch {
      // 클립보드 권한 없음 — 무시
    }
  };

  const handleAddManual = async () => {
    if (!onAddManual || manualSummary.trim().length < 2) return;
    await onAddManual({
      summary: manualSummary.trim(),
      councilor_name: manualCouncilor.trim() || undefined,
    });
    setManualSummary('');
    setManualCouncilor('');
    setShowAddForm(false);
  };

  return (
    <div
      data-testid="material-request-panel"
      className={`bg-white border border-border rounded-lg ${className}`.trim()}
    >
      {/* 헤더 */}
      <div className="flex items-center justify-between gap-2 px-4 py-3 border-b border-border">
        <div className="flex items-center gap-2 min-w-0">
          <h3 className="text-sm font-semibold text-gray-900 whitespace-nowrap">
            요구자료 감지
          </h3>
          {pendingCount > 0 && (
            <span
              data-testid="material-request-pending-badge"
              className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold bg-error/10 text-error whitespace-nowrap"
            >
              미확인 {pendingCount}
            </span>
          )}
          <span className="text-xs text-gray-400 whitespace-nowrap">
            총 {requests.length}건
          </span>
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          {fullViewHref && (
            <a
              href={fullViewHref}
              target="_blank"
              rel="noreferrer"
              className="px-1.5 py-1 text-xs text-primary hover:underline whitespace-nowrap focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary rounded"
              title="요구자료 목록을 새 창에서 크게 봅니다"
              data-testid="material-request-full-view"
            >
              전체 화면 ↗
            </a>
          )}
          {onAddManual && (
            <Button
              variant="text"
              size="sm"
              onClick={() => setShowAddForm((v) => !v)}
              data-testid="material-request-add-toggle"
            >
              + 수동 추가
            </Button>
          )}
          {onScan && (
            <Button
              variant="secondary"
              size="sm"
              onClick={handleScan}
              loading={isScanning}
              data-testid="material-request-scan-button"
              title="회의 전체 자막을 AI로 분석해 요구자료를 감지합니다"
            >
              {isScanning ? '분석 중...' : 'AI 스캔'}
            </Button>
          )}
        </div>
      </div>

      {/* 수동 추가 폼 */}
      {showAddForm && onAddManual && (
        <div className="flex flex-wrap items-center gap-2 px-4 py-2.5 border-b border-border bg-surface-raised">
          <input
            value={manualCouncilor}
            onChange={(e) => setManualCouncilor(e.target.value)}
            placeholder="요구 의원"
            className="w-24 px-2 py-1.5 text-sm border border-gray-300 rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
            data-testid="material-request-manual-councilor"
          />
          <input
            value={manualSummary}
            onChange={(e) => setManualSummary(e.target.value)}
            placeholder="요청 자료 제목 (예: 지방채 발행 검토 자료)"
            className="flex-1 min-w-[180px] px-2 py-1.5 text-sm border border-gray-300 rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
            data-testid="material-request-manual-summary"
            onKeyDown={(e) => {
              if (e.key === 'Enter') void handleAddManual();
            }}
          />
          <Button
            size="sm"
            onClick={() => void handleAddManual()}
            disabled={manualSummary.trim().length < 2}
            data-testid="material-request-manual-submit"
          >
            추가
          </Button>
        </div>
      )}

      {/* 목록 */}
      {isLoading ? (
        <div className="px-4 py-6 text-center text-sm text-gray-400">불러오는 중...</div>
      ) : visible.length === 0 ? (
        <div
          data-testid="material-request-empty"
          className="px-4 py-6 text-center text-sm text-gray-400"
        >
          {requests.length === 0
            ? onScan
              ? '감지된 요구자료가 없습니다. AI 스캔으로 분석할 수 있습니다.'
              : '아직 감지된 요구자료가 없습니다. 의원 발언에서 자동 감지됩니다.'
            : '무시 처리된 항목만 있습니다.'}
        </div>
      ) : (
        <ul
          className={`divide-y divide-gray-100 ${
            fullHeight ? '' : 'max-h-96 overflow-y-auto'
          }`.trim()}
        >
          {visible.map((r) => {
            const conf = CONFIDENCE_LABEL[r.confidence] ?? CONFIDENCE_FALLBACK;
            const st = STATUS_LABEL[r.status] ?? STATUS_FALLBACK;
            return (
              <li key={r.id} className="px-4 py-2.5" data-testid="material-request-item">
                <div className="flex items-start gap-2">
                  <button
                    type="button"
                    onClick={() => r.start_time != null && onJumpTo?.(r.start_time, r.subtitle_id)}
                    disabled={!onJumpTo || r.start_time == null}
                    className="text-xs text-primary tabular-nums whitespace-nowrap pt-0.5 disabled:text-gray-400 disabled:cursor-default hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary rounded"
                    title={onJumpTo ? '해당 발언 시점으로 이동' : undefined}
                  >
                    {formatTime(r.start_time)}
                  </button>
                  <div className="flex-1 min-w-0">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <span className="text-sm font-medium text-gray-900">
                        {r.councilor_name || r.speaker || '화자 미상'}
                      </span>
                      <span className={`px-1.5 py-0.5 rounded text-[11px] font-medium ${st.cls}`}>
                        {st.label}
                      </span>
                      <span
                        className={`px-1.5 py-0.5 rounded text-[11px] ${conf.cls}`}
                        title="AI 감지 신뢰도"
                      >
                        {conf.label}
                      </span>
                      {r.department && (
                        <span className="text-[11px] text-gray-500">{r.department}</span>
                      )}
                    </div>
                    <p className="text-sm text-gray-800 mt-0.5 break-keep">{r.summary}</p>
                    {r.request_text &&
                      (fullHeight ? (
                        <p className="text-xs text-gray-500 mt-0.5 leading-relaxed">
                          “{r.request_text}”
                        </p>
                      ) : (
                        <p
                          className="text-xs text-gray-500 mt-0.5 line-clamp-4 cursor-pointer"
                          title="클릭하면 전체 발언을 펼칩니다"
                          onClick={(e) => {
                            e.stopPropagation();
                            e.currentTarget.classList.toggle('line-clamp-4');
                          }}
                        >
                          “{r.request_text}”
                        </p>
                      ))}
                  </div>
                  <div className="flex items-center gap-1 shrink-0">
                    {r.status === 'detected' && (
                      <>
                        <button
                          type="button"
                          onClick={() => void onUpdate(r.id, { status: 'confirmed' })}
                          className="px-2 py-1 text-xs rounded-md bg-primary-5 text-primary-dark hover:bg-primary-10 whitespace-nowrap focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
                          data-testid="material-request-confirm"
                        >
                          확인
                        </button>
                        <button
                          type="button"
                          onClick={() => void onUpdate(r.id, { status: 'dismissed' })}
                          className="px-2 py-1 text-xs rounded-md text-gray-500 hover:bg-gray-50 whitespace-nowrap focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
                          data-testid="material-request-dismiss"
                        >
                          무시
                        </button>
                      </>
                    )}
                    {r.status === 'confirmed' && (
                      <button
                        type="button"
                        onClick={() => void onUpdate(r.id, { status: 'registered' })}
                        className="px-2 py-1 text-xs rounded-md text-success hover:bg-success/5 whitespace-nowrap focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
                        title="KMS에 공식 등록을 마친 뒤 표시"
                        data-testid="material-request-mark-registered"
                      >
                        등록 완료
                      </button>
                    )}
                    <button
                      type="button"
                      onClick={() => void handleCopy(r)}
                      className="px-2 py-1 text-xs rounded-md text-gray-500 hover:bg-gray-50 whitespace-nowrap focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
                      title={`KMS 등록용 제목 복사: ${kmsTitle(r)}`}
                      data-testid="material-request-copy"
                    >
                      {copiedId === r.id ? '복사됨 ✓' : '복사'}
                    </button>
                  </div>
                </div>
              </li>
            );
          })}
        </ul>
      )}

      {/* 푸터: 무시 항목 토글 */}
      {dismissedCount > 0 && (
        <div className="px-4 py-2 border-t border-border">
          <button
            type="button"
            onClick={() => setShowDismissed((v) => !v)}
            className="text-xs text-gray-400 hover:text-gray-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary rounded"
            data-testid="material-request-toggle-dismissed"
          >
            {showDismissed ? '무시된 항목 숨기기' : `무시된 항목 보기 (${dismissedCount})`}
          </button>
        </div>
      )}
    </div>
  );
}
