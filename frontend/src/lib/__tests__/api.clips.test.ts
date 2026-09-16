/**
 * 발언영상 추출(clips) API 테스트 — URL / Authorization / 에러 처리
 *
 * getSpeakerSegments, downloadSpeechClip, createClipJob, getClipJob,
 * downloadClipJobResult 가 올바른 URL·헤더로 호출되고 에러를 ApiError 로
 * 전달하는지 검증한다.
 */

import {
  ApiError,
  createClipJob,
  downloadClipJobResult,
  downloadSpeechClip,
  getClipJob,
  getSpeakerSegments,
} from '../api';

const mockFetch = jest.fn();
global.fetch = mockFetch as unknown as typeof fetch;

// jsdom 에는 Blob URL API 가 없으므로 모킹
const mockCreateObjectURL = jest.fn(() => 'blob:mock-url');
const mockRevokeObjectURL = jest.fn();
(URL as unknown as { createObjectURL: unknown }).createObjectURL = mockCreateObjectURL;
(URL as unknown as { revokeObjectURL: unknown }).revokeObjectURL = mockRevokeObjectURL;

/** 다운로드용 blob 응답 모킹 */
function mockBlobResponse(filename: string) {
  return {
    ok: true,
    status: 200,
    blob: async () => new Blob(['clip-data']),
    headers: {
      get: (name: string) =>
        name === 'Content-Disposition' ? `attachment; filename="${filename}"` : null,
    },
  };
}

describe('clips API', () => {
  let clickSpy: jest.Mock;
  let createElementSpy: jest.SpyInstance;

  beforeEach(() => {
    mockFetch.mockReset();
    mockCreateObjectURL.mockClear();
    mockRevokeObjectURL.mockClear();
    localStorage.clear();

    // 앵커 click 은 jsdom 내비게이션 미지원이므로 무력화
    clickSpy = jest.fn();
    const realCreateElement = document.createElement.bind(document);
    createElementSpy = jest
      .spyOn(document, 'createElement')
      .mockImplementation((tag: string) => {
        const el = realCreateElement(tag);
        if (tag === 'a') {
          (el as HTMLAnchorElement).click = clickSpy as unknown as () => void;
        }
        return el;
      });
  });

  afterEach(() => {
    createElementSpy.mockRestore();
  });

  describe('getSpeakerSegments', () => {
    it('올바른 URL 로 GET 요청한다', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({
          meeting_id: 'M1',
          kms_midx: null,
          title: '테스트 회의',
          total_duration: 3600,
          speakers: [],
        }),
      });

      const result = await getSpeakerSegments('M1');

      expect(mockFetch.mock.calls[0][0]).toBe('/api/meetings/M1/speakers/segments');
      expect(result.meeting_id).toBe('M1');
      expect(result.speakers).toEqual([]);
    });

    it('토큰이 있으면 Authorization 헤더를 첨부한다', async () => {
      localStorage.setItem('auth_token', 'test-token');
      mockFetch.mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ meeting_id: 'M1', kms_midx: null, title: '', total_duration: 0, speakers: [] }),
      });

      await getSpeakerSegments('M1');

      const options = mockFetch.mock.calls[0][1] as RequestInit;
      expect(options.headers).toMatchObject({ Authorization: 'Bearer test-token' });
    });

    it('에러 응답을 ApiError 로 전달한다', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 500,
        json: async () => ({ detail: '서버 오류' }),
      });

      await expect(getSpeakerSegments('M1')).rejects.toMatchObject({ status: 500 });
    });
  });

  describe('downloadSpeechClip', () => {
    it('start/end 쿼리와 Authorization 헤더로 요청하고 blob 을 다운로드한다', async () => {
      localStorage.setItem('auth_token', 'test-token');
      mockFetch.mockResolvedValueOnce(mockBlobResponse('clip_8-32.mp4'));

      await downloadSpeechClip('M1', 8, 32);

      expect(mockFetch).toHaveBeenCalledWith('/api/meetings/M1/speakers/clip?start=8&end=32', {
        headers: { Authorization: 'Bearer test-token' },
      });
      expect(mockCreateObjectURL).toHaveBeenCalled();
      expect(clickSpy).toHaveBeenCalled();
      expect(mockRevokeObjectURL).toHaveBeenCalled();
    });

    it('에러 응답(409)을 ApiError 로 던진다', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 409,
        json: async () => ({ detail: '자막이 없습니다' }),
      });

      let caught: unknown;
      try {
        await downloadSpeechClip('M1', 0, 10);
      } catch (e) {
        caught = e;
      }

      expect(caught).toBeInstanceOf(ApiError);
      expect((caught as ApiError).status).toBe(409);
      expect((caught as ApiError).message).toBe('자막이 없습니다');
    });
  });

  describe('createClipJob', () => {
    it('segments 와 merge:true 를 POST 한다', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ job_id: 'J1' }),
      });

      const result = await createClipJob('M1', [
        { start: 8, end: 32 },
        { start: 48, end: 67 },
      ]);

      expect(mockFetch.mock.calls[0][0]).toBe('/api/meetings/M1/speakers/clip-jobs');
      const options = mockFetch.mock.calls[0][1] as RequestInit;
      expect(options.method).toBe('POST');
      expect(JSON.parse(options.body as string)).toEqual({
        segments: [
          { start: 8, end: 32 },
          { start: 48, end: 67 },
        ],
        merge: true,
      });
      expect(result.job_id).toBe('J1');
    });
  });

  describe('getClipJob', () => {
    it('작업 상태를 올바른 URL 로 조회한다', async () => {
      const mockStatus = {
        status: 'running',
        progress: 0.4,
        current_segment: 1,
        error: null,
        filename: null,
      };
      mockFetch.mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => mockStatus,
      });

      const result = await getClipJob('M1', 'J1');

      expect(mockFetch.mock.calls[0][0]).toBe('/api/meetings/M1/speakers/clip-jobs/J1');
      expect(result).toEqual(mockStatus);
    });
  });

  describe('downloadClipJobResult', () => {
    it('결과 파일(blob)을 다운로드한다', async () => {
      localStorage.setItem('auth_token', 'test-token');
      mockFetch.mockResolvedValueOnce(mockBlobResponse('merged.mp4'));

      await downloadClipJobResult('M1', 'J1');

      expect(mockFetch).toHaveBeenCalledWith('/api/meetings/M1/speakers/clip-jobs/J1/download', {
        headers: { Authorization: 'Bearer test-token' },
      });
      expect(mockCreateObjectURL).toHaveBeenCalled();
      expect(clickSpy).toHaveBeenCalled();
    });

    it('에러 응답을 ApiError 로 던진다', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 404,
        json: async () => ({ detail: '작업 결과가 없습니다' }),
      });

      await expect(downloadClipJobResult('M1', 'J1')).rejects.toMatchObject({ status: 404 });
    });
  });
});
