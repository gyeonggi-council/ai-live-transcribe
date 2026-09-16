/**
 * useAiChat — 답을 조각으로 받아 말풍선을 채우고, 끝나면 서버 정리본·출처로 바꾼다(2026-09-15).
 */
import { act, renderHook, waitFor } from '@testing-library/react';

import { ApiError } from '@/lib/api';

import { useAiChat } from '../useAiChat';

const mockStream = jest.fn();
jest.mock('@/lib/api', () => {
  const actual = jest.requireActual('@/lib/api');
  return { ...actual, aiChatStream: (...args: unknown[]) => mockStream(...args) };
});

type Opts = { onDelta: (t: string) => void; onStatus?: (t: string) => void; onReset?: () => void; signal?: AbortSignal };

describe('useAiChat (stream)', () => {
  beforeEach(() => mockStream.mockReset());

  it('shows streamed text, then replaces it with the cleaned final answer', async () => {
    let release!: () => void;
    mockStream.mockImplementation(async (_q: string, _s: string, _m: string, { onDelta }: Opts) => {
      onDelta('**예산**');
      await new Promise<void>((r) => (release = r));
      return { answer: '예산은 가결', sources: [{ meeting_id: 'm', meeting_title: 't', start_time: 1, text_snippet: 'x' }], session_id: 's9', saved: true };
    });
    const { result } = renderHook(() => useAiChat('m1'));
    let done!: Promise<void>;
    act(() => {
      done = result.current.sendMessage('질문');
    });
    await waitFor(() => expect(result.current.streaming).toBe(true));
    expect(result.current.messages.at(-1)).toMatchObject({ role: 'assistant', content: '**예산**' });
    await act(async () => {
      release();
      await done;
    });
    expect(result.current.messages).toHaveLength(2);
    const answer = result.current.messages[1];
    expect(answer).toMatchObject({ role: 'assistant', content: '예산은 가결' });
    expect(answer?.sources).toHaveLength(1);
    expect(result.current.sessionId).toBe('s9');
    expect(result.current.loading).toBe(false);
    expect(result.current.streaming).toBe(false);
  });

  it('drops the partial answer on failure so retry resends the same question', async () => {
    mockStream.mockImplementationOnce(async (_q: string, _s: string, _m: string, { onDelta }: Opts) => {
      onDelta('반쪽');
      throw new ApiError(502, 'AI 응답이 중간에 끊겼습니다.');
    });
    const { result } = renderHook(() => useAiChat('m1'));
    await act(async () => {
      await result.current.sendMessage('질문');
    });
    expect(result.current.messages).toEqual([{ role: 'user', content: '질문' }]);
    expect(result.current.error).toContain('끊겼습니다');

    mockStream.mockResolvedValueOnce({ answer: '답', sources: [], session_id: 's1', saved: true });
    await act(async () => {
      await result.current.retryLast();
    });
    expect(result.current.messages.map((m) => m.content)).toEqual(['질문', '답']);
  });

  it('marks 429 as rate limited', async () => {
    mockStream.mockRejectedValueOnce(new ApiError(429, '오늘 AI 대화 한도'));
    const { result } = renderHook(() => useAiChat('m1'));
    await act(async () => {
      await result.current.sendMessage('질문');
    });
    expect(result.current.rateLimited).toBe(true);
  });

  it('ignores a second question while an answer is still streaming', async () => {
    let release!: () => void;
    mockStream.mockImplementationOnce(async (_q: string, _s: string, _m: string, { onDelta }: Opts) => {
      onDelta('첫 답');
      await new Promise<void>((r) => (release = r));
      return { answer: '첫 답 끝', sources: [], session_id: 's1', saved: true };
    });
    const { result } = renderHook(() => useAiChat('m1'));
    let first!: Promise<void>;
    act(() => {
      first = result.current.sendMessage('첫 질문');
    });
    await waitFor(() => expect(result.current.streaming).toBe(true));
    await act(async () => {
      await result.current.sendMessage('빠른 질문');
    });
    expect(mockStream).toHaveBeenCalledTimes(1);
    expect(result.current.loading).toBe(true);
    await act(async () => {
      release();
      await first;
    });
    expect(result.current.messages.map((m) => m.content)).toEqual(['첫 질문', '첫 답 끝']);
    expect(result.current.loading).toBe(false);
  });

  it('aborts the running stream on new chat and ignores its late result', async () => {
    let seenSignal: AbortSignal | undefined;
    let release!: () => void;
    mockStream.mockImplementationOnce(async (_q: string, _s: string, _m: string, { signal }: Opts) => {
      seenSignal = signal;
      await new Promise<void>((r) => (release = r));
      return { answer: '늦은 답', sources: [], session_id: 'old', saved: true };
    });
    const { result } = renderHook(() => useAiChat('m1'));
    let pending!: Promise<void>;
    act(() => {
      pending = result.current.sendMessage('질문');
    });
    act(() => result.current.clearMessages());
    expect(seenSignal?.aborted).toBe(true);
    await act(async () => {
      release();
      await pending;
    });
    expect(result.current.messages).toEqual([]);
  });
});


describe('useAiChat (agent events)', () => {
  beforeEach(() => mockStream.mockReset());

  it('shows tool status, then clears a partial answer on reset', async () => {
    let release!: () => void;
    mockStream.mockImplementationOnce(async (_q: string, _s: string, _m: string, o: Opts) => {
      o.onDelta('관련 자료를 찾지');
      o.onReset?.();
      o.onStatus?.("자막 검색 중… '보안'");
      await new Promise<void>((r) => (release = r));
      o.onDelta('전자영 위원');
      return { answer: '전자영 위원입니다', sources: [], session_id: 's', saved: true };
    });
    const { result } = renderHook(() => useAiChat('m1'));
    let done!: Promise<void>;
    act(() => {
      done = result.current.sendMessage('누가 물었어?');
    });
    await waitFor(() => expect(result.current.statusText).toBe("자막 검색 중… '보안'"));
    expect(result.current.messages).toEqual([{ role: 'user', content: '누가 물었어?' }]);   // 반쪽 글은 지워졌다
    expect(result.current.streaming).toBe(false);
    await act(async () => {
      release();
      await done;
    });
    expect(result.current.messages.map((m) => m.content)).toEqual(['누가 물었어?', '전자영 위원입니다']);
    expect(result.current.statusText).toBeNull();
  });
});
