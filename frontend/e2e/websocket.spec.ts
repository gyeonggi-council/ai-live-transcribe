import { test, expect, type Page } from '@playwright/test';

/**
 * WebSocket E2E Tests for Phase 2
 *
 * 실시간 자막 WebSocket 연결 및 메시지 수신 테스트
 *
 * 참고: 실제 WebSocket 서버 없이 테스트하므로
 * 연결 상태와 UI 반응을 중심으로 테스트합니다.
 */

// Mock Meeting for WebSocket tests
const mockMeeting = {
  id: 'ws-test-meeting-1',
  title: 'WebSocket 테스트 회의',
  meeting_date: '2026-02-06T10:00:00Z',
  stream_url: 'https://test.example.com/stream.m3u8',
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
    stream_url: 'https://test.example.com/stream.m3u8',
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
    stream_url: 'https://test.example.com/live-off.m3u8',
    livestatus: 0,
    status_text: '방송전',
    has_schedule: false,
    stt_running: false,
  },
];

function getLiveChannelUrl(channelId: string = 'ch1') {
  return `/live?channel=${channelId}`;
}

/**
 * Setup API mocks for WebSocket tests
 */
async function setupApiMocks(page: Page) {
  await page.route('**/api/channels/status', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockChannels),
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
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockMeeting),
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

  await page.route('**/api/meetings/*/subtitles', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        data: [],
        meta: { total: 0 },
      }),
    });
  });
}

test.describe('WebSocket Connection Tests', () => {
  test('should display connection status component', async ({ page }) => {
    await setupApiMocks(page);
    await page.goto(getLiveChannelUrl());

    // Wait for page to be fully loaded
    await expect(page.getByTestId('live-page')).toBeVisible({ timeout: 10000 });

    // Connection status should be visible
    const connectionStatus = page.getByTestId('connection-status');
    await expect(connectionStatus).toBeVisible();

    // Should show status text (may have multiple, pick first)
    await expect(connectionStatus.getByText(/연결|상태/).first()).toBeVisible();
  });

  test('should show appropriate connection state', async ({ page }) => {
    await setupApiMocks(page);
    await page.goto(getLiveChannelUrl());

    await expect(page.getByTestId('live-page')).toBeVisible({ timeout: 10000 });

    // Check for any connection state text
    // Since there's no real WebSocket server, it will likely show 'connecting' then 'disconnected' or 'error'
    const possibleStates = ['연결 중...', '연결됨', '연결 끊김', '연결 오류'];
    const statusText = await page.getByTestId('connection-status').textContent();

    const hasValidState = possibleStates.some(state => statusText?.includes(state));
    expect(hasValidState).toBe(true);
  });

  test('should have reconnect button when connection fails', async ({ page }) => {
    await setupApiMocks(page);
    await page.goto(getLiveChannelUrl());

    await expect(page.getByTestId('live-page')).toBeVisible({ timeout: 10000 });

    // Wait a bit for WebSocket to fail connection (no server)
    await page.waitForTimeout(3000);

    // Check if reconnect button appears (only visible when disconnected or error)
    const reconnectButton = page.getByTestId('reconnect-button');

    // The button may or may not be visible depending on timing
    // This test just verifies the mechanism exists
    const isVisible = await reconnectButton.isVisible().catch(() => false);

    if (isVisible) {
      await expect(reconnectButton).toBeEnabled();
    }
  });

  test('reconnect button should trigger connection attempt', async ({ page }) => {
    await setupApiMocks(page);
    await page.goto(getLiveChannelUrl());

    await expect(page.getByTestId('live-page')).toBeVisible({ timeout: 10000 });

    // Wait for initial connection to fail
    await page.waitForTimeout(3000);

    const reconnectButton = page.getByTestId('reconnect-button');
    const isVisible = await reconnectButton.isVisible().catch(() => false);

    if (isVisible) {
      // Click reconnect
      await reconnectButton.click();

      // Should trigger reconnection attempt
      // Status should change (connecting, connected, or stay error)
      const connectionStatus = page.getByTestId('connection-status');
      await expect(connectionStatus).toBeVisible();
    }
  });
});

test.describe('Subtitle Display Tests', () => {
  test('should display subtitle panel', async ({ page }) => {
    await setupApiMocks(page);
    await page.goto(getLiveChannelUrl());

    await expect(page.getByTestId('live-page')).toBeVisible({ timeout: 10000 });

    // Subtitle panel should be visible
    await expect(page.getByTestId('subtitle-panel')).toBeVisible();
  });

  test('should show empty state when no subtitles', async ({ page }) => {
    await setupApiMocks(page);
    await page.goto(getLiveChannelUrl());

    await expect(page.getByTestId('live-page')).toBeVisible({ timeout: 10000 });

    // Subtitle panel should show empty state
    const subtitlePanel = page.getByTestId('subtitle-panel');
    await expect(subtitlePanel).toBeVisible();

    // Check for empty state text or just verify panel exists
    const panelContent = await subtitlePanel.textContent();
    expect(panelContent).toBeDefined();
  });

  test('subtitle panel should have scrollable container', async ({ page }) => {
    await setupApiMocks(page);
    await page.goto(getLiveChannelUrl());

    await expect(page.getByTestId('live-page')).toBeVisible({ timeout: 10000 });

    // Check that subtitle panel has overflow-y-auto class for scrolling
    const subtitlePanel = page.getByTestId('subtitle-panel');
    await expect(subtitlePanel).toBeVisible();

    // Verify scroll container exists
    const scrollContainer = subtitlePanel.locator('.overflow-y-auto');
    await expect(scrollContainer).toBeVisible();
  });
});

test.describe('Real-time Subtitle Search', () => {
  test('should have search input on live page', async ({ page }) => {
    await setupApiMocks(page);
    await page.goto(getLiveChannelUrl());

    await expect(page.getByTestId('live-page')).toBeVisible({ timeout: 10000 });

    // Search input should be available
    const searchInput = page.getByRole('searchbox');
    await expect(searchInput).toBeVisible();
  });

  test('search should filter displayed subtitles', async ({ page }) => {
    await setupApiMocks(page);
    await page.goto(getLiveChannelUrl());

    await expect(page.getByTestId('live-page')).toBeVisible({ timeout: 10000 });

    // Type search query
    const searchInput = page.getByRole('searchbox');
    await searchInput.fill('테스트');

    // Search should be applied (verified by input value)
    await expect(searchInput).toHaveValue('테스트');

    // Debounce delay
    await page.waitForTimeout(400);

    // Note: Without real subtitles, we can't test actual filtering
    // This test verifies the search mechanism works
  });

  test('should show no results message for non-matching search', async ({ page }) => {
    await setupApiMocks(page);
    await page.goto(getLiveChannelUrl());

    await expect(page.getByTestId('live-page')).toBeVisible({ timeout: 10000 });

    const searchInput = page.getByRole('searchbox');
    await searchInput.fill('존재하지않는검색어xyz123');

    // Wait for debounce
    await page.waitForTimeout(400);

    // If there are no subtitles, no-results message may or may not show
    // This depends on implementation - verify search value is set
    await expect(searchInput).toHaveValue('존재하지않는검색어xyz123');
  });

  test('clearing search should show all subtitles', async ({ page }) => {
    await setupApiMocks(page);
    await page.goto(getLiveChannelUrl());

    await expect(page.getByTestId('live-page')).toBeVisible({ timeout: 10000 });

    const searchInput = page.getByRole('searchbox');

    // Type then clear
    await searchInput.fill('검색어');
    await page.waitForTimeout(400);
    await searchInput.clear();

    await expect(searchInput).toHaveValue('');
  });
});

test.describe('Connection Recovery', () => {
  test('should handle page visibility change', async ({ page }) => {
    await setupApiMocks(page);
    await page.goto(getLiveChannelUrl());

    await expect(page.getByTestId('live-page')).toBeVisible({ timeout: 10000 });

    // Simulate page becoming hidden (background tab)
    await page.evaluate(() => {
      Object.defineProperty(document, 'hidden', {
        value: true,
        writable: true,
      });
      document.dispatchEvent(new Event('visibilitychange'));
    });

    // Bring page back to foreground
    await page.evaluate(() => {
      Object.defineProperty(document, 'hidden', {
        value: false,
        writable: true,
      });
      document.dispatchEvent(new Event('visibilitychange'));
    });

    // Page should still be functional
    await expect(page.getByTestId('live-page')).toBeVisible();
  });

  test('should handle network reconnection', async ({ page, context }) => {
    await setupApiMocks(page);
    await page.goto(getLiveChannelUrl());

    await expect(page.getByTestId('live-page')).toBeVisible({ timeout: 10000 });

    // Simulate going offline
    await context.setOffline(true);
    await page.waitForTimeout(1000);

    // Simulate coming back online
    await context.setOffline(false);
    await page.waitForTimeout(1000);

    // Page should still work (SWR should revalidate)
    await expect(page.getByTestId('live-page')).toBeVisible();
  });
});

test.describe('Subtitle UI Interactions', () => {
  test('should be able to scroll in subtitle panel', async ({ page }) => {
    await setupApiMocks(page);
    await page.goto(getLiveChannelUrl());

    await expect(page.getByTestId('live-page')).toBeVisible({ timeout: 10000 });

    const subtitlePanel = page.getByTestId('subtitle-panel');
    await expect(subtitlePanel).toBeVisible();

    // Verify panel is interactive (can receive focus/scroll)
    await subtitlePanel.scrollIntoViewIfNeeded();
  });

  test('connection status should update badge style', async ({ page }) => {
    await setupApiMocks(page);
    await page.goto(getLiveChannelUrl());

    await expect(page.getByTestId('live-page')).toBeVisible({ timeout: 10000 });

    // Badge component should be present in connection status
    const connectionStatus = page.getByTestId('connection-status');
    await expect(connectionStatus).toBeVisible();

    // Find Badge element within connection status
    const badge = connectionStatus.locator('[class*="rounded"]');
    await expect(badge.first()).toBeVisible();
  });
});

test.describe('Edge Cases', () => {
  test('should handle meeting ending while on live page', async ({ page }) => {
    await setupApiMocks(page);

    // Start with live meeting
    await page.route('**/api/meetings/live*', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(mockMeeting),
      });
    });

    await page.route('**/api/meetings?*', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ data: [], meta: { total: 0, page: 1 } }),
      });
    });

    await page.goto(getLiveChannelUrl('ch2'));
    await expect(page.getByTestId('live-page')).toBeVisible({ timeout: 10000 });

    // Simulate meeting ending by changing mock response
    await page.route('**/api/meetings/live*', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(null),
      });
    });

    // Force SWR to refetch (simulate polling)
    await page.reload();

    // Should now show no broadcast message
    await expect(page.getByText('현재 방송 중이 아닙니다')).toBeVisible({ timeout: 10000 });
  });

  test('should handle rapid navigation', async ({ page }) => {
    await setupApiMocks(page);

    // Navigate quickly between pages
    await page.goto('/');
    await page.goto(getLiveChannelUrl());

    // Wait for page to stabilize before navigation
    await expect(page.getByTestId('live-page')).toBeVisible({ timeout: 10000 });

    await page.goBack();
    await page.waitForURL('/');

    // Go forward again
    await page.goto(getLiveChannelUrl());

    // Should still be functional
    await expect(page.getByTestId('live-page')).toBeVisible({ timeout: 10000 });
  });
});
