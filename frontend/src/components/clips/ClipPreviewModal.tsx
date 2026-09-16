'use client';

import React, { useCallback, useEffect, useRef, useState } from 'react';

import Modal from '@/components/ui/Modal';
import { fetchClipJobFile, saveBlob } from '@/lib/api';
import type { ClipJobType } from '@/types';
import { formatBytes, formatHMS, formatLen } from '@/utils/clipTime';

/**
 * 「받기 전에 재생해 확인」 (2026-09-16 사용자 요청)
 *
 * 자동 클립의 구간 정확도는 99% 가 아니다(392회 위원회 전수 80.9%, 규칙 보강 뒤 94.0% —
 * `docs/clip-slot-accuracy-eval-2026-09.md`). 그래서 화면은 늘 "공유하기 전에 한 번 재생해
 * 확인해 주세요" 라고 적어 두는데, 정작 그 화면에서 재생할 방법이 없었다.
 *
 * ★ 원본 회의영상의 그 구간이 아니라 **잘라 둔 mp4 파일 자체**를 재생한다(사용자 결정) —
 *   사람이 맞는지뿐 아니라 파일이 제대로 만들어졌는지도 함께 본다.
 * ★ 재생에 쓴 blob 을 그대로 저장한다 — 확인하고 받는데 두 번 내려받지 않는다.
 * ★ blob 은 한 번에 하나만 들고 있는다(닫으면 revoke) — 20MB 짜리를 쌓아 두지 않는다.
 */

/** 이 크기를 넘으면 받기 전에 한 번 묻는다 — 수동 클립(-c copy)은 100MB 를 넘는다 */
const CONFIRM_BYTES = 80 * 1024 * 1024;

export interface ClipPreviewTarget {
  job: ClipJobType;
  fileName: string;
  bytes: number;
  no?: number;
  seg?: { start: number; end: number };
}

export interface ClipPreviewModalProps {
  target: ClipPreviewTarget | null;
  onClose: () => void;
}

export default function ClipPreviewModal({ target, onClose }: ClipPreviewModalProps) {
  const [url, setUrl] = useState<string | null>(null);
  const [blob, setBlob] = useState<Blob | null>(null);
  const [ratio, setRatio] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const urlRef = useRef<string | null>(null);

  const release = useCallback(() => {
    if (urlRef.current) {
      URL.revokeObjectURL(urlRef.current);
      urlRef.current = null;
    }
  }, []);

  const big = !!target && target.bytes > CONFIRM_BYTES;
  const shouldLoad = !!target && (!big || confirmed);

  useEffect(() => {
    setConfirmed(false);
    setErr(null);
    setRatio(null);
    setBlob(null);
    setUrl(null);
    release();
  }, [target, release]);

  useEffect(() => {
    if (!target || !shouldLoad) return;
    const controller = new AbortController();
    let cancelled = false;
    setLoading(true);
    setErr(null);
    setRatio(0);

    void (async () => {
      try {
        const got = await fetchClipJobFile(
          target.job.meeting_id,
          target.job.job_id,
          target.fileName,
          (r) => {
            if (!cancelled) setRatio(r);
          },
          controller.signal
        );
        if (cancelled) return;
        const objectUrl = URL.createObjectURL(got.blob);
        urlRef.current = objectUrl;
        setBlob(got.blob);
        setUrl(objectUrl);
      } catch (e) {
        if (cancelled || controller.signal.aborted) return;
        setErr(e instanceof Error ? e.message : '영상을 불러오지 못했습니다.');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [target, shouldLoad]);

  // 언마운트 때도 반드시 회수한다
  useEffect(() => release, [release]);

  const close = () => {
    release();
    setUrl(null);
    setBlob(null);
    onClose();
  };

  if (!target) return null;

  const { job, fileName, bytes, no, seg } = target;
  const who = job.speaker_name || job.label || '클립';
  const pct = ratio === null ? 0 : Math.round(ratio * 100);

  return (
    <Modal
      isOpen
      onClose={close}
      size="lg"
      title={
        <span className="flex flex-wrap items-baseline gap-2">
          <span>{who}</span>
          {no ? <span className="text-[13px] font-normal text-text-muted">#{no}</span> : null}
          <span className="text-[12px] font-normal text-text-muted tabular-nums">
            {seg ? `${formatHMS(seg.start)} · ${formatLen(seg.end - seg.start)} · ` : ''}
            {formatBytes(bytes)}
          </span>
        </span>
      }
      footer={
        <>
          <button
            type="button"
            className="rounded-md border border-border bg-white px-3 py-1.5 text-[13px] hover:bg-gray-50"
            onClick={close}
          >
            닫기
          </button>
          <button
            type="button"
            data-testid="clip-preview-save"
            disabled={!blob}
            className="rounded-md bg-primary px-3 py-1.5 text-[13px] font-semibold text-white disabled:opacity-50"
            onClick={() => blob && saveBlob(blob, fileName)}
          >
            ⬇ 이 파일 받기
          </button>
        </>
      }
    >
      <div data-testid="clip-preview-modal" className="flex flex-col gap-3">
        {big && !confirmed && (
          <div className="rounded-md border border-border bg-surface-raised p-3 text-[13px]">
            <p className="mb-2">
              이 영상은 <strong className="tabular-nums">{formatBytes(bytes)}</strong> 입니다.
              재생하려면 먼저 받아야 하므로 잠시 걸립니다.
            </p>
            <button
              type="button"
              data-testid="clip-preview-confirm"
              className="rounded-md bg-primary px-3 py-1.5 text-[13px] font-semibold text-white"
              onClick={() => setConfirmed(true)}
            >
              받아서 재생하기
            </button>
          </div>
        )}

        {shouldLoad && loading && (
          <div className="flex flex-col gap-2 rounded-lg bg-black/5 p-6">
            <div className="text-[13px] text-text-muted tabular-nums">
              영상을 받는 중… {ratio !== null && ratio > 0 ? `${pct}%` : ''}
            </div>
            <div className="h-2 overflow-hidden rounded bg-gray-200">
              {ratio !== null && ratio > 0 ? (
                <div
                  data-testid="clip-preview-progress"
                  className="h-full bg-primary transition-all"
                  style={{ width: `${pct}%` }}
                />
              ) : (
                <div className="h-full w-full animate-pulse bg-primary/60" />
              )}
            </div>
          </div>
        )}

        {err && <div className="text-[13px] text-red-700">{err}</div>}

        {url && (
          // eslint-disable-next-line jsx-a11y/media-has-caption -- 발언 영상 원본, 자막은 별도 SRT 로 받는다
          <video
            data-testid="clip-preview-video"
            src={url}
            controls
            autoPlay
            className="max-h-[60vh] w-full rounded-lg bg-black"
          />
        )}

        <p className="text-[12px] leading-relaxed text-text-muted">
          {job.origin === 'auto'
            ? '⚠ AI 가 자막으로 찾은 구간을 자동으로 자른 영상입니다. 드물게 다른 사람의 발언이 섞일 수 있으니, 공유하기 전에 이 화면에서 확인해 주세요.'
            : '내려받을 파일 그대로입니다.'}
        </p>
        <p className="truncate text-[11px] text-text-muted" title={fileName}>
          {fileName}
        </p>
      </div>
    </Modal>
  );
}
