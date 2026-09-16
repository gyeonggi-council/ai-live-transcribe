/**
 * useSubtitleWebSocket 훅 테스트
 *
 * TDD RED Phase - 테스트 먼저 작성
 *
 * 테스트 케이스:
 * 1. WebSocket 연결 성공
 * 2. subtitle_created 이벤트 수신 및 상태 업데이트
 * 3. 연결 끊김 시 자동 재연결 (exponential backoff)
 * 4. 수동 연결/해제
 * 5. 컴포넌트 언마운트 시 연결 정리
 * 6. 에러 상태 처리
 * 7. 자막 배열 초기화 (clearSubtitles)
 */

import { renderHook, act } from '@testing-library/react';

import type { SubtitleType } from '@/types';

import { useSubtitleWebSocket } from '../useSubtitleWebSocket';

// Mock WebSocket
class MockWebSocket {
  static instances: MockWebSocket[] = [];
  static lastUrl: string | null = null;

  url: string;
  readyState: number = WebSocket.CONNECTING;
  onopen: ((event: Event) => void) | null = null;
  onclose: ((event: CloseEvent) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;

  constructor(url: string) {
    this.url = url;
    MockWebSocket.lastUrl = url;
    MockWebSocket.instances.push(this);
  }

  close() {
    this.readyState = WebSocket.CLOSED;
    if (this.onclose) {
      this.onclose(new CloseEvent('close'));
    }
  }

  simulateOpen() {
    this.readyState = WebSocket.OPEN;
    if (this.onopen) {
      this.onopen(new Event('open'));
    }
  }

  simulateMessage(data: object) {
    if (this.onmessage) {
      this.onmessage(new MessageEvent('message', { data: JSON.stringify(data) }));
    }
  }

  simulateError() {
    if (this.onerror) {
      this.onerror(new Event('error'));
    }
  }

  simulateClose(code: number = 1000, wasClean: boolean = true) {
    this.readyState = WebSocket.CLOSED;
    if (this.onclose) {
      this.onclose(new CloseEvent('close', { code, wasClean }));
    }
  }

  static clearInstances() {
    MockWebSocket.instances = [];
    MockWebSocket.lastUrl = null;
  }

  static getLastInstance(): MockWebSocket | undefined {
    return MockWebSocket.instances[MockWebSocket.instances.length - 1];
  }
}

// Replace global WebSocket with mock
const originalWebSocket = global.WebSocket;

// Mock environment variable
const mockWsUrl = 'ws://localhost:8000';
process.env.NEXT_PUBLIC_WS_URL = mockWsUrl;

// Mock subtitle data
const mockSubtitle: SubtitleType = {
  id: 'subtitle-1',
  meeting_id: 'meeting-1',
  start_time: 0,
  end_time: 5,
  text: '안녕하세요, 회의를 시작하겠습니다.',
  speaker: '의장',
  confidence: 0.95,
  created_at: '2026-02-05T10:00:00Z',
};

const mockSubtitle2: SubtitleType = {
  id: 'subtitle-2',
  meeting_id: 'meeting-1',
  start_time: 5,
  end_time: 10,
  text: '오늘의 안건은 예산안 심의입니다.',
  speaker: '의장',
  confidence: 0.92,
  created_at: '2026-02-05T10:00:05Z',
};

describe('useSubtitleWebSocket', () => {
  beforeEach(() => {
    jest.useFakeTimers();
    MockWebSocket.clearInstances();
    (global as { WebSocket: typeof WebSocket }).WebSocket = MockWebSocket as unknown as typeof WebSocket;
  });

  afterEach(() => {
    jest.useRealTimers();
    (global as unknown as { WebSocket: typeof WebSocket }).WebSocket = originalWebSocket;
  });

  describe('Connection', () => {
    it('should connect to WebSocket when autoConnect is true (default)', async () => {
      const { result } = renderHook(() =>
        useSubtitleWebSocket({ meetingId: 'meeting-1' })
      );

      expect(result.current.connectionStatus).toBe('connecting');
      expect(MockWebSocket.lastUrl).toBe(`${mockWsUrl}/ws/meetings/meeting-1/subtitles`);
    });

    it('should not connect when autoConnect is false', () => {
      const { result } = renderHook(() =>
        useSubtitleWebSocket({ meetingId: 'meeting-1', autoConnect: false })
      );

      expect(result.current.connectionStatus).toBe('disconnected');
      expect(MockWebSocket.instances.length).toBe(0);
    });

    it('should update status to connected when WebSocket opens', async () => {
      const { result } = renderHook(() =>
        useSubtitleWebSocket({ meetingId: 'meeting-1' })
      );

      const ws = MockWebSocket.getLastInstance();
      expect(ws).toBeDefined();

      act(() => {
        ws!.simulateOpen();
      });

      expect(result.current.connectionStatus).toBe('connected');
    });

    it('should return empty subtitles array initially', () => {
      const { result } = renderHook(() =>
        useSubtitleWebSocket({ meetingId: 'meeting-1' })
      );

      expect(result.current.subtitles).toEqual([]);
    });
  });

  describe('Receiving subtitles', () => {
    it('should receive and store subtitle_created events', async () => {
      const { result } = renderHook(() =>
        useSubtitleWebSocket({ meetingId: 'meeting-1' })
      );

      const ws = MockWebSocket.getLastInstance();

      act(() => {
        ws!.simulateOpen();
      });

      act(() => {
        ws!.simulateMessage({
          type: 'subtitle_created',
          payload: { subtitle: mockSubtitle },
        });
      });

      expect(result.current.subtitles).toHaveLength(1);
      expect(result.current.subtitles[0]).toMatchObject(mockSubtitle);
    });

    it('should accumulate multiple subtitles', async () => {
      const { result } = renderHook(() =>
        useSubtitleWebSocket({ meetingId: 'meeting-1' })
      );

      const ws = MockWebSocket.getLastInstance();

      act(() => {
        ws!.simulateOpen();
      });

      act(() => {
        ws!.simulateMessage({
          type: 'subtitle_created',
          payload: { subtitle: mockSubtitle },
        });
      });

      act(() => {
        ws!.simulateMessage({
          type: 'subtitle_created',
          payload: { subtitle: mockSubtitle2 },
        });
      });

      expect(result.current.subtitles).toHaveLength(2);
      expect(result.current.subtitles[0]).toMatchObject(mockSubtitle);
      expect(result.current.subtitles[1]).toMatchObject(mockSubtitle2);
    });

    it('should call onSubtitle callback when subtitle is received', async () => {
      const onSubtitle = jest.fn();

      renderHook(() =>
        useSubtitleWebSocket({
          meetingId: 'meeting-1',
          onSubtitle,
        })
      );

      const ws = MockWebSocket.getLastInstance();

      act(() => {
        ws!.simulateOpen();
      });

      act(() => {
        ws!.simulateMessage({
          type: 'subtitle_created',
          payload: { subtitle: mockSubtitle },
        });
      });

      expect(onSubtitle).toHaveBeenCalledTimes(1);
      expect(onSubtitle).toHaveBeenCalledWith(mockSubtitle);
    });

    it('should handle invalid JSON messages gracefully', async () => {
      const consoleSpy = jest.spyOn(console, 'error').mockImplementation();

      const { result } = renderHook(() =>
        useSubtitleWebSocket({ meetingId: 'meeting-1' })
      );

      const ws = MockWebSocket.getLastInstance();

      act(() => {
        ws!.simulateOpen();
      });

      // Send invalid JSON
      act(() => {
        if (ws!.onmessage) {
          ws!.onmessage(new MessageEvent('message', { data: 'invalid json {{{' }));
        }
      });

      // Should not add any subtitles
      expect(result.current.subtitles).toHaveLength(0);
      // Should log error
      expect(consoleSpy).toHaveBeenCalled();

      consoleSpy.mockRestore();
    });

    it('should ignore non-subtitle_created events', async () => {
      const { result } = renderHook(() =>
        useSubtitleWebSocket({ meetingId: 'meeting-1' })
      );

      const ws = MockWebSocket.getLastInstance();

      act(() => {
        ws!.simulateOpen();
      });

      act(() => {
        ws!.simulateMessage({
          type: 'meeting_status_changed',
          payload: { meeting_id: 'meeting-1', status: 'ended' },
        });
      });

      expect(result.current.subtitles).toHaveLength(0);
    });
  });

  describe('Error handling', () => {
    it('should update status to error when WebSocket error occurs', async () => {
      const { result } = renderHook(() =>
        useSubtitleWebSocket({ meetingId: 'meeting-1' })
      );

      const ws = MockWebSocket.getLastInstance();

      act(() => {
        ws!.simulateError();
      });

      expect(result.current.connectionStatus).toBe('error');
    });

    it('should update status to disconnected when connection closes', async () => {
      const { result } = renderHook(() =>
        useSubtitleWebSocket({ meetingId: 'meeting-1' })
      );

      const ws = MockWebSocket.getLastInstance();

      act(() => {
        ws!.simulateOpen();
      });

      expect(result.current.connectionStatus).toBe('connected');

      act(() => {
        ws!.simulateClose();
      });

      // After close, it should start reconnecting, so status would be 'connecting' or 'disconnected'
      // depending on implementation. For clean close, it might stay disconnected.
      expect(['disconnected', 'connecting']).toContain(result.current.connectionStatus);
    });
  });

  describe('Auto-reconnect', () => {
    // 재연결 지연에 지터(0.5~1.5배)가 곱해진다 — 0.5 고정(배율 1.0)으로
    // 기존의 정확한 백오프 시각(1000ms, 2000ms 경계) 단언을 유지한다.
    let randomSpy: jest.SpyInstance;
    beforeEach(() => {
      randomSpy = jest.spyOn(Math, 'random').mockReturnValue(0.5);
    });
    afterEach(() => {
      randomSpy.mockRestore();
    });

    it('should attempt to reconnect after unexpected close', async () => {
      const { result } = renderHook(() =>
        useSubtitleWebSocket({ meetingId: 'meeting-1' })
      );

      const initialInstanceCount = MockWebSocket.instances.length;
      const ws1 = MockWebSocket.getLastInstance();

      act(() => {
        ws1!.simulateOpen();
      });

      expect(result.current.connectionStatus).toBe('connected');

      // Simulate unexpected close (wasClean = false)
      act(() => {
        ws1!.simulateClose(1006, false);
      });

      // Should be trying to reconnect
      expect(result.current.connectionStatus).toBe('connecting');

      // Advance timer by initial delay (1000ms)
      act(() => {
        jest.advanceTimersByTime(1000);
      });

      // A new WebSocket should be created
      expect(MockWebSocket.instances.length).toBe(initialInstanceCount + 1);
    });

    it('should use exponential backoff for subsequent reconnect attempts', async () => {
      renderHook(() =>
        useSubtitleWebSocket({ meetingId: 'meeting-1' })
      );

      const ws1 = MockWebSocket.getLastInstance();

      act(() => {
        ws1!.simulateOpen();
      });

      // First unexpected close
      act(() => {
        ws1!.simulateClose(1006, false);
      });

      // First reconnect after 1000ms
      act(() => {
        jest.advanceTimersByTime(1000);
      });

      const ws2 = MockWebSocket.getLastInstance();
      const instancesAfterFirstReconnect = MockWebSocket.instances.length;

      // Second unexpected close (without opening - simulating immediate failure)
      act(() => {
        ws2!.simulateClose(1006, false);
      });

      // Should not reconnect before 2000ms (exponential backoff: 1000 * 2^1 = 2000)
      act(() => {
        jest.advanceTimersByTime(1999);
      });

      expect(MockWebSocket.instances.length).toBe(instancesAfterFirstReconnect);

      // Should reconnect at 2000ms
      act(() => {
        jest.advanceTimersByTime(1);
      });

      expect(MockWebSocket.instances.length).toBe(instancesAfterFirstReconnect + 1);
    });

    it('should not reconnect when manually disconnected', async () => {
      const { result } = renderHook(() =>
        useSubtitleWebSocket({ meetingId: 'meeting-1' })
      );

      const ws = MockWebSocket.getLastInstance();

      act(() => {
        ws!.simulateOpen();
      });

      // Manually disconnect
      act(() => {
        result.current.disconnect();
      });

      expect(result.current.connectionStatus).toBe('disconnected');

      // Advance timer
      act(() => {
        jest.advanceTimersByTime(5000);
      });

      // Should not create new WebSocket
      expect(MockWebSocket.instances.length).toBe(1);
    });

    it('should reset reconnect attempts on successful connection', async () => {
      const { result } = renderHook(() =>
        useSubtitleWebSocket({ meetingId: 'meeting-1' })
      );

      const ws1 = MockWebSocket.getLastInstance();

      // First connection fails
      act(() => {
        ws1!.simulateClose(1006, false);
      });

      // Wait for reconnect
      act(() => {
        jest.advanceTimersByTime(1000);
      });

      const ws2 = MockWebSocket.getLastInstance();

      // Second connection succeeds
      act(() => {
        ws2!.simulateOpen();
      });

      expect(result.current.connectionStatus).toBe('connected');

      // Close again
      act(() => {
        ws2!.simulateClose(1006, false);
      });

      // Should start from initial delay (1000ms) since attempts were reset
      act(() => {
        jest.advanceTimersByTime(1000);
      });

      expect(MockWebSocket.instances.length).toBe(3);
    });
  });

  describe('Manual connect/disconnect', () => {
    it('should allow manual connection when autoConnect is false', async () => {
      const { result } = renderHook(() =>
        useSubtitleWebSocket({ meetingId: 'meeting-1', autoConnect: false })
      );

      expect(result.current.connectionStatus).toBe('disconnected');
      expect(MockWebSocket.instances.length).toBe(0);

      act(() => {
        result.current.connect();
      });

      expect(result.current.connectionStatus).toBe('connecting');
      expect(MockWebSocket.instances.length).toBe(1);
    });

    it('should close connection when disconnect is called', async () => {
      const { result } = renderHook(() =>
        useSubtitleWebSocket({ meetingId: 'meeting-1' })
      );

      const ws = MockWebSocket.getLastInstance();

      act(() => {
        ws!.simulateOpen();
      });

      expect(result.current.connectionStatus).toBe('connected');

      act(() => {
        result.current.disconnect();
      });

      expect(result.current.connectionStatus).toBe('disconnected');
    });

    it('should reconnect when connect is called after disconnect', async () => {
      const { result } = renderHook(() =>
        useSubtitleWebSocket({ meetingId: 'meeting-1' })
      );

      const ws1 = MockWebSocket.getLastInstance();

      act(() => {
        ws1!.simulateOpen();
      });

      act(() => {
        result.current.disconnect();
      });

      expect(MockWebSocket.instances.length).toBe(1);

      act(() => {
        result.current.connect();
      });

      expect(MockWebSocket.instances.length).toBe(2);
      expect(result.current.connectionStatus).toBe('connecting');
    });
  });

  describe('clearSubtitles', () => {
    it('should clear all subtitles when clearSubtitles is called', async () => {
      const { result } = renderHook(() =>
        useSubtitleWebSocket({ meetingId: 'meeting-1' })
      );

      const ws = MockWebSocket.getLastInstance();

      act(() => {
        ws!.simulateOpen();
      });

      act(() => {
        ws!.simulateMessage({
          type: 'subtitle_created',
          payload: { subtitle: mockSubtitle },
        });
      });

      act(() => {
        ws!.simulateMessage({
          type: 'subtitle_created',
          payload: { subtitle: mockSubtitle2 },
        });
      });

      expect(result.current.subtitles).toHaveLength(2);

      act(() => {
        result.current.clearSubtitles();
      });

      expect(result.current.subtitles).toHaveLength(0);
    });
  });

  describe('Cleanup', () => {
    it('should close WebSocket on unmount', async () => {
      const { result, unmount } = renderHook(() =>
        useSubtitleWebSocket({ meetingId: 'meeting-1' })
      );

      const ws = MockWebSocket.getLastInstance();

      act(() => {
        ws!.simulateOpen();
      });

      expect(result.current.connectionStatus).toBe('connected');

      unmount();

      expect(ws!.readyState).toBe(WebSocket.CLOSED);
    });

    it('should not attempt reconnect after unmount', async () => {
      const { unmount } = renderHook(() =>
        useSubtitleWebSocket({ meetingId: 'meeting-1' })
      );

      const ws = MockWebSocket.getLastInstance();

      act(() => {
        ws!.simulateOpen();
      });

      unmount();

      // Advance timers
      act(() => {
        jest.advanceTimersByTime(10000);
      });

      // Should only have the initial WebSocket instance
      expect(MockWebSocket.instances.length).toBe(1);
    });
  });

  describe('Correction buffering (BUG #3)', () => {
    it('should buffer corrections that arrive before their subtitle and apply when subtitle arrives', async () => {
      const { result } = renderHook(() =>
        useSubtitleWebSocket({ meetingId: 'meeting-1' })
      );

      const ws = MockWebSocket.getLastInstance();

      act(() => {
        ws!.simulateOpen();
      });

      // Send correction BEFORE the subtitle
      act(() => {
        ws!.simulateMessage({
          type: 'subtitle_corrected',
          payload: {
            id: 'subtitle-1',
            corrected_text: '안녕하세요, 회의를 시작하겠습니다. (교정됨)',
            meeting_id: 'meeting-1',
          },
        });
      });

      // No subtitles yet
      expect(result.current.subtitles).toHaveLength(0);

      // Now send the subtitle
      act(() => {
        ws!.simulateMessage({
          type: 'subtitle_created',
          payload: { subtitle: mockSubtitle },
        });
      });

      // Subtitle should be added with the corrected text already applied
      expect(result.current.subtitles).toHaveLength(1);
      expect(result.current.subtitles[0].text).toBe('안녕하세요, 회의를 시작하겠습니다. (교정됨)');
      expect(result.current.subtitles[0].is_corrected).toBe(true);
      expect(result.current.subtitles[0].original_text).toBe(mockSubtitle.text);
    });

    it('should apply correction directly when subtitle already exists', async () => {
      const { result } = renderHook(() =>
        useSubtitleWebSocket({ meetingId: 'meeting-1' })
      );

      const ws = MockWebSocket.getLastInstance();

      act(() => {
        ws!.simulateOpen();
      });

      // First, add the subtitle
      act(() => {
        ws!.simulateMessage({
          type: 'subtitle_created',
          payload: { subtitle: mockSubtitle },
        });
      });

      expect(result.current.subtitles).toHaveLength(1);
      expect(result.current.subtitles[0].text).toBe(mockSubtitle.text);

      // Then send the correction
      act(() => {
        ws!.simulateMessage({
          type: 'subtitle_corrected',
          payload: {
            id: 'subtitle-1',
            corrected_text: '교정된 텍스트',
            meeting_id: 'meeting-1',
          },
        });
      });

      expect(result.current.subtitles).toHaveLength(1);
      expect(result.current.subtitles[0].text).toBe('교정된 텍스트');
      expect(result.current.subtitles[0].is_corrected).toBe(true);
    });

    it('should log a warning when buffering a correction (BUG #4)', async () => {
      const consoleSpy = jest.spyOn(console, 'warn').mockImplementation();

      renderHook(() =>
        useSubtitleWebSocket({ meetingId: 'meeting-1' })
      );

      const ws = MockWebSocket.getLastInstance();

      act(() => {
        ws!.simulateOpen();
      });

      // Send correction before subtitle exists
      act(() => {
        ws!.simulateMessage({
          type: 'subtitle_corrected',
          payload: {
            id: 'subtitle-1',
            corrected_text: '교정 텍스트',
            meeting_id: 'meeting-1',
          },
        });
      });

      expect(consoleSpy).toHaveBeenCalledWith(
        expect.stringContaining('Correction arrived before subtitle')
      );

      consoleSpy.mockRestore();
    });
  });

  describe('subtitle_correction_failed handling', () => {
    it('should set is_corrected to false when correction fails for existing subtitle', async () => {
      const { result } = renderHook(() =>
        useSubtitleWebSocket({ meetingId: 'meeting-1' })
      );

      const ws = MockWebSocket.getLastInstance();

      act(() => {
        ws!.simulateOpen();
      });

      // Add subtitle
      act(() => {
        ws!.simulateMessage({
          type: 'subtitle_created',
          payload: { subtitle: mockSubtitle },
        });
      });

      // Send correction failed event
      act(() => {
        ws!.simulateMessage({
          type: 'subtitle_correction_failed',
          payload: {
            subtitle_id: 'subtitle-1',
            reason: 'text_too_short',
          },
        });
      });

      expect(result.current.subtitles).toHaveLength(1);
      expect(result.current.subtitles[0].is_corrected).toBe(false);
    });

    it('should clear buffered correction when correction_failed arrives', async () => {
      const { result } = renderHook(() =>
        useSubtitleWebSocket({ meetingId: 'meeting-1' })
      );

      const ws = MockWebSocket.getLastInstance();

      act(() => {
        ws!.simulateOpen();
      });

      // Buffer a correction (subtitle not added yet)
      act(() => {
        ws!.simulateMessage({
          type: 'subtitle_corrected',
          payload: {
            id: 'subtitle-1',
            corrected_text: '교정 텍스트',
            meeting_id: 'meeting-1',
          },
        });
      });

      // Then receive correction_failed for same subtitle
      act(() => {
        ws!.simulateMessage({
          type: 'subtitle_correction_failed',
          payload: {
            subtitle_id: 'subtitle-1',
            reason: 'not_returned_by_openai',
          },
        });
      });

      // Now add the subtitle - it should NOT have the correction applied
      act(() => {
        ws!.simulateMessage({
          type: 'subtitle_created',
          payload: { subtitle: mockSubtitle },
        });
      });

      expect(result.current.subtitles).toHaveLength(1);
      expect(result.current.subtitles[0].text).toBe(mockSubtitle.text);
      expect(result.current.subtitles[0].is_corrected).toBeUndefined();
    });
  });

  describe('Speaker assignment via diarize (subtitle_corrected, speaker only)', () => {
    it('updates speaker without changing text when only speaker is sent', () => {
      const { result } = renderHook(() =>
        useSubtitleWebSocket({ meetingId: 'meeting-1' })
      );
      const ws = MockWebSocket.getLastInstance();
      act(() => {
        ws!.simulateOpen();
      });
      act(() => {
        ws!.simulateMessage({
          type: 'subtitle_created',
          payload: { subtitle: mockSubtitle },
        });
      });
      // 화자 구분(diarize) 경로: corrected_text 없이 speaker만 전송
      act(() => {
        ws!.simulateMessage({
          type: 'subtitle_corrected',
          payload: {
            id: 'subtitle-1',
            speaker: '화자 2',
            meeting_id: 'meeting-1',
            source: 'diarize',
          },
        });
      });

      // 화자는 갱신되고 텍스트는 그대로, 텍스트 교정 플래그는 설정되지 않음
      expect(result.current.subtitles[0].speaker).toBe('화자 2');
      expect(result.current.subtitles[0].text).toBe(mockSubtitle.text);
      expect(result.current.subtitles[0].is_corrected).toBeUndefined();
    });
  });

  describe('Meeting ID validation (RISK #2)', () => {
    it('applies corrections regardless of payload meeting_id (backend filters by room)', async () => {
      // 채널 ID 방송에서는 payload.meeting_id가 UUID(실제 회의)라 룸 ID와 다르다.
      // 백엔드가 이미 channel_id 룸으로 필터된 이벤트만 보내므로 프론트는 재필터하지 않는다.
      const { result } = renderHook(() =>
        useSubtitleWebSocket({ meetingId: 'meeting-1' })
      );

      const ws = MockWebSocket.getLastInstance();

      act(() => {
        ws!.simulateOpen();
      });

      // Add subtitle
      act(() => {
        ws!.simulateMessage({
          type: 'subtitle_created',
          payload: { subtitle: mockSubtitle },
        });
      });

      // Send correction whose payload meeting_id differs from the room id
      act(() => {
        ws!.simulateMessage({
          type: 'subtitle_corrected',
          payload: {
            id: 'subtitle-1',
            corrected_text: '교정된 텍스트',
            meeting_id: 'different-meeting',
          },
        });
      });

      expect(result.current.subtitles[0].text).toBe('교정된 텍스트');
      expect(result.current.subtitles[0].is_corrected).toBe(true);
    });

    it('should apply corrections when meeting_id matches', async () => {
      const { result } = renderHook(() =>
        useSubtitleWebSocket({ meetingId: 'meeting-1' })
      );

      const ws = MockWebSocket.getLastInstance();

      act(() => {
        ws!.simulateOpen();
      });

      // Add subtitle
      act(() => {
        ws!.simulateMessage({
          type: 'subtitle_created',
          payload: { subtitle: mockSubtitle },
        });
      });

      // Send correction with matching meeting_id
      act(() => {
        ws!.simulateMessage({
          type: 'subtitle_corrected',
          payload: {
            id: 'subtitle-1',
            corrected_text: '교정된 텍스트',
            meeting_id: 'meeting-1',
          },
        });
      });

      expect(result.current.subtitles[0].text).toBe('교정된 텍스트');
      expect(result.current.subtitles[0].is_corrected).toBe(true);
    });

    it('should apply corrections when meeting_id is not provided (backward compatibility)', async () => {
      const { result } = renderHook(() =>
        useSubtitleWebSocket({ meetingId: 'meeting-1' })
      );

      const ws = MockWebSocket.getLastInstance();

      act(() => {
        ws!.simulateOpen();
      });

      // Add subtitle
      act(() => {
        ws!.simulateMessage({
          type: 'subtitle_created',
          payload: { subtitle: mockSubtitle },
        });
      });

      // Send correction without meeting_id (backward compat)
      act(() => {
        ws!.simulateMessage({
          type: 'subtitle_corrected',
          payload: {
            id: 'subtitle-1',
            corrected_text: '교정된 텍스트',
          },
        });
      });

      expect(result.current.subtitles[0].text).toBe('교정된 텍스트');
      expect(result.current.subtitles[0].is_corrected).toBe(true);
    });
  });

  describe('Meeting ID changes', () => {
    it('should reconnect when meetingId changes', async () => {
      const { result, rerender } = renderHook(
        ({ meetingId }: { meetingId: string }) =>
          useSubtitleWebSocket({ meetingId }),
        { initialProps: { meetingId: 'meeting-1' } }
      );

      const ws1 = MockWebSocket.getLastInstance();

      act(() => {
        ws1!.simulateOpen();
      });

      act(() => {
        ws1!.simulateMessage({
          type: 'subtitle_created',
          payload: { subtitle: mockSubtitle },
        });
      });

      expect(result.current.subtitles).toHaveLength(1);

      // Change meeting ID
      rerender({ meetingId: 'meeting-2' });

      expect(MockWebSocket.instances.length).toBe(2);
      expect(MockWebSocket.lastUrl).toBe(`${mockWsUrl}/ws/meetings/meeting-2/subtitles`);

      // Subtitles should be cleared when meeting changes
      expect(result.current.subtitles).toHaveLength(0);
    });
  });
});
