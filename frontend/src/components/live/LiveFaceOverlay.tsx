'use client';

/**
 * 영상 화면에서 의원 찾기 (2026-09-16 담당자 요청)
 *
 * [의원 찾기]를 누르면 **지금 보고 있는 그 장면**을 캔버스로 한 장 떠서 서버에 보내고,
 * 돌아온 이름을 얼굴 위에 붙인다. 이름을 누르면 약력·상임위·최근 발언이 열린다.
 *
 * 왜 브라우저에서 화면을 뜨는가
 * ---------------------------
 * 라이브는 자막과 맞추려고 영상을 17초쯤 뒤로 잡아 재생한다. 서버가 지금 재생목록에서 받는
 * 장면은 사용자가 보는 장면보다 그만큼 앞서 있어 **다른 사람이 잡힌다.** hls.js 는 세그먼트를
 * XHR 로 받아 MSE 에 넣으므로 캔버스가 오염되지 않아 그대로 뜰 수 있다. 네이티브 HLS(iOS)처럼
 * 캔버스가 막힌 환경에서만 서버 캡처로 물러선다.
 *
 * 왜 상자를 항상 띄우지 않는가
 * --------------------------
 * 영상 위 상시 오버레이는 2026-09-08 에 걷어낸 결정이 있다(자막). 그래서 이 기능도 **누를 때만**
 * 뜨고, 다시 누르면 사라진다. 얼굴은 계속 움직이므로 상자는 뜬 시점의 장면에 대한 것이고,
 * 오래되면(기본 12초) 스스로 흐려져 "지금 화면과 다르다"는 것을 눈으로 알 수 있게 했다.
 */

import React, { useCallback, useEffect, useRef, useState } from 'react';

import CouncilorDetailModal from '@/components/CouncilorDetailModal';
import { identifyFaces, identifyFacesOnChannel } from '@/lib/api';
import type { FaceIdentifyResponse, FaceMatchType } from '@/lib/api';

/** 상자가 "낡았다"고 표시하기까지 (ms) */
const STALE_AFTER_MS = 12_000;

interface LiveFaceOverlayProps {
  videoRef: React.RefObject<HTMLVideoElement | null>;
  channelId?: string | null;
  /** 지금 발언자 이름(자막에서) — 애매한 얼굴의 저울을 기울이는 보조 증거 */
  speakerHint?: string | null;
  /** 방송 중이 아니면 버튼을 내린다 */
  enabled?: boolean;
  className?: string;
}

function captureFrame(video: HTMLVideoElement): Promise<Blob | null> {
  return new Promise((resolve) => {
    const w = video.videoWidth;
    const h = video.videoHeight;
    if (!w || !h) {
      resolve(null);
      return;
    }
    // 긴 변 1280 로 맞춘다 — 얼굴 인식에 충분하고 업로드가 가볍다
    const scale = Math.min(1, 1280 / Math.max(w, h));
    const canvas = document.createElement('canvas');
    canvas.width = Math.round(w * scale);
    canvas.height = Math.round(h * scale);
    const ctx = canvas.getContext('2d');
    if (!ctx) {
      resolve(null);
      return;
    }
    try {
      ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
      canvas.toBlob((b) => resolve(b), 'image/jpeg', 0.9);
    } catch {
      // 캔버스 오염(네이티브 HLS 등) — 서버 캡처로 물러선다
      resolve(null);
    }
  });
}

export default function LiveFaceOverlay({
  videoRef,
  channelId,
  speakerHint,
  enabled = true,
  className = '',
}: LiveFaceOverlayProps) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<FaceIdentifyResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [takenAt, setTakenAt] = useState(0);
  const [stale, setStale] = useState(false);
  const [openId, setOpenId] = useState<string | null>(null);
  const [openName, setOpenName] = useState<string | null>(null);
  const runningRef = useRef(false);

  useEffect(() => {
    if (!open || !takenAt) return;
    setStale(false);
    const t = setTimeout(() => setStale(true), STALE_AFTER_MS);
    return () => clearTimeout(t);
  }, [open, takenAt]);

  // 채널이 바뀌면 이전 결과를 버린다 — 다른 회의의 이름이 남아 있으면 안 된다
  useEffect(() => {
    setResult(null);
    setOpen(false);
    setError(null);
  }, [channelId]);

  const identify = useCallback(async () => {
    if (runningRef.current) return;
    runningRef.current = true;
    setBusy(true);
    setError(null);
    try {
      const video = videoRef.current;
      const blob = video ? await captureFrame(video) : null;
      const res = blob
        ? await identifyFaces(blob, { channelId: channelId || undefined, speakerHint })
        : channelId
          ? await identifyFacesOnChannel(channelId, speakerHint)
          : null;
      if (!res) {
        setError('영상 화면을 읽지 못했습니다.');
      } else if (res.error) {
        setError(res.error);
        setResult(null);
      } else {
        setResult(res);
        setTakenAt(Date.now());
        setOpen(true);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : '의원을 찾지 못했습니다.');
    } finally {
      setBusy(false);
      runningRef.current = false;
    }
  }, [videoRef, channelId, speakerHint]);

  const faces = result?.faces || [];
  const named = faces.filter((f) => f.confident && f.councilor_id);

  if (!enabled) return null;

  return (
    <>
      {/* 조작 줄 — 영상 왼쪽 위. 네이티브 재생 컨트롤(아래쪽)과 겹치지 않는다 */}
      <div className={`pointer-events-none absolute left-2 top-2 z-20 flex flex-col items-start gap-1.5 ${className}`}>
        <div className="pointer-events-auto flex items-center gap-1.5">
          <button
            type="button"
            onClick={() => (open ? setOpen(false) : identify())}
            disabled={busy}
            aria-pressed={open}
            data-testid="face-identify-button"
            title="지금 화면에 나온 의원의 이름을 찾습니다"
            className={`flex h-8 items-center gap-1.5 rounded-md px-2.5 text-[13px] font-medium shadow-sm backdrop-blur transition-colors ${
              open ? 'bg-brand text-white' : 'bg-black/55 text-white hover:bg-black/70'
            } ${busy ? 'cursor-wait opacity-80' : ''}`}
          >
            {busy ? (
              <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-white/40 border-t-white" />
            ) : (
              <svg className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" d="M15 10.5a3 3 0 11-6 0 3 3 0 016 0z" />
                <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 10.5c0 7.142-7.5 11.25-7.5 11.25S4.5 17.642 4.5 10.5a7.5 7.5 0 1115 0z" />
              </svg>
            )}
            {busy ? '찾는 중…' : open ? '의원 찾기 끄기' : '의원 찾기'}
          </button>
          {open && (
            <button
              type="button"
              onClick={identify}
              disabled={busy}
              data-testid="face-identify-refresh"
              title="지금 화면으로 다시 찾습니다"
              className="flex h-8 items-center rounded-md bg-black/55 px-2.5 text-[13px] font-medium text-white shadow-sm backdrop-blur transition-colors hover:bg-black/70"
            >
              다시 찾기
            </button>
          )}
        </div>

        {/* 찾은 의원 — 누르면 약력·상임위·최근 발언 */}
        {open && (
          <div
            className="pointer-events-auto max-w-[min(20rem,70vw)] rounded-md bg-black/55 p-1.5 shadow-sm backdrop-blur"
            data-testid="face-identify-panel"
          >
            {named.length > 0 ? (
              <ul className="flex flex-col gap-1">
                {named.map((f) => (
                  <li key={f.councilor_id}>
                    <button
                      type="button"
                      onClick={() => {
                        setOpenId(f.councilor_id);
                        setOpenName(f.name);
                      }}
                      data-testid="face-identify-name"
                      className="flex w-full items-center gap-2 rounded px-1.5 py-1 text-left text-white transition-colors hover:bg-white/15"
                    >
                      <span className="text-[13px] font-bold">{f.name}</span>
                      <span className="truncate text-[11px] text-white/70">
                        {[f.party, f.district].filter(Boolean).join(' · ')}
                      </span>
                      <span className="ml-auto shrink-0 text-[11px] text-white/50">정보 ›</span>
                    </button>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="px-1.5 py-1 text-[12px] text-white/80">
                {faces.length === 0
                  ? '화면에서 얼굴을 찾지 못했습니다.'
                  : '화면의 얼굴이 의원 명단과 맞지 않습니다. 집행부·직원일 수 있습니다.'}
              </p>
            )}
            {stale && named.length > 0 && (
              <p className="px-1.5 pb-1 pt-0.5 text-[11px] text-amber-300">
                화면이 바뀌었을 수 있습니다 — [다시 찾기]
              </p>
            )}
          </div>
        )}

        {error && (
          <p className="pointer-events-auto rounded-md bg-red-600/85 px-2 py-1 text-[12px] text-white shadow-sm">
            {error}
          </p>
        )}
      </div>

      {/* 얼굴 상자 — 클릭을 막지 않도록 이름표만 눌린다 */}
      {open && faces.length > 0 && (
        <div
          className={`pointer-events-none absolute inset-0 z-10 transition-opacity ${stale ? 'opacity-40' : 'opacity-100'}`}
          data-testid="face-identify-boxes"
        >
          {faces.map((f, i) => (
            <FaceBox
              key={`${f.councilor_id || 'unknown'}-${i}`}
              face={f}
              onOpen={() => {
                if (f.councilor_id) {
                  setOpenId(f.councilor_id);
                  setOpenName(f.name);
                }
              }}
            />
          ))}
        </div>
      )}

      <CouncilorDetailModal
        councilorId={openId}
        fallbackName={openName}
        isOpen={openId !== null}
        onClose={() => setOpenId(null)}
      />
    </>
  );
}

function FaceBox({ face, onOpen }: { face: FaceMatchType; onOpen: () => void }) {
  const [x, y, w, h] = face.box;
  const known = face.confident && !!face.councilor_id;
  return (
    <div
      className="absolute"
      style={{ left: `${x * 100}%`, top: `${y * 100}%`, width: `${w * 100}%`, height: `${h * 100}%` }}
    >
      <div
        className={`h-full w-full rounded-sm border-2 ${
          known ? 'border-emerald-400' : 'border-white/35'
        }`}
      />
      {known && (
        <button
          type="button"
          onClick={onOpen}
          className="pointer-events-auto absolute left-1/2 top-full mt-1 -translate-x-1/2 whitespace-nowrap rounded bg-emerald-500 px-1.5 py-0.5 text-[11px] font-bold text-white shadow hover:bg-emerald-600"
        >
          {face.name}
          {face.basis === 'face+speaker' && <span className="ml-1 font-normal opacity-80">발언 중</span>}
        </button>
      )}
    </div>
  );
}
