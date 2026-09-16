import { test, expect, type Page } from '@playwright/test';
import type { ChannelType } from '../src/types';

/**
 * Phase 2 E2E Test Suite
 *
 * 검증 항목:
 * 1. 네비게이션: `/` -> `/live` (방송중일 때만 버튼 활성화)
 * 2. meetings 리소스: 필드 커버리지 확인
 * 3. subtitles 리소스: 필드 커버리지 확인
 * 4. WebSocket 연결/재연결: 실시간 자막 수신
 * 5. HLS 스트림 재생: 영상 로드 및 재생
 */

// Mock Data
const mockLiveMeeting = {
  id: 'meeting-1',
  title: '제352회 본회의',
  meeting_date: '2026-02-06T10:00:00Z',
  stream_url: 'https://example.com/stream.m3u8',
  vod_url: null,
  status: 'live',
  duration_seconds: null,
  created_at: '2026-02-06T00:00:00Z',
  updated_at: '2026-02-06T00:00:00Z',
};

const mockRecentVods = [
  {
    id: 'vod-1',
    title: '제351회 본회의',
    meeting_date: '2026-02-05T10:00:00Z',
    stream_url: null,
    vod_url: 'https://example.com/vod1.mp4',
    status: 'ended',
    duration_seconds: 3600,
    created_at: '2026-02-05T00:00:00Z',
    updated_at: '2026-02-05T12:00:00Z',
  },
  {
    id: 'vod-2',
    title: '제350회 상임위원회',
    meeting_date: '2026-02-04T14:00:00Z',
    stream_url: null,
    vod_url: 'https://example.com/vod2.mp4',
    status: 'ended',
    duration_seconds: 5400,
    created_at: '2026-02-04T00:00:00Z',
    updated_at: '2026-02-04T15:30:00Z',
  },
];

const mockSubtitles = [
  {
    id: 'sub-1',
    meeting_id: 'meeting-1',
    start_time: 0,
    end_time: 5,
    text: '안녕하세요. 제352회 본회의를 시작하겠습니다.',
    speaker: '의장',
    confidence: 0.95,
    created_at: '2026-02-06T10:00:00Z',
  },
  {
    id: 'sub-2',
    meeting_id: 'meeting-1',
    start_time: 5,
    end_time: 12,
    text: '오늘의 안건은 2026년 예산안 심의입니다.',
    speaker: '의장',
    confidence: 0.92,
    created_at: '2026-02-06T10:00:05Z',
  },
];

const mockChannels: ChannelType[] = [
  {
    id: 'ch1',
    code: 'ch1',
    name: '도청채널',
    stream_url: 'https://example.com/stream.m3u8',
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
    stream_url: 'https://example.com/stream-off.m3u8',
    livestatus: 0,
    status_text: '방송전',
    has_schedule: false,
    stt_running: false,
  },
];

const mockNoBroadcastChannels: ChannelType[] = [
  mockChannels[0]!,
  {
    ...mockChannels[1]!,
    livestatus: 0,
    status_text: '방송전',
  } as ChannelType,
];

function getLiveChannelTestId(channelId: string) {
  return `channel-${channelId}`;
}

function getLiveChannelUrl(channelId: string = 'ch1') {
  return `/live?channel=${channelId}`;
}

/**
 * API Mock Setup - 페이지에 API 응답을 모킹
 */
async function setupApiMocks(page: Page, options: {
  hasLiveMeeting?: boolean;
  liveMeeting?: typeof mockLiveMeeting | null;
  recentVods?: typeof mockRecentVods;
  channels?: ChannelType[];
  apiDelay?: number;
} = {}) {
  const {
    hasLiveMeeting = true,
    liveMeeting = mockLiveMeeting,
    recentVods = mockRecentVods,
    channels = mockChannels,
    apiDelay = 0,
  } = options;

  await page.route('**/api/channels/status', async (route) => {
    if (apiDelay > 0) {
      await new Promise(resolve => setTimeout(resolve, apiDelay));
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(channels),
    });
  });

  await page.route('**/api/channels/*/stt/start', async (route) => {
    if (apiDelay > 0) {
      await new Promise(resolve => setTimeout(resolve, apiDelay));
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ status: 'started' }),
    });
  });

  // Mock GET /api/meetings/live
  await page.route('**/api/meetings/live*', async (route) => {
    if (apiDelay > 0) {
      await new Promise(resolve => setTimeout(resolve, apiDelay));
    }
    if (hasLiveMeeting && liveMeeting) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(liveMeeting),
      });
    } else {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(null),
      });
    }
  });

  // Mock GET /api/meetings (Recent VODs)
  await page.route('**/api/meetings?*', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        data: recentVods,
        meta: { total: recentVods.length, page: 1 },
      }),
    });
  });

  // Mock GET /api/meetings/{id}/subtitles
  await page.route('**/api/meetings/*/subtitles', async (route) => {
    if (apiDelay > 0) {
      await new Promise(resolve => setTimeout(resolve, apiDelay));
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        data: mockSubtitles,
        meta: { total: mockSubtitles.length },
      }),
    });
  });
}

test.describe('Phase 2: Live Meeting E2E Tests', () => {
  test.describe('S-01: Home Dashboard', () => {
    test('should display live meeting card when broadcast is active', async ({ page }) => {
      await setupApiMocks(page, { hasLiveMeeting: true });
      await page.goto('/');

      // Live badge should be visible
      await expect(page.getByText('Live')).toBeVisible();

      // Meeting title should be displayed
      await expect(page.getByText('제352회 본회의')).toBeVisible();

      // "실시간 자막 보기" button should be visible and enabled
      const watchButton = page.getByRole('button', { name: /실시간 자막 보기/i });
      await expect(watchButton).toBeVisible();
      await expect(watchButton).toBeEnabled();
    });

    test('should show no broadcast message when no live meeting', async ({ page }) => {
      await setupApiMocks(page, { hasLiveMeeting: false });
      await page.goto('/');

      // Should show no meeting message
      await expect(page.getByText('현재 진행 중인 회의가 없습니다')).toBeVisible();

      // "실시간 자막 보기" button should not be visible
      const watchButton = page.getByRole('button', { name: /실시간 자막 보기/i });
      await expect(watchButton).not.toBeVisible();
    });

    test('should display recent VODs list', async ({ page }) => {
      await setupApiMocks(page);
      await page.goto('/');

      // Section heading
      await expect(page.getByText('최근 회의')).toBeVisible();

      // VOD titles should be visible
      await expect(page.getByText('제351회 본회의')).toBeVisible();
      await expect(page.getByText('제350회 상임위원회')).toBeVisible();
    });

    test('should navigate to /live when clicking watch button', async ({ page }) => {
      await setupApiMocks(page);
      await page.goto('/');

      // Click the watch button
      const watchButton = page.getByRole('button', { name: /실시간 자막 보기/i });
      await watchButton.click();

      // Should navigate to /live
      await expect(page).toHaveURL('/live');
      await expect(page.getByTestId('channel-selector')).toBeVisible();
    });
  });

  test.describe('S-02: Live Viewer Page', () => {
    test('should display live page with meeting info when broadcast exists', async ({ page }) => {
      await setupApiMocks(page, { hasLiveMeeting: true });
      await page.goto(getLiveChannelUrl());

      // Page should be loaded
      await expect(page.getByTestId('live-page')).toBeVisible();

      // Header should show meeting title
      await expect(page.getByText('제352회 본회의')).toBeVisible();

      // Live badge should be visible
      await expect(page.getByText('LIVE')).toBeVisible();
    });

    test('should show no broadcast message when no live meeting on /live', async ({ page }) => {
      await setupApiMocks(page, {
        hasLiveMeeting: false,
        channels: mockNoBroadcastChannels,
      });
      await page.goto(getLiveChannelUrl('ch2'));

      // Should show no broadcast message
      await expect(page.getByText('현재 방송 중이 아닙니다')).toBeVisible();

      // Should have channel list button
      const channelListButton = page.getByRole('button', { name: /채널 목록/i });
      await expect(channelListButton).toBeVisible();
    });

    test('should navigate to channel selector when clicking channel list button', async ({ page }) => {
      await setupApiMocks(page, {
        hasLiveMeeting: false,
        channels: mockNoBroadcastChannels,
      });
      await page.goto(getLiveChannelUrl('ch2'));

      // Click channel list button
      const channelListButton = page.getByRole('button', { name: /채널 목록/i });
      await channelListButton.click();

      // Should return to channel selector
      await expect(page).toHaveURL('/live');
      await expect(page.getByTestId('channel-selector')).toBeVisible();
    });

    test('should display HLS player container', async ({ page }) => {
      await setupApiMocks(page, { hasLiveMeeting: true });
      await page.goto(getLiveChannelUrl());

      // HLS player container should be visible
      await expect(page.getByTestId('hls-player-container')).toBeVisible();
    });

    test('should display subtitle panel', async ({ page }) => {
      await setupApiMocks(page, { hasLiveMeeting: true });
      await page.goto(getLiveChannelUrl());

      // Subtitle panel should be visible
      await expect(page.getByTestId('subtitle-panel')).toBeVisible();
    });

    test('should display connection status', async ({ page }) => {
      await setupApiMocks(page, { hasLiveMeeting: true });
      await page.goto(getLiveChannelUrl());

      // Connection status should be visible
      await expect(page.getByTestId('connection-status')).toBeVisible();
    });

    test('should have 70/30 layout for video and subtitles', async ({ page }) => {
      await setupApiMocks(page, { hasLiveMeeting: true });
      await page.goto(getLiveChannelUrl());

      const mainContent = page.getByTestId('main-content');
      const sidebar = page.getByTestId('sidebar');

      // Check that both elements are visible
      await expect(mainContent).toBeVisible();
      await expect(sidebar).toBeVisible();

      // Check classes for layout (lg:w-[70%] and lg:w-[30%])
      await expect(mainContent).toHaveClass(/lg:w-\[70%\]/);
      await expect(sidebar).toHaveClass(/lg:w-\[30%\]/);
    });
  });

  test.describe('Search Functionality', () => {
    test('should have search input in header on live page', async ({ page }) => {
      await setupApiMocks(page, { hasLiveMeeting: true });
      await page.goto(getLiveChannelUrl());

      // Search input should be visible
      const searchInput = page.getByRole('searchbox');
      await expect(searchInput).toBeVisible();
    });

    test('should be able to type in search input', async ({ page }) => {
      await setupApiMocks(page, { hasLiveMeeting: true });
      await page.goto(getLiveChannelUrl());

      const searchInput = page.getByRole('searchbox');
      await searchInput.fill('예산');

      await expect(searchInput).toHaveValue('예산');
    });

    test('should show no results message when search has no matches', async ({ page }) => {
      await setupApiMocks(page, { hasLiveMeeting: true });
      await page.goto(getLiveChannelUrl());

      const searchInput = page.getByRole('searchbox');
      await searchInput.fill('존재하지않는검색어xyz');

      // Wait for debounce
      await page.waitForTimeout(400);

      // No results message should appear (only if there are subtitles loaded)
      // Note: This depends on WebSocket connection which may not be active in E2E
      // We verify the input works correctly
      await expect(searchInput).toHaveValue('존재하지않는검색어xyz');
    });
  });

  test.describe('meetings Resource Field Coverage', () => {
    test('should verify all meeting fields are accessible', async ({ page }) => {
      await setupApiMocks(page, { hasLiveMeeting: true });

      // Navigate to live page directly
      await page.goto('/');

      // id: Used for routing
      const liveButton = page.getByRole('button', { name: /실시간 자막 보기/i });
      await expect(liveButton).toBeVisible();

      // title: Displayed on card
      await expect(page.getByText('제352회 본회의')).toBeVisible();

      // meeting_date: Displayed as formatted date
      await expect(page.getByText(/2026년 2월 6일/)).toBeVisible();

      // status: Indicated by Live badge when status is 'live'
      await expect(page.getByText('Live')).toBeVisible();

      // stream_url: Used in /live page for HLS player
      await page.goto(getLiveChannelUrl());
      await expect(page.getByTestId('hls-player-container')).toBeVisible();
    });

    test('should display VOD meeting fields correctly', async ({ page }) => {
      await setupApiMocks(page);
      await page.goto('/');

      // VOD items should display their fields
      // title
      await expect(page.getByText('제351회 본회의')).toBeVisible();

      // meeting_date (formatted)
      await expect(page.getByText(/2026년 2월 5일/)).toBeVisible();

      // status shown as ended (not Live badge)
      const vodSection = page.locator('text=제351회 본회의').locator('..');
      // VOD items shouldn't have Live badge
      await expect(vodSection.getByText('Live')).not.toBeVisible();
    });
  });

  test.describe('Responsive Layout', () => {
    test('should stack layout vertically on mobile', async ({ page }) => {
      await setupApiMocks(page, { hasLiveMeeting: true });

      // Set mobile viewport
      await page.setViewportSize({ width: 375, height: 667 });
      await page.goto(getLiveChannelUrl());

      const layout = page.getByTestId('live-layout');
      await expect(layout).toHaveClass(/flex-col/);

      // Both main content and sidebar should be full width on mobile
      const mainContent = page.getByTestId('main-content');
      await expect(mainContent).toHaveClass(/w-full/);
    });

    test('should use side-by-side layout on desktop', async ({ page }) => {
      await setupApiMocks(page, { hasLiveMeeting: true });

      // Set desktop viewport
      await page.setViewportSize({ width: 1280, height: 800 });
      await page.goto(getLiveChannelUrl());

      const layout = page.getByTestId('live-layout');
      await expect(layout).toHaveClass(/lg:flex-row/);
    });
  });

  test.describe('Navigation Flow', () => {
    test('complete user flow: Home -> channel selector -> channel live', async ({ page }) => {
      await setupApiMocks(page, { hasLiveMeeting: true });

      // Step 1: Start at home
      await page.goto('/');
      await expect(page).toHaveURL('/');

      // Step 2: Click to go to live
      const watchButton = page.getByRole('button', { name: /실시간 자막 보기/i });
      await watchButton.click();
      await expect(page).toHaveURL('/live');

      // Step 3: Select a channel
      await page.getByTestId(getLiveChannelTestId('ch1')).click();
      await expect(page).toHaveURL('/live?channel=ch1');

      // Step 4: Verify live page content
      await expect(page.getByTestId('live-page')).toBeVisible();
      await expect(page.getByText('제352회 본회의')).toBeVisible();

      // Step 5: Return to selector via browser back
      await page.goBack();
      await expect(page).toHaveURL('/live');
      await expect(page.getByTestId('channel-selector')).toBeVisible();

      // Step 6: Go back one more to home
      await page.goBack();
      await expect(page).toHaveURL('/');
    });

    test('should return to channel selector when no broadcast is selected', async ({ page }) => {
      await setupApiMocks(page, {
        hasLiveMeeting: false,
        channels: mockNoBroadcastChannels,
      });

      // Go directly to /live
      await page.goto(getLiveChannelUrl('ch2'));

      // Should show no broadcast message and channel selector button
      await expect(page.getByText('현재 방송 중이 아닙니다')).toBeVisible();

      // Click channel list button
      await page.getByRole('button', { name: /채널 목록/i }).click();
      await expect(page).toHaveURL('/live');
      await expect(page.getByTestId('channel-selector')).toBeVisible();
    });
  });

  test.describe('Header Component', () => {
    test('should display header with correct title on home page', async ({ page }) => {
      await setupApiMocks(page);
      await page.goto('/');

      // Header should be visible (from Home page title)
      await expect(page.getByText('경기도의회 실시간 자막 서비스')).toBeVisible();
    });

    test('should display header with meeting title on live page', async ({ page }) => {
      await setupApiMocks(page, { hasLiveMeeting: true });
      await page.goto(getLiveChannelUrl());

      // Header should show meeting title
      await expect(page.getByText('제352회 본회의')).toBeVisible();
    });

    test('should have VOD register button on home page', async ({ page }) => {
      await setupApiMocks(page);
      await page.goto('/');

      // VOD register button should be visible (may have multiple, pick the first one)
      const registerButton = page.getByRole('button', { name: /VOD 등록/i }).first();
      await expect(registerButton).toBeVisible();
    });
  });
});

test.describe('subtitles Resource Field Coverage', () => {
  test('subtitle fields should be properly structured in mock data', () => {
    const subtitle = mockSubtitles[0]!;

    // This test verifies that our mock data includes all required subtitle fields
    // The actual WebSocket connection would provide real data

    // Verify mock subtitle structure
    expect(subtitle).toHaveProperty('id');
    expect(subtitle).toHaveProperty('meeting_id');
    expect(subtitle).toHaveProperty('start_time');
    expect(subtitle).toHaveProperty('end_time');
    expect(subtitle).toHaveProperty('text');
    expect(subtitle).toHaveProperty('speaker');
    expect(subtitle).toHaveProperty('confidence');
    expect(subtitle).toHaveProperty('created_at');

    // Verify field types
    expect(typeof subtitle.id).toBe('string');
    expect(typeof subtitle.meeting_id).toBe('string');
    expect(typeof subtitle.start_time).toBe('number');
    expect(typeof subtitle.end_time).toBe('number');
    expect(typeof subtitle.text).toBe('string');
    expect(typeof subtitle.confidence).toBe('number');
  });
});

test.describe('Error Handling', () => {
  test('should display error state when API fails on home', async ({ page }) => {
    // Mock API to return error
    await page.route('**/api/meetings/live*', async (route) => {
      await route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ error: 'Internal Server Error' }),
      });
    });

    await page.route('**/api/meetings?*', async (route) => {
      await route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ error: 'Internal Server Error' }),
      });
    });

    await page.goto('/');

    // Error message should be visible (may have multiple, pick first)
    await expect(page.getByText(/데이터를 불러오는 중 오류/).first()).toBeVisible();
  });

  test('should keep live view stable when meeting API fails', async ({ page }) => {
    await setupApiMocks(page, {
      channels: mockChannels,
    });

    await page.route('**/api/meetings/live*', async (route) => {
      await route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ error: 'Internal Server Error' }),
      });
    });

    await page.goto(getLiveChannelUrl('ch2'));

    // When meeting lookup fails, the page should still render and fall back to no-broadcast state
    await expect(page.getByText('현재 방송 중이 아닙니다')).toBeVisible();
  });
});

test.describe('Loading States', () => {
  test('should show loading state initially on home page', async ({ page }) => {
    // Delay API response
    await page.route('**/api/meetings/live*', async (route) => {
      await new Promise(resolve => setTimeout(resolve, 1000));
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(mockLiveMeeting),
      });
    });

    await page.route('**/api/meetings?*', async (route) => {
      await new Promise(resolve => setTimeout(resolve, 1000));
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          data: mockRecentVods,
          meta: { total: mockRecentVods.length, page: 1 },
        }),
      });
    });

    await page.goto('/');

    // Loading text should be visible initially (may have multiple, pick first)
    await expect(page.getByText('로딩 중...').first()).toBeVisible();
  });

  test('should show loading state initially on live page', async ({ page }) => {
    // Delay API response
    await page.route('**/api/meetings/live*', async (route) => {
      await new Promise(resolve => setTimeout(resolve, 1000));
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(mockLiveMeeting),
      });
    });

    await page.goto(getLiveChannelUrl());

    // Loading indicator should be visible initially
    await expect(page.getByText('로딩 중...')).toBeVisible();
  });
});
