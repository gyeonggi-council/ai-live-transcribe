/**
 * 전자회의록 마크다운 미리보기/편집 API 테스트
 *
 * getMinutesMarkdown, downloadHwpxFromMarkdown, downloadHwpx 가
 * 올바른 URL·Authorization 헤더·POST body 로 호출되고 에러를
 * ApiError 로 전달하는지 검증한다.
 */

import {
  ApiError,
  downloadHwpx,
  downloadHwpxFromMarkdown,
  getMinutesMarkdown,
} from '../api';

const mockFetch = jest.fn();
global.fetch = mockFetch as unknown as typeof fetch;

// jsdom 에는 Blob URL API 가 없으므로 모킹
const mockCreateObjectURL = jest.fn(() => 'blob:mock-url');
const mockRevokeObjectURL = jest.fn();
(URL as unknown as { createObjectURL: unknown }).createObjectURL = mockCreateObjectURL;
(URL as unknown as { revokeObjectURL: unknown }).revokeObjectURL = mockRevokeObjectURL;

/** 다운로드용 blob 응답 모킹 (RFC5987 filename* 포함 가능) */
function mockBlobResponse(disposition: string) {
  return {
    ok: true,
    status: 200,
    blob: async () => new Blob(['hwpx-data']),
    headers: {
      get: (name: string) => (name === 'Content-Disposition' ? disposition : null),
    },
  };
}

describe('minutes preview API', () => {
  let clickSpy: jest.Mock;
  let createElementSpy: jest.SpyInstance;
  let anchors: HTMLAnchorElement[];

  beforeEach(() => {
    mockFetch.mockReset();
    mockCreateObjectURL.mockClear();
    mockRevokeObjectURL.mockClear();
    localStorage.clear();
    anchors = [];

    // 앵커 click 은 jsdom 내비게이션 미지원이므로 무력화 + 파일명 검증용 캡처
    clickSpy = jest.fn();
    const realCreateElement = document.createElement.bind(document);
    createElementSpy = jest
      .spyOn(document, 'createElement')
      .mockImplementation((tag: string) => {
        const el = realCreateElement(tag);
        if (tag === 'a') {
          (el as HTMLAnchorElement).click = clickSpy as unknown as () => void;
          anchors.push(el as HTMLAnchorElement);
        }
        return el;
      });
  });

  afterEach(() => {
    createElementSpy.mockRestore();
  });

  describe('getMinutesMarkdown', () => {
    it('올바른 URL 로 GET 하고 markdown/kordoc_available 을 반환한다', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ markdown: '# 회의록', kordoc_available: true }),
      });

      const result = await getMinutesMarkdown('M1');

      expect(mockFetch.mock.calls[0][0]).toBe('/api/meetings/M1/minutes-markdown');
      expect(result).toEqual({ markdown: '# 회의록', kordoc_available: true });
    });

    it('토큰이 있으면 Authorization 헤더를 첨부한다', async () => {
      localStorage.setItem('auth_token', 'test-token');
      mockFetch.mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ markdown: '', kordoc_available: false }),
      });

      await getMinutesMarkdown('M1');

      const options = mockFetch.mock.calls[0][1] as RequestInit;
      expect(options.headers).toMatchObject({ Authorization: 'Bearer test-token' });
    });

    it('401(로그인 필요)을 ApiError 로 전파한다', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 401,
        json: async () => ({ detail: '로그인이 필요합니다.' }),
      });

      await expect(getMinutesMarkdown('M1')).rejects.toMatchObject({
        status: 401,
        message: '로그인이 필요합니다.',
      });
    });

    it('409(자막 없음)를 ApiError 로 전파한다', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 409,
        json: async () => ({ detail: '자막이 없어 회의록 마크다운을 만들 수 없습니다.' }),
      });

      let caught: unknown;
      try {
        await getMinutesMarkdown('M1');
      } catch (e) {
        caught = e;
      }

      expect(caught).toBeInstanceOf(ApiError);
      expect((caught as ApiError).status).toBe(409);
    });
  });

  describe('downloadHwpxFromMarkdown', () => {
    it('markdown 을 JSON body 로 POST 하고 Authorization 헤더를 첨부한다', async () => {
      localStorage.setItem('auth_token', 'test-token');
      mockFetch.mockResolvedValueOnce(
        mockBlobResponse(
          "attachment; filename*=UTF-8''%ED%9A%8C%EC%9D%98%EB%A1%9D_edited.hwpx"
        )
      );

      await downloadHwpxFromMarkdown('M1', '# 수정된 회의록');

      expect(mockFetch.mock.calls[0][0]).toBe(
        '/api/meetings/M1/export/hwpx-from-markdown'
      );
      const options = mockFetch.mock.calls[0][1] as RequestInit;
      expect(options.method).toBe('POST');
      expect(options.headers).toMatchObject({
        'Content-Type': 'application/json',
        Authorization: 'Bearer test-token',
      });
      expect(JSON.parse(options.body as string)).toEqual({
        markdown: '# 수정된 회의록',
      });

      // blob 다운로드 트리거 + RFC5987 파일명 디코딩
      expect(mockCreateObjectURL).toHaveBeenCalled();
      expect(clickSpy).toHaveBeenCalled();
      expect(mockRevokeObjectURL).toHaveBeenCalled();
      expect(anchors[0]?.download).toBe('회의록_edited.hwpx');
    });

    it('503(kordoc 불가)을 ApiError 로 던진다', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 503,
        json: async () => ({ detail: 'kordoc 엔진을 사용할 수 없습니다' }),
      });

      let caught: unknown;
      try {
        await downloadHwpxFromMarkdown('M1', '# md');
      } catch (e) {
        caught = e;
      }

      expect(caught).toBeInstanceOf(ApiError);
      expect((caught as ApiError).status).toBe(503);
      expect((caught as ApiError).message).toBe('kordoc 엔진을 사용할 수 없습니다');
    });
  });

  describe('downloadHwpx', () => {
    it('기본은 native 엔진 쿼리로 요청한다', async () => {
      mockFetch.mockResolvedValueOnce(
        mockBlobResponse('attachment; filename="minutes.hwpx"')
      );

      await downloadHwpx('M1');

      expect(mockFetch.mock.calls[0][0]).toBe(
        '/api/meetings/M1/export?format=hwpx&engine=native'
      );
      expect(clickSpy).toHaveBeenCalled();
    });

    it('kordoc 엔진 지정 시 engine=kordoc 쿼리와 Authorization 을 첨부한다', async () => {
      localStorage.setItem('auth_token', 'test-token');
      mockFetch.mockResolvedValueOnce(
        mockBlobResponse('attachment; filename="minutes.hwpx"')
      );

      await downloadHwpx('M1', 'kordoc');

      expect(mockFetch.mock.calls[0][0]).toBe(
        '/api/meetings/M1/export?format=hwpx&engine=kordoc'
      );
      const options = mockFetch.mock.calls[0][1] as RequestInit;
      expect(options.headers).toMatchObject({ Authorization: 'Bearer test-token' });
    });

    it('에러 응답을 ApiError 로 던진다', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 404,
        json: async () => ({ detail: '회의를 찾을 수 없습니다.' }),
      });

      await expect(downloadHwpx('M1')).rejects.toMatchObject({ status: 404 });
    });
  });
});
