'use client';

/**
 * 의원 상세 (2026-09-16 담당자 요청 — "사진도 나오고 상세 정보도")
 *
 * 한 곳에서 두 군데가 쓴다: 위원 명단에서 누른 의원, 영상 화면에서 찾은 의원.
 * 그래서 이 컴포넌트는 **의원 id 만 받는다** — 어디서 열렸는지 모른다.
 *
 * 약력은 의회 홈페이지에만 있어 서버가 처음 열람할 때 가져와 DB 에 담는다. 못 가져와도
 * 화면은 뜬다(약력 자리에 안내만 뜬다) — 외부 사이트 하나 때문에 상세가 죽지 않게 한다.
 */

import React, { useCallback, useEffect, useState } from 'react';

import { API_BASE_URL, getCouncilorDetail } from '@/lib/api';
import type { CouncilorDetailType } from '@/lib/api';

interface CouncilorDetailModalProps {
  councilorId: string | null;
  /** 아직 상세를 못 받았을 때 먼저 보여 줄 이름 — 모달이 빈 채로 뜨지 않게 한다 */
  fallbackName?: string | null;
  isOpen: boolean;
  onClose: () => void;
  /** 발언을 눌렀을 때 — 해당 회의 화면으로 보낸다. 없으면 발언이 링크가 아니다. */
  onOpenSpeech?: (speech: { meetingId: string; subtitleId: string; startTime: number | null }) => void;
}

function partyClass(party: string | null | undefined): string {
  const p = party || '';
  if (p.includes('국민의힘')) return 'text-red-600';
  if (p.includes('민주')) return 'text-blue-700';
  return 'text-gray-600';
}

function formatClock(sec: number | null | undefined): string {
  if (sec === null || sec === undefined || Number.isNaN(sec)) return '';
  const s = Math.max(0, Math.floor(sec));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const ss = s % 60;
  const mm = String(m).padStart(2, '0');
  const sss = String(ss).padStart(2, '0');
  return h > 0 ? `${h}:${mm}:${sss}` : `${mm}:${sss}`;
}

export default function CouncilorDetailModal({
  councilorId,
  fallbackName,
  isOpen,
  onClose,
  onOpenSpeech,
}: CouncilorDetailModalProps) {
  const [detail, setDetail] = useState<CouncilorDetailType | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!isOpen || !councilorId) return;
    let alive = true;
    setLoading(true);
    setError(null);
    setDetail(null);
    getCouncilorDetail(councilorId)
      .then((d) => {
        if (alive) setDetail(d);
      })
      .catch(() => {
        if (alive) setError('의원 정보를 불러오지 못했습니다.');
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [isOpen, councilorId]);

  const onKey = useCallback(
    (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    },
    [onClose],
  );

  useEffect(() => {
    if (!isOpen) return;
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [isOpen, onKey]);

  if (!isOpen || !councilorId) return null;

  const c = detail?.councilor;
  const name = c?.name || fallbackName || '';

  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center bg-black/50 p-4"
      role="dialog"
      aria-label={`${name} 의원 정보`}
      onClick={onClose}
    >
      <div
        className="flex max-h-[88vh] w-full max-w-2xl flex-col rounded-lg bg-white shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b px-5 py-3.5">
          <h2 className="text-base font-bold text-gray-900">의원 정보</h2>
          <button
            type="button"
            onClick={onClose}
            className="text-lg text-gray-400 hover:text-gray-600"
            aria-label="닫기"
            data-testid="councilor-detail-close"
          >
            ✕
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-5">
          {error && <p className="py-8 text-center text-sm text-red-600">{error}</p>}
          {loading && !detail && (
            <p className="py-10 text-center text-sm text-gray-400">
              <span className="mr-2 inline-block h-4 w-4 animate-spin rounded-full border-2 border-gray-300 border-t-transparent align-middle" />
              불러오는 중…
            </p>
          )}

          {detail && c && (
            <>
              {/* 머리 — 사진과 기본 사항 */}
              <div className="flex gap-4">
                <img
                  src={`${API_BASE_URL}/api/councilors/${c.id}/photo`}
                  alt={`${name} 의원 사진`}
                  className="h-[150px] w-[112px] shrink-0 rounded-md bg-gray-100 object-cover"
                  onError={(e) => {
                    const el = e.currentTarget;
                    if (c.profile_image_url && el.src !== c.profile_image_url) {
                      el.src = c.profile_image_url;
                    } else {
                      el.style.display = 'none';
                    }
                  }}
                />
                <div className="min-w-0 flex-1">
                  <p className="text-xl font-bold text-gray-900">{name}</p>
                  <p className={`mt-0.5 text-sm font-medium ${partyClass(c.party)}`}>{c.party}</p>
                  <dl className="mt-3 space-y-1.5 text-sm">
                    <div className="flex gap-2">
                      <dt className="w-16 shrink-0 text-gray-500">선거구</dt>
                      <dd className="text-gray-800">{c.district || '-'}</dd>
                    </div>
                    {detail.positions.length > 0 && (
                      <div className="flex gap-2">
                        <dt className="w-16 shrink-0 text-gray-500">직책</dt>
                        <dd className="text-gray-800">{detail.positions.join(' · ')}</dd>
                      </div>
                    )}
                    {c.office_number && (
                      <div className="flex gap-2">
                        <dt className="w-16 shrink-0 text-gray-500">사무실</dt>
                        <dd className="text-gray-800">{c.office_number}</dd>
                      </div>
                    )}
                  </dl>
                  {c.homepage_url && (
                    <a
                      href={c.homepage_url}
                      target="_blank"
                      rel="noreferrer"
                      className="mt-3 inline-block text-xs font-medium text-brand hover:underline"
                    >
                      의원 홈페이지 ↗
                    </a>
                  )}
                </div>
              </div>

              {/* 상임위 */}
              <section className="mt-6">
                <h3 className="mb-2 text-sm font-bold text-gray-900">소속 위원회</h3>
                {(c.committees || []).length > 0 ? (
                  <ul className="flex flex-wrap gap-2">
                    {(c.committees || []).map((cm) => (
                      <li
                        key={`${cm.name}-${cm.role}`}
                        className="rounded-full border border-gray-200 bg-gray-50 px-3 py-1 text-xs text-gray-700"
                      >
                        {cm.name}
                        {cm.role && cm.role !== '위원' && (
                          <span className="ml-1 font-bold text-brand">{cm.role}</span>
                        )}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-xs text-gray-400">등록된 위원회 정보가 없습니다.</p>
                )}
              </section>

              {/* 약력 */}
              <section className="mt-6">
                <h3 className="mb-2 text-sm font-bold text-gray-900">약력</h3>
                {detail.career.length > 0 ? (
                  <ul className="space-y-1">
                    {detail.career.map((line, i) => (
                      <li key={`${line}-${i}`} className="flex gap-2 text-sm text-gray-700">
                        <span className="mt-[7px] h-1 w-1 shrink-0 rounded-full bg-gray-300" />
                        <span>{line}</span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-xs text-gray-400">
                    의회 홈페이지에서 약력을 가져오지 못했습니다.
                  </p>
                )}
              </section>

              {/* 최근 발언 */}
              <section className="mt-6">
                <h3 className="mb-2 text-sm font-bold text-gray-900">
                  최근 발언
                  {detail.recent_speeches.length > 0 && (
                    <span className="ml-2 text-xs font-normal text-gray-400">
                      {detail.recent_speeches.length}건
                    </span>
                  )}
                </h3>
                {detail.recent_speeches.length > 0 ? (
                  <ul className="space-y-2">
                    {detail.recent_speeches.map((s) => {
                      const body = (
                        <>
                          <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11px] text-gray-500">
                            <span>{s.meeting_date || ''}</span>
                            {s.committee && <span>· {s.committee}</span>}
                            {s.start_time !== null && <span>· {formatClock(s.start_time)}</span>}
                          </div>
                          <p className="mt-1 line-clamp-2 text-sm text-gray-800">{s.text}</p>
                        </>
                      );
                      return (
                        <li key={s.subtitle_id}>
                          {onOpenSpeech ? (
                            <button
                              type="button"
                              onClick={() =>
                                onOpenSpeech({
                                  meetingId: s.meeting_id,
                                  subtitleId: s.subtitle_id,
                                  startTime: s.start_time,
                                })
                              }
                              className="w-full rounded-md border border-gray-200 p-2.5 text-left transition-colors hover:border-brand/40 hover:bg-brand/[0.03]"
                            >
                              {body}
                            </button>
                          ) : (
                            <div className="rounded-md border border-gray-200 p-2.5">{body}</div>
                          )}
                        </li>
                      );
                    })}
                  </ul>
                ) : (
                  <p className="text-xs text-gray-400">
                    이 의원의 자막 발언 기록이 아직 없습니다.
                  </p>
                )}
              </section>
            </>
          )}
        </div>

        <div className="rounded-b-lg border-t bg-gray-50 px-5 py-3">
          <span className="text-[11px] text-gray-400">
            출처: 경기도의회 공식 명단·의원 홈페이지 (제12대) · 발언은 이 서비스의 자막 기록
          </span>
        </div>
      </div>
    </div>
  );
}
