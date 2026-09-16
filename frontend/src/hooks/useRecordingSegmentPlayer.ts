'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import type { RefObject } from 'react';

import { logAccess } from './useAccessLog';
import { API_BASE_URL } from '../lib/api';

import type { SubtitleType } from '../types';

/**
 * 자막 ▶ → 그 구간의 라이브 녹음 음성 재생 (생중계 화면 · VOD 등록 전 화면 공용).
 *
 * 녹음은 라이브 STT 가 받은 PCM 을 그대로 mp3(CBR)로 저장한 파일이라 자막 시각과
 * 파일 위치가 대응한다(백엔드 `live_recorder.py` · `GET /api/meetings/{id}/recording`).
 * CBR 이라 시간→바이트가 선형이므로 필요한 구간 바이트만 Range 로 받아 blob 으로 재생한다
 * (전체 파일 스트리밍·탐색이 필요 없어 진행 중 녹음에도 견고).
 *
 * 원래 생중계 화면(`app/live/page.tsx`)에만 있던 로직을 2026-09-15 담당자 요청
 * ("VOD 영상 등록 대기 화면에서 ▶ 누르면 녹음 음성이 나오게")으로 여기로 옮겼다.
 */

export interface RecordingMeta {
  bytes_per_sec?: number;
  size_bytes?: number;
  start_offset_sec?: number;
  sessions?: { clock?: number; byte?: number }[];
}

/**
 * 자막 시각(초) 구간 → 녹음 파일 바이트 구간. 녹음이 아직 그 구간까지 안 왔으면 null.
 *
 * ★자막 시각 → 파일 바이트 (2026-09-01 수정)
 *   녹음 mp3 는 STT 세션마다 이어붙는데, 서버가 재시작되면 오디오 시계는
 *   0 으로 되감기고 파일만 계속 자란다. 그래서 '시각 x 초당바이트' 로만
 *   계산하면 뒤쪽 세션의 자막이 앞쪽 세션(=맨 처음 녹음)으로 떨어진다.
 *   실제로 제393회 제1차 본회의에서 27분대 발언을 눌렀더니 개회 직후
 *   음성이 나왔다 — 그 파일 앞에 전날 세션이 붙어 있었기 때문이다.
 *   meta.sessions = [{clock, byte}, ...] 로 세션별 선형 매핑을 한다:
 *     파일 위치 = byte + (자막시각 - clock) x 초당바이트
 */
export function recordingByteRange(
  meta: RecordingMeta,
  startTime: number | null | undefined,
  endTime: number | null | undefined,
): { startByte: number; endByte: number } | null {
  const bps: number = Number(meta.bytes_per_sec) || 6000;
  const sizeBytes: number = Number(meta.size_bytes) || 0;
  const offset: number = Number(meta.start_offset_sec ?? 0);

  const sessions: { clock: number; byte: number }[] = Array.isArray(meta.sessions)
    ? [...meta.sessions]
        .map((x) => ({
          clock: Number(x.clock) || 0,
          byte: Number(x.byte) || 0,
        }))
        .sort((a, b) => a.byte - b.byte)
    : [];
  const clockToByte = (clock: number): number => {
    const last = sessions.at(-1);
    if (!last) return (clock - offset) * bps;
    // 뒤(최신) 세션부터 살펴 그 세션이 담고 있는 시간 범위에 드는 것을 고른다.
    // 같은 clock 이 여러 세션에 있을 수 있어(재시작마다 0으로 되감김) 최신 우선.
    for (let i = sessions.length - 1; i >= 0; i -= 1) {
      const cur = sessions[i];
      if (!cur) continue;
      const endByte = sessions[i + 1]?.byte ?? sizeBytes;
      const spanSec = Math.max(0, (endByte - cur.byte) / bps);
      if (clock >= cur.clock - 0.5 && clock <= cur.clock + spanSec + 0.5) {
        return cur.byte + (clock - cur.clock) * bps;
      }
    }
    return last.byte + (clock - last.clock) * bps;
  };

  const beginClock = Math.max(0, startTime ?? 0);
  const endClock = Math.max(beginClock + 0.5, endTime ?? beginClock + 5);
  // mp3 프레임 동기/문장 앞머리 여유로 앞뒤 약간 패딩
  const startByte = Math.max(0, Math.floor(clockToByte(beginClock)) - 2 * 1024);
  const endByte = Math.min(
    Math.max(sizeBytes - 1, 0),
    Math.ceil(clockToByte(endClock)) + 4 * 1024,
  );
  if (startByte >= sizeBytes) return null;
  return { startByte, endByte };
}

export interface UseRecordingSegmentPlayerOptions {
  /** 회의 UUID. 채널 ID 등 UUID 가 아니면 '지원하지 않음' 안내만 한다 */
  meetingId: string | null | undefined;
  /** 사용자에게 보일 짧은 안내 (녹음 없음·실패 등) */
  onNotice: (message: string) => void;
  /** 재생 동안 음소거했다가 끝나면 되돌릴 영상 (생중계 화면의 라이브 영상 덕킹) */
  duckRef?: RefObject<HTMLVideoElement | null>;
}

export interface UseRecordingSegmentPlayerReturn {
  /** 그 자막 구간을 재생한다. 재생 중인 자막을 다시 누르면 멈춘다 (토글) */
  playSegment: (subtitle: SubtitleType) => Promise<void>;
  /** 지금 음성이 나오고 있는 자막 ID — 칩을 '재생 중'으로 바꾸는 근거 */
  playingSegmentId: string | null;
}

export function useRecordingSegmentPlayer({
  meetingId,
  onNotice,
  duckRef,
}: UseRecordingSegmentPlayerOptions): UseRecordingSegmentPlayerReturn {
  const stopRef = useRef<(() => void) | null>(null);
  const [playingSegmentId, setPlayingSegmentId] = useState<string | null>(null);

  const playSegment = useCallback(async (s: SubtitleType) => {
    if (!meetingId || !/^[0-9a-f-]{36}$/i.test(meetingId)) {
      onNotice('이 방송은 음성 재생을 지원하지 않습니다');
      return;
    }
    // 재생 중인 칩을 다시 누르면 멈춘다 (토글)
    if (playingSegmentId === s.id) {
      stopRef.current?.();
      return;
    }
    logAccess('record', { meetingId });  // 접속 통계(2026-09-16)
    const base = `${API_BASE_URL}/api/meetings/${meetingId}/recording`;
    try {
      stopRef.current?.(); // 이전 재생 중지(+영상 음량 복원)

      const metaRes = await fetch(`${base}/meta?ts=${Date.now()}`);
      if (!metaRes.ok) {
        onNotice('이 구간의 녹음이 아직 없습니다');
        return;
      }
      const meta: RecordingMeta = await metaRes.json();
      const range = recordingByteRange(meta, s.start_time, s.end_time);
      if (!range) {
        onNotice('이 구간의 녹음이 아직 기록되지 않았습니다 (잠시 후 다시 시도)');
        return;
      }

      const res = await fetch(base, {
        headers: { Range: `bytes=${range.startByte}-${range.endByte}` },
      });
      if (!res.ok && res.status !== 206) {
        onNotice('음성 구간을 가져오지 못했습니다');
        return;
      }
      const objUrl = URL.createObjectURL(await res.blob());
      const audio = new Audio(objUrl);

      // 영상 덕킹: 구간 재생 동안 음소거 → 종료 시 복원
      const video = duckRef?.current ?? null;
      const prevMuted = video?.muted;
      const cleanup = () => {
        audio.pause();
        URL.revokeObjectURL(objUrl);
        if (video && prevMuted !== undefined) video.muted = prevMuted;
        if (stopRef.current === cleanup) stopRef.current = null;
        setPlayingSegmentId((cur) => (cur === s.id ? null : cur));
      };
      stopRef.current = cleanup;
      audio.addEventListener('ended', cleanup, { once: true });
      audio.addEventListener('error', cleanup, { once: true });
      if (video) video.muted = true;

      setPlayingSegmentId(s.id);
      await audio.play();
    } catch {
      stopRef.current?.();
      setPlayingSegmentId(null);
      onNotice('음성 재생에 실패했습니다');
    }
  }, [meetingId, onNotice, duckRef, playingSegmentId]);

  // 회의(채널) 변경/언마운트 시 구간 재생 정리(+영상 음량 복원)
  useEffect(() => {
    return () => {
      stopRef.current?.();
    };
  }, [meetingId]);

  return { playSegment, playingSegmentId };
}

export default useRecordingSegmentPlayer;
