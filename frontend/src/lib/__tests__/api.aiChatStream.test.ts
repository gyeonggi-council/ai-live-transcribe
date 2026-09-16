/**
 * aiChatStream — POST /api/ai/chat/stream 의 SSE 를 조각·최종본으로 푼다(2026-09-15).
 */
import { TextDecoder as NodeTextDecoder, TextEncoder as NodeTextEncoder } from 'util';

import { ApiError, aiChatStream, parseSseBlock } from '../api';

// jsdom 에는 TextDecoder 가 없을 수 있다
(global as unknown as { TextDecoder: unknown }).TextDecoder ??= NodeTextDecoder;
const enc = new NodeTextEncoder();

function streamResponse(chunks: string[], status = 200) {
  let i = 0;
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => ({ detail: '오늘 AI 대화 한도(10회, 접속 주소 기준)를 초과했습니다.' }),
    body: {
      getReader: () => ({
        read: async () => (i < chunks.length ? { value: enc.encode(chunks[i++]), done: false } : { value: undefined, done: true }),
      }),
    },
  };
}

describe('parseSseBlock', () => {
  it('reads event and JSON data', () => {
    expect(parseSseBlock('event: delta\ndata: {"t":"가"}')).toEqual({ event: 'delta', data: { t: '가' } });
  });
  it('ignores keepalive comments', () => {
    expect(parseSseBlock(': keepalive')).toBeNull();
  });
});

describe('aiChatStream', () => {
  afterEach(() => {
    (global.fetch as jest.Mock | undefined)?.mockReset?.();
  });

  it('delivers deltas (even split across network chunks) and returns the final answer', async () => {
    global.fetch = jest.fn().mockResolvedValue(
      streamResponse([
        'event: delta\ndata: {"t":"예산"}\n\nevent: del',
        'ta\ndata: {"t":"은 가결"}\n\n',
        'event: done\ndata: {"answer":"예산은 가결","sources":[],"session_id":"s1","saved":true}\n\n',
      ])
    ) as unknown as typeof fetch;
    const pieces: string[] = [];
    const res = await aiChatStream('q', undefined, 'm1', { onDelta: (t) => pieces.push(t) });
    expect(pieces).toEqual(['예산', '은 가결']);
    expect(res).toEqual({ answer: '예산은 가결', sources: [], session_id: 's1', saved: true });
    const [url, init] = (global.fetch as jest.Mock).mock.calls[0];
    expect(url).toContain('/api/ai/chat/stream');
    expect(JSON.parse(init.body)).toMatchObject({ question: 'q', meeting_context_id: 'm1' });
  });

  it('turns an HTTP error before the stream into ApiError with the server message', async () => {
    global.fetch = jest.fn().mockResolvedValue(streamResponse([], 429)) as unknown as typeof fetch;
    await expect(aiChatStream('q', undefined, 'm1', { onDelta: jest.fn() })).rejects.toMatchObject({
      status: 429,
      message: expect.stringContaining('한도'),
    });
  });

  it('turns a mid-stream error event into ApiError(502)', async () => {
    global.fetch = jest.fn().mockResolvedValue(
      streamResponse(['event: delta\ndata: {"t":"반"}\n\n', 'event: error\ndata: {"detail":"AI 응답이 중간에 끊겼습니다."}\n\n'])
    ) as unknown as typeof fetch;
    await expect(aiChatStream('q', undefined, 'm1', { onDelta: jest.fn() })).rejects.toBeInstanceOf(ApiError);
  });

  it('treats a stream that ends without done as an error', async () => {
    global.fetch = jest.fn().mockResolvedValue(streamResponse(['event: delta\ndata: {"t":"반"}\n\n'])) as unknown as typeof fetch;
    await expect(aiChatStream('q', undefined, 'm1', { onDelta: jest.fn() })).rejects.toMatchObject({ status: 502 });
  });
});


describe('aiChatStream agent events', () => {
  it('calls onStatus and onReset', async () => {
    global.fetch = jest.fn().mockResolvedValue(
      streamResponse([
        'event: status\ndata: {"t":"자막 검색 중…"}\n\n',
        'event: delta\ndata: {"t":"반"}\n\nevent: reset\ndata: {}\n\n',
        'event: done\ndata: {"answer":"답","sources":[],"session_id":"s","saved":true}\n\n',
      ])
    ) as unknown as typeof fetch;
    const status = jest.fn();
    const reset = jest.fn();
    await aiChatStream('q', undefined, 'm1', { onDelta: jest.fn(), onStatus: status, onReset: reset });
    expect(status).toHaveBeenCalledWith('자막 검색 중…');
    expect(reset).toHaveBeenCalledTimes(1);
  });
});
