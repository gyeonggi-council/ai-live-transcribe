'use client';

/**
 * useChannelAlerts — 채널별 방송 시작 알람 구독 관리
 *
 * 시민이 특정 위원회 방송을 미리 "알람 등록"해 두면,
 * 해당 채널의 상태가 방송전(0/4)→방송중(1)으로 전환되는 순간
 * 브라우저 Notification API로 토스트 알림을 띄운다.
 *
 * 특징:
 * - 구독 상태는 localStorage에 영속 (`channel_alerts` key)
 * - 다른 탭에서 구독 변경 시 storage 이벤트로 동기화
 * - Notification 권한이 없으면 subscribe 시점에 자동 요청
 * - 상태 변경 감지는 `useChannelStatus` 의 channels 배열을 외부에서 주입받아 수행
 *   (이미 SSE/폴링으로 실시간 업데이트되고 있으므로 중복 구독 방지)
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import type { ChannelType } from '@/types';

const STORAGE_KEY = 'channel_alerts';

function readStored(): Set<string> {
  if (typeof window === 'undefined') return new Set();
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return new Set();
    const arr = JSON.parse(raw);
    return Array.isArray(arr) ? new Set(arr.filter((x) => typeof x === 'string')) : new Set();
  } catch {
    return new Set();
  }
}

function writeStored(value: Set<string>): void {
  if (typeof window === 'undefined') return;
  localStorage.setItem(STORAGE_KEY, JSON.stringify(Array.from(value)));
}

export interface UseChannelAlertsOptions {
  /** 실시간 채널 상태 (useChannelStatus 로부터 주입) */
  channels: ChannelType[];
}

export interface UseChannelAlertsResult {
  /** 현재 구독 중인 채널 ID 집합 */
  subscribed: Set<string>;
  /** 특정 채널 구독 여부 */
  isSubscribed: (channelId: string) => boolean;
  /** 구독 추가. Notification 권한이 없으면 자동 요청. */
  subscribe: (channelId: string) => Promise<void>;
  /** 구독 해제 */
  unsubscribe: (channelId: string) => void;
  /** 전체 구독 초기화 */
  clearAll: () => void;
  /** 현재 Notification 권한 상태 */
  permission: NotificationPermission | 'unsupported';
}

export function useChannelAlerts({ channels }: UseChannelAlertsOptions): UseChannelAlertsResult {
  const [subscribed, setSubscribed] = useState<Set<string>>(() => readStored());
  const [permission, setPermission] = useState<NotificationPermission | 'unsupported'>(() => {
    if (typeof window === 'undefined' || !('Notification' in window)) return 'unsupported';
    return Notification.permission;
  });

  // 이전 스냅샷으로 방송전→방송중 전환 감지
  const prevStatusRef = useRef<Map<string, number>>(new Map());

  // 다른 탭에서 구독 변경 시 동기화
  useEffect(() => {
    if (typeof window === 'undefined') return;
    const onStorage = (e: StorageEvent) => {
      if (e.key === STORAGE_KEY) setSubscribed(readStored());
    };
    window.addEventListener('storage', onStorage);
    return () => window.removeEventListener('storage', onStorage);
  }, []);

  // 채널 상태 변경 감지 → 구독된 채널이 방송중으로 전환되면 알림
  useEffect(() => {
    if (channels.length === 0) return;
    if (typeof window === 'undefined' || !('Notification' in window)) return;

    const newMap = new Map<string, number>();
    for (const ch of channels) {
      const status = ch.livestatus ?? 0;
      newMap.set(ch.id, status);

      const prev = prevStatusRef.current.get(ch.id);
      const transitionedToLive = prev !== undefined && prev !== 1 && status === 1;

      if (transitionedToLive && subscribed.has(ch.id) && Notification.permission === 'granted') {
        const n = new Notification(`${ch.name} 방송 시작`, {
          body: '알람 등록하신 경기도의회 방송이 시작되었습니다. 클릭하여 시청하세요.',
          icon: '/favicon.ico',
          tag: `live-${ch.id}`,
          requireInteraction: false,
        });
        n.onclick = () => {
          // 클릭 시 해당 채널의 실시간 뷰어로 이동
          window.focus();
          window.location.href = `/live?channel=${encodeURIComponent(ch.id)}`;
          n.close();
        };
      }
    }

    prevStatusRef.current = newMap;
  }, [channels, subscribed]);

  const isSubscribed = useCallback((channelId: string) => subscribed.has(channelId), [subscribed]);

  const subscribe = useCallback(async (channelId: string) => {
    // Notification 권한 요청 (거부 상태는 user gesture로만 복구 가능)
    if (typeof window !== 'undefined' && 'Notification' in window) {
      if (Notification.permission === 'default') {
        const result = await Notification.requestPermission();
        setPermission(result);
        if (result === 'denied') {
          // 권한 거부돼도 구독은 허용 — 브라우저 설정에서 다시 켤 수 있음
        }
      } else {
        setPermission(Notification.permission);
      }
    }

    setSubscribed((prev) => {
      if (prev.has(channelId)) return prev;
      const next = new Set(prev);
      next.add(channelId);
      writeStored(next);
      return next;
    });
  }, []);

  const unsubscribe = useCallback((channelId: string) => {
    setSubscribed((prev) => {
      if (!prev.has(channelId)) return prev;
      const next = new Set(prev);
      next.delete(channelId);
      writeStored(next);
      return next;
    });
  }, []);

  const clearAll = useCallback(() => {
    setSubscribed(new Set());
    writeStored(new Set());
  }, []);

  return { subscribed, isSubscribed, subscribe, unsubscribe, clearAll, permission };
}

export default useChannelAlerts;
