'use client';

import { useCallback, useEffect, useRef } from 'react';

import useSWR from 'swr';

import { apiClient, API_BASE_URL } from '@/lib/api';
import type { ChannelType } from '@/types';

async function fetcher(endpoint: string): Promise<ChannelType[]> {
  return apiClient<ChannelType[]>(endpoint);
}

export interface StatusChange {
  code: string;
  old_status: number | null;
  new_status: number | null;
  old_text: string | null;
  new_text: string | null;
}

export interface UseChannelStatusOptions {
  /** SWR 폴링 간격 (ms). 기본값 5000 */
  pollingInterval?: number;
  /**
   * 모든 채널의 방송 시작 알림 활성화 여부. 기본값 false.
   * 특정 채널만 알림 받고 싶다면 `useChannelAlerts` 훅을 사용할 것.
   * (useChannelAlerts가 이 훅의 channels 배열을 관찰하므로 중복 알림을 피함)
   */
  enableNotifications?: boolean;
  /** 상태 변경 콜백 */
  onStatusChange?: (changes: StatusChange[]) => void;
}

export interface UseChannelStatusResult {
  channels: ChannelType[];
  isLoading: boolean;
  error: Error | null;
  /** 알림 권한 요청 */
  requestNotificationPermission: () => Promise<NotificationPermission | null>;
}

/**
 * 채널 방송 상태를 실시간으로 추적하는 훅.
 *
 * - SWR 폴링 (5초)으로 기본 업데이트
 * - SSE 연결로 실시간 변경 수신
 * - 방송 시작 시 브라우저 알림 발송
 */
export function useChannelStatus(
  options: UseChannelStatusOptions = {}
): UseChannelStatusResult {
  const {
    // 30초 — 즉시 반영은 SSE가 담당하므로 폴링은 안전망.
    // (기존 5초 폴링은 시청자 수십 명 규모에서 터널의 TCP 연결 한도(분당 150)를
    //  압박해 2026-07-21 장애의 원인이 됐다)
    pollingInterval = 30000,
    enableNotifications = false, // 구독 기반 알림은 useChannelAlerts에서 처리
    onStatusChange,
  } = options;

  const { data, error, isLoading, mutate } = useSWR<ChannelType[]>(
    '/api/channels/status',
    fetcher,
    { refreshInterval: pollingInterval }
  );

  const onStatusChangeRef = useRef(onStatusChange);
  onStatusChangeRef.current = onStatusChange;

  const prevChannelsRef = useRef<Map<string, number>>(new Map());

  // 채널 이름 조회 헬퍼
  const getChannelName = useCallback(
    (code: string): string => {
      const ch = data?.find((c) => c.code === code);
      return ch?.name ?? code;
    },
    [data]
  );

  // 브라우저 알림 발송
  const sendNotification = useCallback(
    (changes: StatusChange[]) => {
      if (!enableNotifications) return;
      if (typeof window === 'undefined' || !('Notification' in window)) return;
      if (Notification.permission !== 'granted') return;

      for (const change of changes) {
        // 방송 시작 (0→1) 알림만 발송
        if (change.new_status === 1 && change.old_status !== 1) {
          const channelName = getChannelName(change.code);
          const notification = new Notification(`${channelName} 방송 시작`, {
            body: `경기도의회 ${channelName} 생중계가 시작되었습니다.`,
            icon: '/favicon.ico',
            tag: `live-${change.code}`,
          });
          notification.onclick = () => {
            window.focus();
            notification.close();
          };
        }
      }
    },
    [enableNotifications, getChannelName]
  );

  // SSE 연결 — fetch 스트리밍 구현.
  // ★EventSource를 쓰지 않는 이유: 커스텀 헤더를 붙일 수 없어 ngrok 무료
  //   터널의 브라우저 경고 페이지(ERR_NGROK_6024, CORS 헤더 없음)에 가로채여
  //   콘솔에 CORS 에러가 반복 출력됐다. fetch는 우회 헤더를 붙일 수 있다.
  useEffect(() => {
    if (typeof window === 'undefined') return;

    let stopped = false;
    let controller: AbortController | null = null;

    const handleEvent = (eventName: string, data: string) => {
      if (eventName !== 'status_change' || !data) return;
      try {
        const payload = JSON.parse(data);
        const channels: ChannelType[] = payload.channels;
        const changes: StatusChange[] = payload.changes;
        mutate(channels, false); // SWR 캐시 업데이트
        onStatusChangeRef.current?.(changes);
        sendNotification(changes); // 브라우저 알림
      } catch {
        // JSON 파싱 실패 무시
      }
    };

    const run = async () => {
      // ★고정 5초 재시도는 시청자 수십 명이 동시에 몰리면 ngrok 연결 한도(분당 150)를
      //   초과시켜 터널 복구 자체를 막는다(2026-07-21 장애) — 지수 백오프 + 지터로 분산.
      let failStreak = 0;
      while (!stopped) {
        const startedAt = Date.now();
        try {
          controller = new AbortController();
          const res = await fetch(`${API_BASE_URL}/api/channels/status/stream`, {
            headers: {
              Accept: 'text/event-stream',
              'ngrok-skip-browser-warning': '1',
            },
            signal: controller.signal,
          });
          if (!res.ok || !res.body) throw new Error(`SSE HTTP ${res.status}`);

          const reader = res.body.getReader();
          const decoder = new TextDecoder();
          let buf = '';
          for (;;) {
            const { done, value } = await reader.read();
            if (done || stopped) break;
            buf += decoder.decode(value, { stream: true });
            let sep;
            while ((sep = buf.indexOf('\n\n')) !== -1) {
              const rawEvent = buf.slice(0, sep);
              buf = buf.slice(sep + 2);
              let eventName = 'message';
              let data = '';
              for (const line of rawEvent.split('\n')) {
                if (line.startsWith('event:')) eventName = line.slice(6).trim();
                else if (line.startsWith('data:')) data += line.slice(5).trim();
              }
              handleEvent(eventName, data);
            }
          }
        } catch {
          // 네트워크 오류/서버 재시작 — 백오프 후 재연결
        }
        if (stopped) break;
        // 30초 이상 유지되다 끊긴 스트림은 정상 순환 → 백오프 리셋
        if (Date.now() - startedAt > 30000) {
          failStreak = 0;
        } else {
          failStreak = Math.min(failStreak + 1, 5);
        }
        // 5s → 10s → 20s → 40s → 80s → 160s, 지터 0.5~1.5배
        const delay = Math.min(5000 * 2 ** failStreak, 160000) * (0.5 + Math.random());
        await new Promise((r) => setTimeout(r, delay));
      }
    };

    void run();

    return () => {
      stopped = true;
      controller?.abort();
    };
  }, [mutate, sendNotification]);

  // SWR 데이터 변경 시 로컬 상태 변경 감지 (SSE 없이 폴링만으로도 작동)
  useEffect(() => {
    if (!data) return;

    const changes: StatusChange[] = [];
    const newMap = new Map<string, number>();

    for (const ch of data) {
      const status = ch.livestatus ?? 0;
      newMap.set(ch.code, status);

      const prev = prevChannelsRef.current.get(ch.code);
      if (prev !== undefined && prev !== status) {
        changes.push({
          code: ch.code,
          old_status: prev,
          new_status: status,
          old_text: null,
          new_text: ch.status_text ?? null,
        });
      }
    }

    prevChannelsRef.current = newMap;

    if (changes.length > 0) {
      onStatusChangeRef.current?.(changes);
      sendNotification(changes);
    }
  }, [data, sendNotification]);

  // 알림 권한 요청
  const requestNotificationPermission =
    useCallback(async (): Promise<NotificationPermission | null> => {
      if (typeof window === 'undefined' || !('Notification' in window)) {
        return null;
      }
      return Notification.requestPermission();
    }, []);

  return {
    channels: data ?? [],
    isLoading,
    error: error ?? null,
    requestNotificationPermission,
  };
}

export default useChannelStatus;
