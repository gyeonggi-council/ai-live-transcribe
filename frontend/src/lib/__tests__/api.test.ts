/**
 * API 클라이언트 테스트
 *
 * 테스트 케이스:
 * 1. 성공적인 GET 요청
 * 2. 성공적인 POST 요청
 * 3. 404 에러 처리
 * 4. 500 에러 처리
 * 5. 네트워크 에러 처리
 * 6. 기본 URL 설정 확인
 */

import { apiClient, ApiError, API_BASE_URL } from '../api';

// Mock fetch globally
const mockFetch = jest.fn();
global.fetch = mockFetch;

describe('apiClient', () => {
  beforeEach(() => {
    mockFetch.mockClear();
  });

  describe('API_BASE_URL', () => {
    it('브라우저(jsdom)에서는 same-origin(빈 문자열)으로 호출해 Next 프록시 rewrite를 탄다', () => {
      // window가 존재하는 브라우저 환경 → 상대경로('') 사용 (CORS 사전요청 회피)
      expect(API_BASE_URL).toBe('');
    });
  });

  describe('GET requests', () => {
    it('should successfully fetch data from an endpoint', async () => {
      const mockData = { id: '1', title: 'Test Meeting' };
      mockFetch.mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => mockData,
      });

      const result = await apiClient<typeof mockData>('/api/meetings/1');

      expect(mockFetch).toHaveBeenCalledWith(
        `${API_BASE_URL}/api/meetings/1`,
        expect.objectContaining({
          headers: expect.objectContaining({
            'Content-Type': 'application/json',
          }),
        })
      );
      expect(result).toEqual(mockData);
    });

    it('should handle query parameters', async () => {
      const mockData = { data: [] };
      mockFetch.mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => mockData,
      });

      await apiClient('/api/meetings?status=live&limit=5');

      expect(mockFetch).toHaveBeenCalledWith(
        `${API_BASE_URL}/api/meetings?status=live&limit=5`,
        expect.any(Object)
      );
    });
  });

  describe('POST requests', () => {
    it('should successfully send POST request with body', async () => {
      const mockData = { id: '1', title: 'New Meeting' };
      const postBody = { title: 'New Meeting', vod_url: 'https://example.com/vod.mp4' };
      mockFetch.mockResolvedValueOnce({
        ok: true,
        status: 201,
        json: async () => mockData,
      });

      const result = await apiClient<typeof mockData>('/api/meetings', {
        method: 'POST',
        body: JSON.stringify(postBody),
      });

      expect(mockFetch).toHaveBeenCalledWith(
        `${API_BASE_URL}/api/meetings`,
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify(postBody),
          headers: expect.objectContaining({
            'Content-Type': 'application/json',
          }),
        })
      );
      expect(result).toEqual(mockData);
    });
  });

  describe('Error handling', () => {
    it('should throw ApiError with status 404 when resource not found', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 404,
        json: async () => ({ error: 'Not Found', message: 'Meeting not found' }),
      });

      try {
        await apiClient('/api/meetings/999');
        fail('Expected ApiError to be thrown');
      } catch (error) {
        expect(error).toBeInstanceOf(ApiError);
        expect((error as ApiError).status).toBe(404);
      }
    });

    it('should throw ApiError with status 500 when server error occurs', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 500,
        json: async () => ({ error: 'Internal Server Error', message: 'Server error' }),
      });

      try {
        await apiClient('/api/meetings');
        fail('Expected ApiError to be thrown');
      } catch (error) {
        expect(error).toBeInstanceOf(ApiError);
        expect((error as ApiError).status).toBe(500);
      }
    });

    it('should throw Error when network request fails', async () => {
      mockFetch.mockRejectedValueOnce(new Error('Network error'));

      await expect(apiClient('/api/meetings')).rejects.toThrow('Network error');
    });

    it('should include error message from API response', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 400,
        json: async () => ({ error: 'Bad Request', message: 'Invalid status parameter' }),
      });

      try {
        await apiClient('/api/meetings?status=invalid');
      } catch (error) {
        expect(error).toBeInstanceOf(ApiError);
        expect((error as ApiError).message).toContain('Invalid status parameter');
        expect((error as ApiError).status).toBe(400);
      }
    });
  });

  describe('Headers', () => {
    it('should include default Content-Type header', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({}),
      });

      await apiClient('/api/meetings');

      expect(mockFetch).toHaveBeenCalledWith(
        expect.any(String),
        expect.objectContaining({
          headers: expect.objectContaining({
            'Content-Type': 'application/json',
          }),
        })
      );
    });

    it('should merge custom headers with defaults', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({}),
      });

      await apiClient('/api/meetings', {
        headers: {
          'X-Custom-Header': 'custom-value',
        },
      });

      expect(mockFetch).toHaveBeenCalledWith(
        expect.any(String),
        expect.objectContaining({
          headers: expect.objectContaining({
            'Content-Type': 'application/json',
            'X-Custom-Header': 'custom-value',
          }),
        })
      );
    });
  });
});
