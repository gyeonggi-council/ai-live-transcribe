/**
 * useSubtitleWebSocket 훅
 *
 * WebSocket을 통해 실시간 자막을 수신하는 훅입니다.
 *
 * 특징:
 * - WebSocket 연결 관리 (/ws/meetings/{id}/subtitles)
 * - subtitle_created 이벤트 처리
 * - subtitle_corrected 교정 결과 적용 (race condition 방지 버퍼링)
 * - subtitle_correction_failed 실패 처리
 * - 자동 재연결 (exponential backoff)
 * - 연결 상태 관리
 * - 자막 배열 상태 관리
 */

'use client';

import { useState, useEffect, useRef, useCallback } from 'react';

import type { MaterialRequestType, SubtitleType } from '@/types';

/**
 * 연결 상태 타입
 */
export type ConnectionStatus = 'connecting' | 'connected' | 'disconnected' | 'error';

/**
 * 훅 옵션 인터페이스
 */
export interface UseSubtitleWebSocketOptions {
  /** 회의 ID */
  meetingId: string;
  /** 자막 수신 시 호출되는 콜백 */
  onSubtitle?: (subtitle: SubtitleType) => void;
  /** 요구자료 감지 이벤트 수신 콜백 (모니터링 직원 알림용) */
  onMaterialRequest?: (request: MaterialRequestType) => void;
  /** 자동 연결 여부 (기본값: true) */
  autoConnect?: boolean;
  /** 실시간 자막 표시 지연(ms) - 영상과 싱크 맞추기용 (기본값: 0) */
  displayDelay?: number;
}

/**
 * 훅 반환 인터페이스
 */
/** 서버가 방송하는 자막 생성 상태 (모든 시청자 동일 — 단일 진실) */
export interface SttStatusType {
  /** generating=생성 중, listening=발언 대기(무음), idle=정회/종료 */
  state: 'generating' | 'listening' | 'idle';
  /** 마지막 자막 방출 후 경과(초, 서버 기준). 방출 이력 없으면 null */
  seconds_since_subtitle: number | null;
  /** 최근 자막 간격 평균(초, 서버 실측). 표본 부족 시 null */
  avg_interval: number | null;
  /**
   * 영상-자막 정밀 동기화 앵커: 서버가 지금까지 디코딩한 누적 오디오 초.
   * 자막 start_time과 같은 시계. 구버전 서버는 미포함(undefined).
   */
  audio_clock?: number | null;
  /** 현재 이 채널을 보고 있는 시청자 수 (자막 WS 룸 연결 수) */
  viewers?: number | null;
  /** 마지막 전사 창의 API 왕복(초) — 계측용 (2026-09-03) */
  api_sec_last?: number | null;
  /** 마지막 전사 창의 준비 지연(초) = 방출 시점 오디오 시계 − 창 시작 */
  ready_lag_last?: number | null;
  /** 최근 100창의 준비 지연 p95(초) — 영상 지연 목표의 근거 */
  ready_lag_p95?: number | null;
  /** 원본 재생목록 깊이(초) — 영상 지연 목표가 이보다 깊으면 접속 직후 톱업 정지 */
  hls_window_sec?: number | null;
  /** 수집 지연(디코더 ↔ 우리 재생목록 엣지, 초) — 마지막 창 · 최근 100창 p95 (2026-09-14) */
  edge_lag_last?: number | null;
  edge_lag_p95?: number | null;
  /** sync_need = ready_lag + edge_lag — 영상 지연 목표 = ceil(p99 + 1) 의 근거 (최근 100창 p95 · 최댓값 · 표본 수) */
  sync_need_p95?: number | null;
  sync_need_max?: number | null;
  samples?: number | null;
  /** 서버가 적용 중인 영상 지연 목표(초, api env LIVE_SYNC_TARGET_SEC) — 채널 상태 응답에도 같은 값 */
  sync_target_sec?: number | null;
  /** 배치 창 길이(초) — 상태 게이지의 평균/최대 기준 */
  window_seconds?: number | null;
  /** 이 상태를 수신한 클라이언트 시각 (보간용 — 수신 순간 스탬프, 표시 지연과 무관) */
  receivedAt: number;
}

export interface UseSubtitleWebSocketReturn {
  /** 수신된 자막 배열 */
  subtitles: SubtitleType[];
  /** 연결 상태 */
  connectionStatus: ConnectionStatus;
  /** 수동 연결 함수 */
  connect: () => void;
  /** 수동 해제 함수 */
  disconnect: () => void;
  /** 자막 배열 초기화 함수 */
  clearSubtitles: () => void;
  /** STT interim (preview) 텍스트 - 확정 전 미리보기 */
  interimText: string;
  /** 마지막 자막/interim 수신 시각 (timestamp ms), 수신 없으면 null */
  lastActivityTime: number | null;
  /** 서버 기준 자막 생성 상태 (2초 주기 방송). 미수신 시 null */
  sttStatus: SttStatusType | null;
}

/**
 * WebSocket 메시지 타입
 */
interface SubtitleCreatedEvent {
  type: 'subtitle_created';
  payload: {
    subtitle: SubtitleType;
  };
}

interface SubtitleHistoryEvent {
  type: 'subtitle_history';
  payload: {
    subtitles: SubtitleType[];
  };
}

interface SubtitleCorrectedEvent {
  type: 'subtitle_corrected';
  payload: {
    id: string;
    // 텍스트 교정값. 화자 구분(diarize) 경로는 텍스트를 바꾸지 않고 speaker만 보내므로 선택적.
    corrected_text?: string;
    meeting_id?: string;
    // 화자 구분(diarize)이 부여한 화자 라벨 (예: "화자 1"). 텍스트 교정과 함께 또는 단독으로 도착.
    speaker?: string | null;
    // 교정 출처 식별 ("diarize" 등) — 디버깅/표시용.
    source?: string;
  };
}

interface SubtitleCorrectionFailedEvent {
  type: 'subtitle_correction_failed';
  payload: {
    subtitle_id: string;
    reason: string;
  };
}

interface WebSocketMessage {
  type: string;
  payload: unknown;
}

/**
 * 재연결 설정
 */
const RECONNECT_CONFIG = {
  initialDelay: 1000, // 1초
  // 60초 — 터널(ngrok Hobby)의 TCP 연결 한도(분당 150) 보호.
  // 순단 시 시청자 수십 명이 동시 재접속하면 한도를 넘겨 복구 자체가 막힌다.
  maxDelay: 60000,
  backoffMultiplier: 2,
};

/** 교정 버퍼 자동 정리 시간 (ms) */
const CORRECTION_BUFFER_CLEANUP_MS = 30000;

/**
 * '교정 중'(pending) 안전 타임아웃 (ms)
 * 교정 이벤트가 끝내 도착하지 않으면(교정기 비활성/이벤트 유실) pending을 해제해
 * '교정 중' 배지가 영원히 남지 않도록 한다.
 */
const PENDING_CORRECTION_TIMEOUT_MS = 45000;

/**
 * WebSocket URL 생성
 * meeting UUID와 channel ID 모두 동일 경로 사용
 */
function getWebSocketUrl(meetingId: string): string {
  // env 미지정 시 접속한 주소를 따라간다(same-origin) — IP 접속과 도메인(aisub.ggc.go.kr)
  // 접속이 각자의 인증서로 자연히 동작한다. k3s 에선 Ingress 가 /transcribe/ws 를 라우팅.
  const wsBaseUrl =
    process.env.NEXT_PUBLIC_WS_URL ||
    (typeof window !== 'undefined'
      ? `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}${process.env.NEXT_PUBLIC_BASE_PATH || ''}`
      : 'ws://localhost:8000');
  return `${wsBaseUrl}/ws/meetings/${meetingId}/subtitles`;
}

/**
 * 실시간 자막 WebSocket 훅
 *
 * @param options - 훅 옵션
 * @returns WebSocket 연결 상태 및 제어 함수
 *
 * @example
 * ```tsx
 * const { subtitles, connectionStatus, connect, disconnect, clearSubtitles } =
 *   useSubtitleWebSocket({
 *     meetingId: 'meeting-1',
 *     onSubtitle: (subtitle) => console.log('New subtitle:', subtitle),
 *   });
 *
 * if (connectionStatus === 'connected') {
 *   return <SubtitlePanel subtitles={subtitles} />;
 * }
 * ```
 */
export function useSubtitleWebSocket(
  options: UseSubtitleWebSocketOptions
): UseSubtitleWebSocketReturn {
  const { meetingId, onSubtitle, onMaterialRequest, autoConnect = true, displayDelay = 0 } = options;

  // State
  const [subtitles, setSubtitles] = useState<SubtitleType[]>([]);
  const [interimText, setInterimText] = useState<string>('');
  const [lastActivityTime, setLastActivityTime] = useState<number | null>(null);
  const [sttStatus, setSttStatus] = useState<SttStatusType | null>(null);
  const [connectionStatus, setConnectionStatus] = useState<ConnectionStatus>(
    autoConnect ? 'connecting' : 'disconnected'
  );

  // Refs for WebSocket and reconnection logic
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectAttemptRef = useRef(0);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const isManualDisconnectRef = useRef(false);
  const isMountedRef = useRef(true);
  const onSubtitleRef = useRef(onSubtitle);
  const delayTimersRef = useRef<NodeJS.Timeout[]>([]);
  // displayDelay는 ref로 읽는다 — 값이 바뀌어도 WS를 재연결하지 않고
  // 다음 메시지부터 새 지연이 적용된다 (라이브 정밀 동기화 모드 토글용).
  const displayDelayRef = useRef(displayDelay);
  useEffect(() => {
    displayDelayRef.current = displayDelay;
  }, [displayDelay]);

  // BUG #3: Pending corrections buffer - corrections that arrive before their subtitle
  const pendingCorrectionsRef = useRef<Map<string, { corrected_text?: string; speaker?: string | null; timer: NodeJS.Timeout }>>(new Map());

  // Update onSubtitle ref when it changes
  useEffect(() => {
    onSubtitleRef.current = onSubtitle;
  }, [onSubtitle]);

  // 요구자료 콜백도 ref 경유 — 콜백 변경으로 WS 재연결되지 않도록
  const onMaterialRequestRef = useRef(onMaterialRequest);
  useEffect(() => {
    onMaterialRequestRef.current = onMaterialRequest;
  }, [onMaterialRequest]);

  /**
   * 재연결 지연 시간 계산 (exponential backoff)
   */
  const getReconnectDelay = useCallback(() => {
    const delay = Math.min(
      RECONNECT_CONFIG.initialDelay *
        Math.pow(RECONNECT_CONFIG.backoffMultiplier, reconnectAttemptRef.current),
      RECONNECT_CONFIG.maxDelay
    );
    // 지터(0.5~1.5배): 터널 순단 시 모든 시청자가 같은 스케줄로 재접속하면
    // 동시 접속 파도가 반복된다 — 무작위 분산으로 파도를 흩뜨린다 (2026-07-21 장애 재발 방지)
    return delay * (0.5 + Math.random());
  }, []);

  /**
   * 재연결 타이머 정리
   */
  const clearReconnectTimeout = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }
  }, []);

  /**
   * WebSocket 연결 생성
   */
  const createConnection = useCallback(() => {
    if (!isMountedRef.current) return;

    // 기존 연결 정리 (wsRef를 먼저 null로 설정하여 close 이벤트에서 재연결 방지)
    if (wsRef.current) {
      const oldWs = wsRef.current;
      wsRef.current = null;
      oldWs.close();
    }

    clearReconnectTimeout();

    const url = getWebSocketUrl(meetingId);
    const ws = new WebSocket(url);
    wsRef.current = ws;
    setConnectionStatus('connecting');

    ws.onopen = () => {
      if (!isMountedRef.current) return;
      setConnectionStatus('connected');
      reconnectAttemptRef.current = 0; // 연결 성공 시 재연결 시도 횟수 초기화
    };

    ws.onmessage = (event: MessageEvent) => {
      if (!isMountedRef.current) return;

      try {
        const message: WebSocketMessage = JSON.parse(event.data);

        if (message.type === 'subtitle_history') {
          // 접속 시 서버에서 보내주는 이전 자막 히스토리 (일괄 수신, 지연 없음)
          const historyEvent = message as SubtitleHistoryEvent;
          const historySubtitles = historyEvent.payload.subtitles;
          setSubtitles(historySubtitles);
        } else if (message.type === 'stt_status') {
          // 서버 기준 자막 생성 상태 (2초 주기) — 모든 시청자가 동일하게 본다.
          // ★자막과 같은 displayDelay를 적용해 타임라인을 일치시킨다 —
          //   안 그러면 게이지가 자막 표시보다 displayDelay만큼 먼저 리셋되어
          //   "게이지는 돌아왔는데 자막이 안 나온다"로 보인다.
          const s = message.payload as Omit<SttStatusType, 'receivedAt'>;
          // receivedAt은 '수신 순간'에 스탬프 — 표시를 지연해도 audio_clock 앵커의
          // 경과시간 보간이 정확해야 영상-자막 동기화가 어긋나지 않는다.
          const stamped: SttStatusType = { ...s, receivedAt: Date.now() };
          const applyStatus = () => {
            if (!isMountedRef.current) return;
            setSttStatus(stamped);
          };
          const statusDelay = displayDelayRef.current;
          if (statusDelay > 0) {
            const timer: NodeJS.Timeout = setTimeout(() => {
              delayTimersRef.current = delayTimersRef.current.filter((t) => t !== timer);
              applyStatus();
            }, statusDelay);
            delayTimersRef.current.push(timer);
          } else {
            applyStatus();
          }
        } else if (message.type === 'subtitle_interim') {
          // STT interim (미확정) 텍스트 - 즉시 표시 (displayDelay 미적용)
          const interim = message.payload as { text: string };
          setInterimText(interim.text);
          setLastActivityTime(Date.now());
        } else if (message.type === 'subtitle_created') {
          // 실시간 자막 수신
          const subtitleEvent = message as SubtitleCreatedEvent;
          const newSubtitle = subtitleEvent.payload.subtitle;

          const addSubtitle = () => {
            if (!isMountedRef.current) return;

            // BUG #3: Check if there's a buffered correction for this subtitle
            const buffered = pendingCorrectionsRef.current.get(newSubtitle.id);
            if (buffered) {
              // Apply buffered correction immediately
              clearTimeout(buffered.timer);
              pendingCorrectionsRef.current.delete(newSubtitle.id);
              const hasText = !!buffered.corrected_text;
              const correctedSubtitle: SubtitleType = {
                ...newSubtitle,
                // 텍스트 교정이 있을 때만 text/original_text 갱신
                ...(hasText
                  ? {
                      original_text: newSubtitle.text,
                      text: buffered.corrected_text as string,
                      is_corrected: true,
                      correction_state: 'corrected' as const,
                    }
                  : { correction_state: 'pending' as const }),
                // diarize가 화자를 함께 보냈으면 반영, 아니면 원래 화자 유지
                speaker: buffered.speaker !== undefined ? buffered.speaker : newSubtitle.speaker,
              };
              setSubtitles((prev) => [...prev, correctedSubtitle]);
            } else {
              // 새 자막: pending 상태로 시작 (교정 대기)
              setSubtitles((prev) => [...prev, { ...newSubtitle, correction_state: 'pending' }]);
            }

            // 안전장치: 교정 이벤트가 오지 않으면 일정 시간 후 pending 해제
            // (발화 시 목록에서 자기 자신을 제거 — 장시간 라이브에서 배열 무한 증가 방지)
            const pendingTimer: NodeJS.Timeout = setTimeout(() => {
              delayTimersRef.current = delayTimersRef.current.filter((t) => t !== pendingTimer);
              if (!isMountedRef.current) return;
              setSubtitles((prev) =>
                prev.map((s) =>
                  s.id === newSubtitle.id && s.correction_state === 'pending'
                    ? { ...s, correction_state: null }
                    : s
                )
              );
            }, PENDING_CORRECTION_TIMEOUT_MS);
            delayTimersRef.current.push(pendingTimer);

            // interim 클리어하지 않음 — 다음 subtitle_interim이 새 텍스트로 덮어씀
            // 국회 자막 스타일: 확정 줄이 추가되고, 인식 중 줄은 계속 업데이트
            setLastActivityTime(Date.now());
            if (onSubtitleRef.current) {
              onSubtitleRef.current(newSubtitle);
            }
          };

          // displayDelay > 0이면 영상과 싱크를 맞추기 위해 지연 표시
          const subtitleDelay = displayDelayRef.current;
          if (subtitleDelay > 0) {
            const timer = setTimeout(addSubtitle, subtitleDelay);
            delayTimersRef.current.push(timer);
          } else {
            addSubtitle();
          }
        } else if (message.type === 'subtitle_corrected') {
          // OpenAI 교정 결과 수신 → 기존 자막 텍스트 교체
          const correctedEvent = message as SubtitleCorrectedEvent;
          const { id, corrected_text, meeting_id: correctionMeetingId, speaker: correctedSpeaker } = correctedEvent.payload;

          // meeting_id 검증 (채널 ID 기반 방송 시에는 correctionMeetingId가 UUID라 건너뜀)
          // 백엔드는 이미 channel_id 룸으로 필터된 이벤트만 보냄 — 여기서 중복 필터는 불필요.
          void correctionMeetingId;

          const applyCorrection = () => {
            setSubtitles((prev) => {
              const exists = prev.some((s) => s.id === id);
              if (exists) {
                // Subtitle exists - apply correction directly.
                // diarize 경로는 텍스트 없이 speaker만 보낼 수 있으므로 corrected_text가 있을 때만 텍스트 교체.
                return prev.map((s) =>
                  s.id === id
                    ? {
                        ...s,
                        ...(corrected_text
                          ? {
                              original_text: s.text,
                              text: corrected_text,
                              is_corrected: true,
                              correction_state: 'corrected' as const,
                            }
                          : {}),
                        speaker: correctedSpeaker !== undefined ? correctedSpeaker : s.speaker,
                      }
                    : s
                );
              } else {
                // 자막보다 교정이 먼저 도착한 경우 버퍼링 (경합 상태)
                console.warn(
                  `[useSubtitleWebSocket] Correction arrived before subtitle (id=${id.substring(0, 8)}), buffering for up to 30s`
                );
                const cleanupTimer = setTimeout(() => {
                  pendingCorrectionsRef.current.delete(id);
                }, CORRECTION_BUFFER_CLEANUP_MS);
                pendingCorrectionsRef.current.set(id, {
                  corrected_text,
                  speaker: correctedSpeaker,
                  timer: cleanupTimer,
                });
                return prev;
              }
            });
          };

          // 자막과 동일한 displayDelay 적용 — A/V sync 유지
          // (자막보다 교정이 먼저 도착해도, 원본 자막과 함께 지연되어 시각적으로 동시에 업데이트)
          const correctionDelay = displayDelayRef.current;
          if (correctionDelay > 0) {
            const timer = setTimeout(applyCorrection, correctionDelay);
            delayTimersRef.current.push(timer);
          } else {
            applyCorrection();
          }
        } else if (message.type === 'material_request_detected') {
          // 요구자료 감지 — 모니터링 패널로 전달 (자막 상태와 무관, 지연 미적용)
          const request = message.payload as MaterialRequestType;
          if (request && request.summary) {
            onMaterialRequestRef.current?.(request);
          }
        } else if (message.type === 'subtitle_correction_failed') {
          // 교정 실패 이벤트 - pending 상태 해제
          const failedEvent = message as SubtitleCorrectionFailedEvent;
          const { subtitle_id } = failedEvent.payload;

          // Remove from pending corrections buffer if present
          const buffered = pendingCorrectionsRef.current.get(subtitle_id);
          if (buffered) {
            clearTimeout(buffered.timer);
            pendingCorrectionsRef.current.delete(subtitle_id);
          }

          // pending('교정 중') 해제 — correction_state를 지우지 않으면 배지가 영원히 남는다
          setSubtitles((prev) =>
            prev.map((s) =>
              s.id === subtitle_id
                ? { ...s, is_corrected: false, correction_state: null }
                : s
            )
          );
        }
      } catch (error) {
        console.error('Failed to parse WebSocket message:', error);
      }
    };

    ws.onerror = () => {
      if (!isMountedRef.current) return;
      setConnectionStatus('error');
    };

    ws.onclose = (event: CloseEvent) => {
      if (!isMountedRef.current) return;

      // 이미 교체된 연결의 close 이벤트이면 무시
      if (wsRef.current !== ws) return;

      // 수동 해제가 아니고 비정상 종료인 경우 재연결 시도
      if (!isManualDisconnectRef.current && !event.wasClean) {
        setConnectionStatus('connecting');
        const delay = getReconnectDelay();
        reconnectAttemptRef.current += 1;

        reconnectTimeoutRef.current = setTimeout(() => {
          if (isMountedRef.current && !isManualDisconnectRef.current) {
            createConnection();
          }
        }, delay);
      } else {
        setConnectionStatus('disconnected');
      }
    };
  }, [meetingId, clearReconnectTimeout, getReconnectDelay]);

  /**
   * 수동 연결
   */
  const connect = useCallback(() => {
    isManualDisconnectRef.current = false;
    createConnection();
  }, [createConnection]);

  /**
   * 대기 중인 지연 타이머 모두 정리
   */
  const clearDelayTimers = useCallback(() => {
    delayTimersRef.current.forEach(clearTimeout);
    delayTimersRef.current = [];
  }, []);

  /**
   * 수동 해제
   */
  const disconnect = useCallback(() => {
    isManualDisconnectRef.current = true;
    clearReconnectTimeout();
    clearDelayTimers();

    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }

    setConnectionStatus('disconnected');
  }, [clearReconnectTimeout, clearDelayTimers]);

  /**
   * 자막 배열 초기화
   */
  const clearSubtitles = useCallback(() => {
    setSubtitles([]);
  }, []);

  // 자동 연결 및 meetingId 변경 처리
  useEffect(() => {
    isMountedRef.current = true;
    isManualDisconnectRef.current = false;

    // meetingId 변경 시 자막 초기화
    setSubtitles([]);
    setInterimText('');
    setLastActivityTime(null);
    setSttStatus(null);

    // Clear pending corrections buffer
    pendingCorrectionsRef.current.forEach(({ timer }) => clearTimeout(timer));
    pendingCorrectionsRef.current.clear();

    if (autoConnect) {
      createConnection();
    }

    return () => {
      isMountedRef.current = false;
      clearReconnectTimeout();
      clearDelayTimers();

      // Clean up pending corrections buffer
      pendingCorrectionsRef.current.forEach(({ timer }) => clearTimeout(timer));
      pendingCorrectionsRef.current.clear();

      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, [meetingId, autoConnect, createConnection, clearReconnectTimeout, clearDelayTimers]);

  return {
    subtitles,
    interimText,
    lastActivityTime,
    sttStatus,
    connectionStatus,
    connect,
    disconnect,
    clearSubtitles,
  };
}

export default useSubtitleWebSocket;
