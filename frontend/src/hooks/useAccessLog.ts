'use client';

import { useEffect, useRef } from 'react';

import { recordAccess } from '@/lib/api';
import type { AccessEventKind } from '@/types';

/**
 * 접속 기록 보내기 (2026-09-16 담당자 요청 — 접속 통계 화면 `/visits`)
 *
 * 무엇을 보내나: 어떤 화면을 열었는지 · 회의를 보는 동안 5분마다 한 번.
 * 무엇을 안 보내나: **IP·이름·계정은 브라우저가 보내지 않고 서버도 저장하지 않는다.**
 * `visitor_key` 는 **그날 하루만 사는 난수**라 날짜를 넘겨 같은 사람인지 알 수 없다
 * (기존 방문 카운터의 `ggc_visit_YYYY-MM-DD` 와 같은 결).
 *
 * 실패는 조용히 삼킨다 — 통계 때문에 회의 화면이 멈추면 안 된다.
 */

const KEY_PREFIX = 'ggc_visit_key_';

/** 5분. 서버는 이 신호 1건을 300초 시청으로 센다(access_stats_service.WATCH_TICK_SECONDS). */
export const WATCH_PING_MS = 5 * 60 * 1000;

function todaySuffix(): string {
  const d = new Date();
  return `${d.getFullYear()}-${`${d.getMonth() + 1}`.padStart(2, '0')}-${`${d.getDate()}`.padStart(2, '0')}`;
}

function randomKey(): string {
  try {
    if (typeof crypto !== 'undefined' && crypto.randomUUID) return crypto.randomUUID();
  } catch {
    // 구형 브라우저 — 아래 폴백
  }
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

/** 그날짜 전용 난수. localStorage 를 못 쓰면 매번 새 값이라 방문자 수가 조금 커질 뿐 기능은 산다. */
export function visitorKey(): string {
  const key = `${KEY_PREFIX}${todaySuffix()}`;
  try {
    if (typeof window === 'undefined') return '';
    // 어제 것은 치운다 — 브라우저에 흔적을 오래 남기지 않는다
    const stale: string[] = [];
    for (let i = 0; i < window.localStorage.length; i += 1) {
      const k = window.localStorage.key(i);
      if (k && k.startsWith(KEY_PREFIX) && k !== key) stale.push(k);
    }
    stale.forEach((k) => window.localStorage.removeItem(k));

    const saved = window.localStorage.getItem(key);
    if (saved) return saved;
    const made = randomKey();
    window.localStorage.setItem(key, made);
    return made;
  } catch {
    return randomKey();
  }
}

/** 한 번만 기록(검색·AI 질문·영상 받기·녹음 듣기 같은 행동). */
export function logAccess(
  kind: AccessEventKind,
  options: { meetingId?: string | null; path?: string } = {}
): void {
  try {
    void recordAccess({
      kind,
      meetingId: options.meetingId ?? null,
      path: options.path ?? (typeof window !== 'undefined' ? window.location.pathname : undefined),
      visitorKey: visitorKey(),
    });
  } catch {
    // 통계는 부가 기능 — 무슨 일이 있어도 회의 화면을 막지 않는다
  }
}

/** 화면을 열었다는 기록 — 마운트 시 1회(서버가 30초 안 중복은 버린다). */
export function usePageAccessLog(path?: string, meetingId?: string | null): void {
  const sent = useRef(false);
  useEffect(() => {
    if (sent.current) return;
    sent.current = true;
    logAccess('page', { path, meetingId });
  }, [path, meetingId]);
}

/**
 * 회의를 보는 동안 5분마다 기록 — **재생 중이고 탭이 보일 때만** 보낸다.
 * (틀어 놓고 잊은 탭까지 세면 시청 시간이 부풀려진다)
 */
export function useWatchAccessLog(options: {
  kind: 'watch_live' | 'watch_vod';
  meetingId?: string | null;
  active: boolean;
}): void {
  const { kind, meetingId, active } = options;

  useEffect(() => {
    if (!active) return undefined;

    const ping = () => {
      if (typeof document !== 'undefined' && document.visibilityState === 'hidden') return;
      logAccess(kind, { meetingId });
    };

    ping();
    const timer = window.setInterval(ping, WATCH_PING_MS);
    return () => window.clearInterval(timer);
  }, [kind, meetingId, active]);
}
