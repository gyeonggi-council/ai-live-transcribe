/**
 * 속기록 라인 API 테스트 — 낙관적 동시성 409 충돌 처리
 *
 * updateStenographyLines 가 409 응답을 ApiError(status=409)로 전달하는지 검증.
 */

import { updateStenographyLines, ApiError } from '../api';

const mockFetch = jest.fn();
global.fetch = mockFetch as unknown as typeof fetch;

describe('updateStenographyLines', () => {
  beforeEach(() => {
    mockFetch.mockClear();
  });

  it('성공 시 업데이트된 라인 목록을 반환한다', async () => {
    const mockResult = {
      updated: 1,
      items: [
        {
          id: 'L1',
          record_id: 'R1',
          sequence_no: 1,
          text: '수정된 텍스트',
          speaker: null,
          start_ms: null,
          end_ms: null,
          starts_new_paragraph: false,
          created_at: '2026-01-01T00:00:00Z',
          updated_at: '2026-01-01T00:00:00Z',
          version: 2,
        },
      ],
    };

    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => mockResult,
    });

    const result = await updateStenographyLines('M1', 'R1', [
      { id: 'L1', text: '수정된 텍스트', version: 1 },
    ]);

    expect(result.updated).toBe(1);
    expect(result.items[0]?.version).toBe(2);

    // version 이 요청 body 에 포함되는지 확인
    const calledBody = JSON.parse(
      (mockFetch.mock.calls[0][1] as RequestInit).body as string
    );
    expect(calledBody.items[0].version).toBe(1);
  });

  it('409 응답을 ApiError(status=409)로 전달한다', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 409,
      json: async () => ({
        detail: {
          message: '충돌 발생',
          conflicts: [{ id: 'L1', current: { version: 3, text: '다른 사람 수정' } }],
        },
      }),
    });

    await expect(
      updateStenographyLines('M1', 'R1', [{ id: 'L1', text: 'x', version: 1 }])
    ).rejects.toMatchObject({ status: 409 });
  });

  it('409 에러가 ApiError 인스턴스임을 확인한다', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 409,
      json: async () => ({
        detail: { message: '버전 충돌', conflicts: [{ id: 'L1' }] },
      }),
    });

    let caught: unknown;
    try {
      await updateStenographyLines('M1', 'R1', [{ id: 'L1', text: 'x', version: 1 }]);
    } catch (e) {
      caught = e;
    }

    expect(caught).toBeInstanceOf(ApiError);
    expect((caught as ApiError).status).toBe(409);
    // detail 이 객체로 파싱됨
    expect((caught as ApiError).detail).toBeDefined();
  });

  it('버전 없는 라인도 전송 가능하다 (신규 라인 / 미지원 서버)', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({ updated: 1, items: [] }),
    });

    await expect(
      updateStenographyLines('M1', 'R1', [{ id: 'L2', text: '신규' }])
    ).resolves.not.toThrow();

    const calledBody = JSON.parse(
      (mockFetch.mock.calls[0][1] as RequestInit).body as string
    );
    // version 미지정 시 undefined → JSON 직렬화 후 필드 없음 (또는 null)
    expect(calledBody.items[0]).not.toHaveProperty('version', 1);
  });

  it('409 이 아닌 다른 에러 상태(500)도 ApiError 로 전달된다', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 500,
      json: async () => ({ detail: '서버 오류' }),
    });

    await expect(
      updateStenographyLines('M1', 'R1', [{ id: 'L1', text: 'x' }])
    ).rejects.toMatchObject({ status: 500 });
  });
});
