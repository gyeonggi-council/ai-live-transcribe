'use client';

import { useCallback, useEffect, useRef } from 'react';

/**
 * 클립 워크벤치 키보드 — 데스크톱 추출기 webui/app.html L1155~1188 이식
 *
 * ★document 의 **캡처 단계**(capture: true)에서 가로채 preventDefault+stopPropagation 한다.
 *   이렇게 하지 않으면 사용자가 네이티브 <video controls> 를 클릭한 뒤 화살표가 섀도 DOM
 *   슬라이더의 %단위 스텝(영상 길이 비례 — 3시간 회의면 ~1분)으로 동작해 이동량이 널뛴다.
 *   e.repeat 는 180ms 스로틀로 길게 눌러도 일정 속도.
 *
 * 단축키(버튼 라벨과 동일): ←/→ 5초 · ↑/↓ 1초 · PgUp/PgDn 1분 · ,/. 프레임 · Space 재생 ·
 * [ 또는 i 시작 지정 · ] 또는 o 종료 지정 · Home/End 처음/끝 · Esc 입력창 벗어나기
 */
export const SEEK_KEYS: Record<string, number> = {
  ArrowLeft: -5,
  ArrowRight: 5,
  ArrowUp: -1,
  ArrowDown: 1,
  PageUp: -60,
  PageDown: 60,
};

export const DEFAULT_FPS = 29.97;
const REPEAT_THROTTLE_MS = 180;

export interface UseClipKeyboardOptions {
  videoRef: React.MutableRefObject<HTMLVideoElement | null>;
  /** 영상이 열려 있을 때만 잡는다 */
  enabled: boolean;
  /** 시크 상한(초). 없으면 video.duration */
  duration?: number | null;
  onMarkStart: () => void;
  onMarkEnd: () => void;
  fps?: number;
}

export interface ClipKeyboardControls {
  seekRel: (sec: number) => void;
  seekTo: (sec: number) => void;
  frameStep: (n: 1 | -1) => void;
  togglePlay: () => void;
}

export function useClipKeyboard(o: UseClipKeyboardOptions): ClipKeyboardControls {
  const { videoRef, enabled, duration, fps = DEFAULT_FPS } = o;
  // 콜백은 ref 로 — 부모가 매 렌더 새 함수를 줘도 리스너를 다시 달지 않는다
  const markStartRef = useRef(o.onMarkStart);
  const markEndRef = useRef(o.onMarkEnd);
  markStartRef.current = o.onMarkStart;
  markEndRef.current = o.onMarkEnd;
  const durationRef = useRef(duration);
  durationRef.current = duration;

  const maxTime = useCallback((v: HTMLVideoElement) => {
    const d = durationRef.current;
    if (d && d > 0) return d;
    return Number.isFinite(v.duration) && v.duration > 0 ? v.duration : 1e9;
  }, []);

  const seekTo = useCallback(
    (sec: number) => {
      const v = videoRef.current;
      if (!v) return;
      v.currentTime = Math.min(maxTime(v), Math.max(0, sec));
    },
    [videoRef, maxTime]
  );

  const seekRel = useCallback(
    (sec: number) => {
      const v = videoRef.current;
      if (!v) return;
      seekTo(v.currentTime + sec);
    },
    [videoRef, seekTo]
  );

  const frameStep = useCallback(
    (n: 1 | -1) => {
      const v = videoRef.current;
      if (!v) return;
      v.pause();
      seekTo(v.currentTime + n / fps);
    },
    [videoRef, seekTo, fps]
  );

  const togglePlay = useCallback(() => {
    const v = videoRef.current;
    if (!v) return;
    if (v.paused) {
      void v.play()?.catch?.(() => {});
    } else {
      v.pause();
    }
  }, [videoRef]);

  useEffect(() => {
    if (!enabled) return undefined;
    let lastSeek = 0;
    const handler = (e: KeyboardEvent) => {
      const v = videoRef.current;
      if (!v) return;
      const el = document.activeElement as HTMLElement | null;
      if (el && ['INPUT', 'SELECT', 'TEXTAREA'].includes(el.tagName)) {
        if (e.key === 'Escape') el.blur();
        return;
      }
      const step = SEEK_KEYS[e.key];
      if (step !== undefined) {
        e.preventDefault();
        e.stopPropagation();
        const now = typeof performance !== 'undefined' ? performance.now() : Date.now();
        if (e.repeat && now - lastSeek < REPEAT_THROTTLE_MS) return;
        lastSeek = now;
        seekRel(step);
        return;
      }
      let handled = true;
      switch (e.key) {
        case ' ':
          togglePlay();
          break;
        case ',':
          frameStep(-1);
          break;
        case '.':
          frameStep(1);
          break;
        case '[':
        case 'i':
        case 'I':
          markStartRef.current();
          break;
        case ']':
        case 'o':
        case 'O':
          markEndRef.current();
          break;
        case 'Home':
          seekTo(0);
          break;
        case 'End':
          seekTo(Math.max(0, maxTime(v) - 0.5));
          break;
        default:
          handled = false;
      }
      if (handled) {
        e.preventDefault();
        e.stopPropagation();
      }
    };
    document.addEventListener('keydown', handler, true);
    return () => document.removeEventListener('keydown', handler, true);
  }, [enabled, videoRef, seekRel, seekTo, frameStep, togglePlay, maxTime]);

  return { seekRel, seekTo, frameStep, togglePlay };
}
