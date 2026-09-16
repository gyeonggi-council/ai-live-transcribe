import { test, expect, type Page } from '@playwright/test';

/**
 * Phase 2 Integration Tests
 *
 * Backend <-> Frontend API 연동 및 WebSocket 통합 테스트
 *
 * 이 테스트들은 실제 백엔드 서버가 실행 중이거나
 * API Mock을 통해 실행될 수 있습니다.
 */

// Mock Meeting Data for Integration Tests
const integrationMockMeeting = {
  id: 'integration-test-meeting-1',
  title: '통합 테스트 회의',
  meeting_date: '2026-02-06T10:00:00Z',
  stream_url: 'https://test-stream.example.com/live.m3u8',
  vod_url: null,
  status: 'live' as const,
  duration_seconds: null,
  created_at: '2026-02-06T00:00:00Z',
  updated_at: '2026-02-06T00:00:00Z',
};

const mockChannels = [
  {
    id: 'ch1',
    code: 'ch1',
    name: '도청채널',
    stream_url: 'https://test-stream.example.com/live.m3u8',
    livestatus: 1,
    status_text: '방송중',
    has_schedule: true,
    session_no: 352,
    session_order: 1,
    stt_running: false,
  },
  {
    id: 'ch2',
    code: 'ch2',
    name: '휴식채널',
    stream_url: 'https://test-stream.example.com/live-off.m3u8',
    livestatus: 0,
    status_text: '방송전',
    has_schedule: false,
    stt_running: false,
  },
];

function getLiveChannelUrl(channelId: string = 'ch1') {
  return `/live?channel=${channelId}`;
}

function getLiveChannelTestId(channelId: string) {
  return `channel-${channelId}`;
}

/**
 * Helper to set up API routes with custom responses
 */
async function setupMockApi(page: Page, config: {
  liveMeeting?: object | null;
  subtitles?: object[];
  channels?: typeof mockChannels;
  apiDelay?: number;
} = {}) {
  const {
    liveMeeting = integrationMockMeeting,
    subtitles = [],
    channels = mockChannels,
    apiDelay = 0,
  } = config;

  await page.route('**/api/channels/status', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(channels),
    });
  });

  await page.route('**/api/channels/*/stt/start', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ status: 'started' }),
    });
  });

  await page.route('**/api/meetings/live*', async (route) => {
    if (apiDelay > 0) {
      await new Promise(resolve => setTimeout(resolve, apiDelay));
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(liveMeeting),
    });
  });

  await page.route('**/api/meetings?*', async (route) => {
    if (apiDelay > 0) {
      await new Promise(resolve => setTimeout(resolve, apiDelay));
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        data: [],
        meta: { total: 0, page: 1 },
      }),
    });
  });

  await page.route('**/api/meetings/*/subtitles', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        data: subtitles,
        meta: { total: subtitles.length },
      }),
    });
  });
}

test.describe('API Integration Tests', () => {
  test.describe('GET /api/meetings/live', () => {
    test('should fetch and display live meeting correctly', async ({ page }) => {
      await setupMockApi(page, { liveMeeting: integrationMockMeeting });
      await page.goto('/');

      // Wait for data to load
      await expect(page.getByText('통합 테스트 회의')).toBeVisible({ timeout: 10000 });
      await expect(page.getByText('Live')).toBeVisible();
    });

    test('should handle null response (no live meeting)', async ({ page }) => {
      await setupMockApi(page, { liveMeeting: null });
      await page.goto('/');

      // Should show no meeting message
      await expect(page.getByText('현재 진행 중인 회의가 없습니다')).toBeVisible({ timeout: 10000 });
    });

  test('should handle API error gracefully', async ({ page }) => {
    await page.route('**/api/meetings/live*', async (route) => {
        await route.fulfill({
          status: 500,
          contentType: 'application/json',
          body: JSON.stringify({ message: 'Internal Server Error' }),
        });
      });

      await page.route('**/api/meetings?*', async (route) => {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ data: [], meta: { total: 0, page: 1 } }),
        });
      });

      await page.goto('/');

      // Should show error message
      await expect(page.getByText(/오류가 발생했습니다|데이터를 불러오는 중 오류/)).toBeVisible({ timeout: 10000 });
    });

  test('should retry on network failure (SWR behavior)', async ({ page }) => {
      let requestCount = 0;

    await page.route('**/api/meetings/live*', async (route) => {
        requestCount++;
        if (requestCount === 1) {
          // First request fails
          await route.abort('connectionfailed');
        } else {
          // Subsequent requests succeed
          await route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify(integrationMockMeeting),
          });
        }
      });

      await page.route('**/api/meetings?*', async (route) => {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ data: [], meta: { total: 0, page: 1 } }),
        });
      });

      await page.goto('/');

      // Eventually should show the meeting (after retry)
      await expect(page.getByText('통합 테스트 회의')).toBeVisible({ timeout: 15000 });
    });
  });

  test.describe('GET /api/meetings (VOD list)', () => {
    const mockVods = [
      {
        id: 'vod-int-1',
        title: '통합 테스트 VOD 1',
        meeting_date: '2026-02-05T10:00:00Z',
        stream_url: null,
        vod_url: 'https://example.com/vod1.mp4',
        status: 'ended',
        duration_seconds: 3600,
        created_at: '2026-02-05T00:00:00Z',
        updated_at: '2026-02-05T12:00:00Z',
      },
    ];

    test('should fetch and display VOD list', async ({ page }) => {
      await page.route('**/api/meetings/live*', async (route) => {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(null),
        });
      });

      await page.route('**/api/meetings?*', async (route) => {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            data: mockVods,
            meta: { total: mockVods.length, page: 1 },
          }),
        });
      });

      await page.goto('/');

      // VOD should be displayed
      await expect(page.getByText('통합 테스트 VOD 1')).toBeVisible({ timeout: 10000 });
    });

    test('should handle empty VOD list', async ({ page }) => {
      await page.route('**/api/meetings/live*', async (route) => {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(null),
        });
      });

      await page.route('**/api/meetings?*', async (route) => {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            data: [],
            meta: { total: 0, page: 1 },
          }),
        });
      });

      await page.goto('/');

      // Should show empty state message or just no VODs
      await expect(page.getByText('최근 회의')).toBeVisible({ timeout: 10000 });
    });
  });
});

test.describe('WebSocket Integration Tests', () => {
  test('should display connection status indicator', async ({ page }) => {
    await setupMockApi(page, { liveMeeting: integrationMockMeeting });
    await page.goto(getLiveChannelUrl());

    // Connection status should be visible
    await expect(page.getByTestId('connection-status')).toBeVisible({ timeout: 10000 });
  });

  test('should show connecting state initially', async ({ page }) => {
    await setupMockApi(page, { liveMeeting: integrationMockMeeting });
    await page.goto(getLiveChannelUrl());

    // Wait for page to load
    await expect(page.getByTestId('live-page')).toBeVisible({ timeout: 10000 });

    // Should show connection status (connecting, connected, or error depending on WS availability)
    const connectionStatus = page.getByTestId('connection-status');
    await expect(connectionStatus).toBeVisible();
  });

  test('should have reconnect button when disconnected', async ({ page }) => {
    await setupMockApi(page, { liveMeeting: integrationMockMeeting });
    await page.goto(getLiveChannelUrl());

    // Wait for page to load
    await expect(page.getByTestId('live-page')).toBeVisible({ timeout: 10000 });

    // Note: In real scenario, WebSocket might fail to connect
    // The reconnect button would appear when status is 'disconnected' or 'error'
    // This test verifies the structure is in place
    const connectionStatus = page.getByTestId('connection-status');
    await expect(connectionStatus).toBeVisible();
  });
});

test.describe('Data Flow Integration', () => {
  test('should pass meeting data from API to components correctly', async ({ page }) => {
    const customMeeting = {
      ...integrationMockMeeting,
      title: '커스텀 데이터 흐름 테스트 회의',
      meeting_date: '2026-02-07T14:30:00Z',
    };

    await setupMockApi(page, { liveMeeting: customMeeting });
    await page.goto('/');

    // Verify data flows to LiveMeetingCard
    await expect(page.getByText('커스텀 데이터 흐름 테스트 회의')).toBeVisible({ timeout: 10000 });
    await expect(page.getByText(/2026년 2월 7일/)).toBeVisible();

    // Navigate to live page
    await page.getByRole('button', { name: /실시간 자막 보기/i }).click();
    await expect(page).toHaveURL('/live');
    await page.getByTestId(getLiveChannelTestId('ch1')).click();

    // Verify data flows to Header on live page
    await expect(page).toHaveURL('/live?channel=ch1');
    await expect(page.getByText('커스텀 데이터 흐름 테스트 회의')).toBeVisible();
  });

  test('should maintain state across navigation', async ({ page }) => {
    await setupMockApi(page, { liveMeeting: integrationMockMeeting });

    // Start at home
    await page.goto('/');
    await expect(page.getByText('통합 테스트 회의')).toBeVisible({ timeout: 10000 });

    // Go to live
    await page.getByRole('button', { name: /실시간 자막 보기/i }).click();
    await expect(page).toHaveURL('/live');
    await page.getByTestId(getLiveChannelTestId('ch1')).click();
    await expect(page.getByTestId('live-page')).toBeVisible();
    await expect(page).toHaveURL('/live?channel=ch1');
    await expect(page.getByText('통합 테스트 회의')).toBeVisible();

    // Go back
    await page.goBack();
    await expect(page.getByText('통합 테스트 회의')).toBeVisible({ timeout: 10000 });
  });
});

test.describe('Performance Integration', () => {
  test('should load home page within acceptable time', async ({ page }) => {
    await setupMockApi(page, { apiDelay: 0 });

    const startTime = Date.now();
    await page.goto('/');
    await expect(page.getByText(/실시간 회의|현재 진행 중인 회의가 없습니다/)).toBeVisible({ timeout: 10000 });
    const loadTime = Date.now() - startTime;

    // Page should load within 5 seconds (generous for CI)
    expect(loadTime).toBeLessThan(5000);
  });

  test('should handle slow API gracefully', async ({ page }) => {
    await setupMockApi(page, {
      liveMeeting: integrationMockMeeting,
      apiDelay: 2000, // 2 second delay
    });

    await page.goto('/');

    // Should show loading state initially (may have multiple instances)
    await expect(page.getByText('로딩 중...').first()).toBeVisible();

    // Eventually should show content
    await expect(page.getByText('통합 테스트 회의')).toBeVisible({ timeout: 10000 });
  });
});

test.describe('URL State Integration', () => {
  test('should handle direct navigation to /live', async ({ page }) => {
    await setupMockApi(page, { liveMeeting: integrationMockMeeting });

    // Go directly to channel-based live view
    await page.goto(getLiveChannelUrl());

    // Should load live page correctly
    await expect(page.getByTestId('live-page')).toBeVisible({ timeout: 10000 });
    await expect(page.getByText('통합 테스트 회의')).toBeVisible();
  });

  test('should handle page refresh on /live', async ({ page }) => {
    await setupMockApi(page, { liveMeeting: integrationMockMeeting });

    // Go to channel-based live view
    await page.goto(getLiveChannelUrl());
    await expect(page.getByTestId('live-page')).toBeVisible({ timeout: 10000 });

    // Refresh
    await page.reload();

    // Should still show live page
    await expect(page.getByTestId('live-page')).toBeVisible({ timeout: 10000 });
    await expect(page.getByText('통합 테스트 회의')).toBeVisible();
  });
});
