'use client';

/**
 * 부서별 회의 문서 만들기(2026-09-15 담당자 요청) — 버튼으로만 만든다(자동 생성 안 함, 담당자 결정).
 * 서식: [서식1] 업무보고 모니터링 · [서식2] 자료요구 목록 · [서식3] 의원 요구자료 표지 · 보도자료(일반 형식 초안).
 * 모니터링·보도자료는 AI 가 초안을 뽑아 30초~1분 걸린다. 같은 회의를 부서만 바꿔 받으면 서버 캐시라 바로 온다.
 */

import React, { useEffect, useState } from 'react';

import Modal from '@/components/ui/Modal';
import {
  ApiError,
  downloadMeetingDocument,
  getMeetingDocumentOptions,
  type MeetingDocumentKind,
  type MeetingDocumentOptions,
} from '@/lib/api';

const KINDS: { kind: MeetingDocumentKind; label: string; hint: string }[] = [
  { kind: 'monitoring', label: '업무보고 모니터링', hint: '의원별 질의 내용·답변·부서 표(서식1). AI 초안, 30초~1분' },
  { kind: 'datareq-list', label: '자료요구 목록', hint: '연번·의원명·요구 내용·제출여부·부서(서식2)' },
  { kind: 'datareq-cover', label: '의원 요구자료 표지', hint: '요구 1건당 표지 1장(서식3). 부서 전체는 ZIP 묶음' },
  { kind: 'press', label: '보도자료(초안)', hint: '회의 요약으로 만든 일반 보도자료 초안. 요약이 있어야 한다' },
];

export interface MeetingDocumentsModalProps {
  meetingId: string;
  open: boolean;
  onClose: () => void;
}

export default function MeetingDocumentsModal({ meetingId, open, onClose }: MeetingDocumentsModalProps) {
  const [options, setOptions] = useState<MeetingDocumentOptions | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [kind, setKind] = useState<MeetingDocumentKind>('monitoring');
  const [department, setDepartment] = useState('');
  const [requestId, setRequestId] = useState('');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);

  useEffect(() => {
    if (!open) return undefined;
    let cancelled = false;
    setOptions(null);
    setLoadError(null);
    setMessage(null);
    getMeetingDocumentOptions(meetingId)
      .then((o) => {
        if (!cancelled) setOptions(o);
      })
      .catch((err) => {
        if (cancelled) return;
        setLoadError(
          err instanceof ApiError && (err.status === 401 || err.status === 403)
            ? '문서 만들기는 로그인하거나 의회망에서 쓸 수 있습니다.'
            : '문서 정보를 불러오지 못했습니다.'
        );
      });
    return () => {
      cancelled = true;
    };
  }, [meetingId, open]);

  const requests = (options?.material_requests ?? []).filter((r) => !department || r.department === department);

  const make = async () => {
    setBusy(true);
    setMessage(null);
    try {
      const name = await downloadMeetingDocument(meetingId, kind, {
        department: department || undefined,
        requestId: kind === 'datareq-cover' && requestId ? requestId : undefined,
      });
      setMessage({ ok: true, text: `내려받았습니다: ${name}` });
    } catch (err) {
      setMessage({
        ok: false,
        text:
          err instanceof ApiError
            ? err.status === 429
              ? '오늘 AI 문서 생성 한도를 다 썼습니다. 내일 다시 시도해 주세요.'
              : err.message
            : '문서를 만들지 못했습니다.',
      });
    } finally {
      setBusy(false);
    }
  };

  if (!open) return null;

  // 공통 Modal — 첫 초점 이동·초점 순환·복원·Escape 닫기(키보드 접근성, Codex 검토)
  return (
    <Modal isOpen={open} onClose={onClose} title="문서 만들기" size="md" closeDisabled={busy}>
      <div data-testid="meeting-documents-modal">
        {loadError && <p className="text-[13px] text-red-700" role="alert">{loadError}</p>}
        {!loadError && !options && <p className="text-[13px] text-text-muted">불러오는 중…</p>}
        {options && (
          <div className="flex flex-col gap-3 text-[13px]">
            <fieldset className="flex flex-col gap-1.5">
              <legend className="mb-1 text-[12px] font-bold text-text-dim">종류</legend>
              {KINDS.map((k) => (
                <label key={k.kind} className="flex cursor-pointer items-start gap-2 rounded-md border border-border px-2.5 py-2 hover:bg-surface-raised">
                  <input type="radio" name="doc-kind" checked={kind === k.kind} onChange={() => setKind(k.kind)} className="mt-0.5" />
                  <span>
                    <span className="font-semibold text-text">{k.label}</span>
                    <span className="block text-[12px] text-text-muted">{k.hint}</span>
                  </span>
                </label>
              ))}
            </fieldset>
            <label className="flex flex-col gap-1">
              <span className="text-[12px] font-bold text-text-dim">부서</span>
              <select
                value={department}
                onChange={(e) => {
                  setDepartment(e.target.value);
                  setRequestId('');
                }}
                className="rounded-md border border-border bg-surface px-2 py-1.5"
                aria-label="부서"
              >
                <option value="">전체</option>
                {options.departments.map((d) => (
                  <option key={d} value={d}>
                    {d}
                  </option>
                ))}
              </select>
            </label>
            {kind === 'datareq-cover' && (
              <label className="flex flex-col gap-1">
                <span className="text-[12px] font-bold text-text-dim">요구자료</span>
                <select value={requestId} onChange={(e) => setRequestId(e.target.value)} className="rounded-md border border-border bg-surface px-2 py-1.5" aria-label="요구자료">
                  <option value="">{department ? `${department} 전체 묶음(ZIP)` : '전체 묶음(ZIP)'}</option>
                  {requests.map((r) => (
                    <option key={r.id} value={r.id}>
                      {r.councilor} — {(r.summary ?? '').slice(0, 40)}
                    </option>
                  ))}
                </select>
              </label>
            )}
            {(kind === 'datareq-list' || kind === 'datareq-cover') && options.material_requests.length === 0 && (
              <p className="text-[12px] text-amber-800">이 회의에는 찾은 자료요구가 없습니다. 회의 화면의 [요구자료] 탭에서 먼저 찾아 주세요.</p>
            )}
            {kind === 'press' && !options.has_summary && (
              <p className="text-[12px] text-amber-800">회의 요약이 아직 없습니다. 요약을 먼저 만들어 주세요.</p>
            )}
            <button
              type="button"
              onClick={make}
              disabled={busy}
              data-testid="meeting-documents-make"
              className="mt-1 rounded-md bg-primary px-3 py-2 text-[13.5px] font-semibold text-white hover:bg-primary-light disabled:opacity-50"
            >
              {busy ? (kind === 'monitoring' || kind === 'press' ? 'AI 가 초안을 만드는 중… (30초~1분)' : '만드는 중…') : 'HWPX 내려받기'}
            </button>
            {message && (
              <p className={`text-[12.5px] ${message.ok ? 'text-primary' : 'text-red-700'}`} role={message.ok ? 'status' : 'alert'}>
                {message.text}
              </p>
            )}
            <p className="text-[11.5px] text-text-dim">AI 초안은 자막을 바탕으로 만들었습니다. 제출 전에 내용을 꼭 확인해 주세요.</p>
          </div>
        )}
      </div>
    </Modal>
  );
}
