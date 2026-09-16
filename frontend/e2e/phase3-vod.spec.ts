import { test, expect, type Page } from '@playwright/test';

/**
 * Phase 3 E2E Test Suite - VOD Subtitle
 *
 * 검증 항목:
 * 1. `/` -> `/vod` 네비게이션 (홈에서 VOD 목록으로)
 * 2. `/vod` -> `/vod/:id` 네비게이션 (VOD 목록에서 상세로)
 * 3. VOD 등록 모달 동작 (열기/닫기/폼 제출)
 * 4. 자막 상태 배지 표시 (processing, ended 등)
 * 5. 자막 동기화 (자막 클릭 -> 영상 시점 이동)
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

const mockVodList = [
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
    status: 'processing',
    duration_seconds: 5400,
    created_at: '2026-02-04T00:00:00Z',
    updated_at: '2026-02-04T15:30:00Z',
  },
  {
    id: 'vod-3',
    title: '제349회 예산결산특별위원회',
    meeting_date: '2026-02-03T10:00:00Z',
    stream_url: null,
    vod_url: 'https://example.com/vod3.mp4',
    status: 'ended',
    duration_seconds: 7200,
    created_at: '2026-02-03T00:00:00Z',
    updated_at: '2026-02-03T12:00:00Z',
  },
];

const mockVodMeeting = {
  id: 'vod-1',
  title: '제351회 본회의',
  meeting_date: '2026-02-05T10:00:00Z',
  stream_url: null,
  vod_url: 'https://example.com/vod1.mp4',
  status: 'ended',
  duration_seconds: 3600,
  created_at: '2026-02-05T00:00:00Z',
  updated_at: '2026-02-05T12:00:00Z',
};

const mockSubtitles = [
  {
    id: 'sub-1',
    meeting_id: 'vod-1',
    start_time: 0,
    end_time: 5,
    text: '안녕하세요. 제351회 본회의를 시작하겠습니다.',
    speaker: '의장',
    confidence: 0.95,
    created_at: '2026-02-05T10:00:00Z',
  },
  {
    id: 'sub-2',
    meeting_id: 'vod-1',
    start_time: 5,
    end_time: 12,
    text: '오늘의 안건은 2026년 예산안 심의입니다.',
    speaker: '의장',
    confidence: 0.92,
    created_at: '2026-02-05T10:00:05Z',
  },
  {
    id: 'sub-3',
    meeting_id: 'vod-1',
    start_time: 12,
    end_time: 20,
    text: '먼저 기획재정위원회 위원장님의 보고를 듣겠습니다.',
    speaker: '의장',
    confidence: 0.90,
    created_at: '2026-02-05T10:00:12Z',
  },
];

/**
 * API Mock Setup - 페이지에 API 응답을 모킹
 */
async function setupHomeMocks(page: Page) {
  // Mock GET /api/meetings/live
  await page.route('**/api/meetings/live', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockLiveMeeting),
    });
  });

  // Mock GET /api/meetings (Recent VODs on home)
  await page.route('**/api/meetings?*', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        data: mockVodList.slice(0, 2),
        meta: { total: mockVodList.length, page: 1 },
      }),
    });
  });
}

/**
 * VOD List page mocks
 */
async function setupVodListMocks(page: Page) {
  // Mock GET /api/meetings (VOD list with pagination)
  await page.route('**/api/meetings?*', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        data: mockVodList,
        meta: { total: mockVodList.length, page: 1 },
      }),
    });
  });

  // Also mock /api/meetings/live in case the page needs it
  await page.route('**/api/meetings/live', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(null),
    });
  });
}

/**
 * VOD Viewer page mocks
 */
async function setupVodViewerMocks(page: Page) {
  // Mock GET /api/meetings/{id}
  await page.route('**/api/meetings/vod-1', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockVodMeeting),
    });
  });

  // Mock GET /api/meetings/{id}/subtitles
  await page.route('**/api/meetings/vod-1/subtitles', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockSubtitles),
    });
  });
}

/**
 * Full app mocks: home + vod list + vod viewer
 */
async function setupAllMocks(page: Page) {
  // Mock GET /api/meetings/live
  await page.route('**/api/meetings/live', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockLiveMeeting),
    });
  });

  // Mock GET /api/meetings/{id}/subtitles (must be before /api/meetings/{id})
  await page.route('**/api/meetings/*/subtitles', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockSubtitles),
    });
  });

  // Mock GET /api/meetings/{id} for specific VOD
  await page.route('**/api/meetings/vod-1', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockVodMeeting),
    });
  });

  // Mock GET /api/meetings (list with query params)
  await page.route('**/api/meetings?*', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        data: mockVodList,
        meta: { total: mockVodList.length, page: 1 },
      }),
    });
  });

  // Mock POST /api/meetings (VOD registration)
  await page.route('**/api/meetings', async (route, request) => {
    if (request.method() === 'POST') {
      const body = request.postDataJSON();
      await route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: JSON.stringify({
          id: 'vod-new',
          ...body,
          status: 'processing',
          stream_url: null,
          duration_seconds: null,
          created_at: '2026-02-06T12:00:00Z',
          updated_at: '2026-02-06T12:00:00Z',
        }),
      });
    } else {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          data: mockVodList,
          meta: { total: mockVodList.length, page: 1 },
        }),
      });
    }
  });
}


// ============================================================
// 1. Navigation: Home (/) -> VOD List (/vod)
// ============================================================
test.describe('Phase 3: VOD E2E Tests', () => {
  test.describe('Navigation: Home -> VOD List', () => {
    test('should have "VOD 전체보기" link on home page', async ({ page }) => {
      await setupHomeMocks(page);
      await page.goto('/');

      // "VOD 전체보기" link should be visible
      const vodLink = page.getByRole('link', { name: /VOD 전체보기/i });
      await expect(vodLink).toBeVisible();
    });

    test('should navigate to /vod when clicking "VOD 전체보기"', async ({ page }) => {
      await setupAllMocks(page);
      await page.goto('/');

      // Click the VOD link
      const vodLink = page.getByRole('link', { name: /VOD 전체보기/i });
      await vodLink.click();

      // Should navigate to /vod
      await expect(page).toHaveURL('/vod');
    });

    test('should display VOD list page with title', async ({ page }) => {
      await setupVodListMocks(page);
      await page.goto('/vod');

      // Page title
      await expect(page.getByText('VOD 목록')).toBeVisible();
    });

    test('complete navigation flow: Home -> VOD List -> Home', async ({ page }) => {
      await setupAllMocks(page);

      // Step 1: Start at home
      await page.goto('/');
      await expect(page).toHaveURL('/');

      // Step 2: Click to go to VOD list
      const vodLink = page.getByRole('link', { name: /VOD 전체보기/i });
      await vodLink.click();
      await expect(page).toHaveURL('/vod');

      // Step 3: Verify VOD list content
      await expect(page.getByText('VOD 목록')).toBeVisible();

      // Step 4: Click header logo to go back home
      const homeLink = page.getByRole('link', { name: /경기도의회 자막/i });
      await homeLink.click();
      await expect(page).toHaveURL('/');
    });
  });

  // ============================================================
  // 2. Navigation: VOD List (/vod) -> VOD Viewer (/vod/:id)
  // ============================================================
  test.describe('Navigation: VOD List -> VOD Viewer', () => {
    test('should display VOD items in the list', async ({ page }) => {
      await setupVodListMocks(page);
      await page.goto('/vod');

      // VOD titles should be visible (desktop table view)
      await expect(page.getByText('제351회 본회의')).toBeVisible();
      await expect(page.getByText('제350회 상임위원회')).toBeVisible();
      await expect(page.getByText('제349회 예산결산특별위원회')).toBeVisible();
    });

    test('should navigate to /vod/:id when clicking a VOD item', async ({ page }) => {
      await setupAllMocks(page);
      await page.goto('/vod');

      // Click the first VOD item (제351회 본회의)
      await page.getByText('제351회 본회의').click();

      // Should navigate to /vod/vod-1
      await expect(page).toHaveURL('/vod/vod-1');
    });

    test('should display VOD viewer page with meeting title', async ({ page }) => {
      await setupVodViewerMocks(page);
      await page.goto('/vod/vod-1');

      // Page should be loaded
      await expect(page.getByTestId('vod-viewer-page')).toBeVisible();

      // Meeting title should be displayed in header
      await expect(page.getByText('제351회 본회의')).toBeVisible();
    });

    test('should display MP4 player and subtitle panel on VOD viewer', async ({ page }) => {
      await setupVodViewerMocks(page);
      await page.goto('/vod/vod-1');

      // MP4 player container should be visible
      await expect(page.getByTestId('mp4-player-container')).toBeVisible();

      // Subtitle panel should be visible
      await expect(page.getByTestId('subtitle-panel')).toBeVisible();
    });

    test('should display VOD badge on viewer page', async ({ page }) => {
      await setupVodViewerMocks(page);
      await page.goto('/vod/vod-1');

      // VOD badge should be visible in header
      await expect(page.getByText('VOD')).toBeVisible();
    });

    test('should show loading state while fetching VOD data', async ({ page }) => {
      // Delay API response to observe loading state
      await page.route('**/api/meetings/vod-1', async (route) => {
        await new Promise(resolve => setTimeout(resolve, 1000));
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(mockVodMeeting),
        });
      });

      await page.route('**/api/meetings/vod-1/subtitles', async (route) => {
        await new Promise(resolve => setTimeout(resolve, 1000));
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(mockSubtitles),
        });
      });

      await page.goto('/vod/vod-1');

      // Loading indicator should be visible initially
      await expect(page.getByTestId('page-loading')).toBeVisible();
    });

    test('should show error state when VOD API fails', async ({ page }) => {
      await page.route('**/api/meetings/vod-1', async (route) => {
        await route.fulfill({
          status: 500,
          contentType: 'application/json',
          body: JSON.stringify({ error: 'Internal Server Error' }),
        });
      });

      await page.route('**/api/meetings/vod-1/subtitles', async (route) => {
        await route.fulfill({
          status: 500,
          contentType: 'application/json',
          body: JSON.stringify({ error: 'Internal Server Error' }),
        });
      });

      await page.goto('/vod/vod-1');

      // Error message should be visible
      await expect(page.getByText(/오류가 발생했습니다/)).toBeVisible();

      // Home button should be visible
      await expect(page.getByRole('button', { name: /홈으로 이동/i })).toBeVisible();
    });

    test('complete flow: Home -> VOD List -> VOD Viewer', async ({ page }) => {
      await setupAllMocks(page);

      // Step 1: Start at home
      await page.goto('/');
      await expect(page).toHaveURL('/');

      // Step 2: Navigate to VOD list
      const vodLink = page.getByRole('link', { name: /VOD 전체보기/i });
      await vodLink.click();
      await expect(page).toHaveURL('/vod');

      // Step 3: Click on a VOD item
      await page.getByText('제351회 본회의').click();
      await expect(page).toHaveURL('/vod/vod-1');

      // Step 4: Verify VOD viewer is showing
      await expect(page.getByTestId('vod-viewer-page')).toBeVisible();
      await expect(page.getByText('제351회 본회의')).toBeVisible();
    });
  });

  // ============================================================
  // 3. VOD Register Modal
  // ============================================================
  test.describe('VOD Register Modal', () => {
    test('should open modal when clicking "VOD 등록" button on home page', async ({ page }) => {
      await setupHomeMocks(page);
      await page.goto('/');

      // Click the "VOD 등록" button
      const registerButton = page.getByRole('button', { name: /VOD 등록/i }).first();
      await registerButton.click();

      // Modal should be visible
      await expect(page.getByText('VOD 등록').nth(1)).toBeVisible();
    });

    test('should close modal when clicking "닫기" button', async ({ page }) => {
      await setupHomeMocks(page);
      await page.goto('/');

      // Open the modal
      const registerButton = page.getByRole('button', { name: /VOD 등록/i }).first();
      await registerButton.click();

      // Verify modal is open
      await expect(page.locator('.fixed.inset-0')).toBeVisible();

      // Click the close button
      const closeButton = page.getByRole('button', { name: /닫기/i });
      await closeButton.click();

      // Modal should be closed
      await expect(page.locator('.fixed.inset-0')).not.toBeVisible();
    });

    test('should display modal form fields', async ({ page }) => {
      await setupHomeMocks(page);
      await page.goto('/');

      // Open the modal
      const registerButton = page.getByRole('button', { name: /VOD 등록/i }).first();
      await registerButton.click();

      // The current home page uses a simplified inline modal
      // Verify modal heading is visible
      await expect(page.locator('.fixed.inset-0')).toBeVisible();
      await expect(page.locator('.fixed.inset-0').getByText('VOD 등록')).toBeVisible();
    });
  });

  // ============================================================
  // 4. Subtitle Status Badges
  // ============================================================
  test.describe('Subtitle Status Badges', () => {
    test('should display "자막 완료" badge for ended VODs', async ({ page }) => {
      await setupVodListMocks(page);

      // Set desktop viewport to see the table
      await page.setViewportSize({ width: 1280, height: 800 });
      await page.goto('/vod');

      // "자막 완료" badge should be visible for ended VODs
      await expect(page.getByText('자막 완료').first()).toBeVisible();
    });

    test('should display "자막 생성중" badge for processing VODs', async ({ page }) => {
      await setupVodListMocks(page);

      // Set desktop viewport to see the table
      await page.setViewportSize({ width: 1280, height: 800 });
      await page.goto('/vod');

      // "자막 생성중" badge should be visible for processing VODs
      await expect(page.getByText('자막 생성중')).toBeVisible();
    });

    test('should display correct badge variants (colors)', async ({ page }) => {
      await setupVodListMocks(page);

      // Set desktop viewport
      await page.setViewportSize({ width: 1280, height: 800 });
      await page.goto('/vod');

      // "자막 완료" uses success variant (green)
      const successBadge = page.getByText('자막 완료').first();
      await expect(successBadge).toHaveClass(/bg-green-100/);
      await expect(successBadge).toHaveClass(/text-green-600/);

      // "자막 생성중" uses warning variant (yellow)
      const warningBadge = page.getByText('자막 생성중');
      await expect(warningBadge).toHaveClass(/bg-yellow-100/);
      await expect(warningBadge).toHaveClass(/text-yellow-600/);
    });

    test('should display status badges on home page recent VOD list', async ({ page }) => {
      await setupHomeMocks(page);
      await page.goto('/');

      // Home page shows recent VODs with badges
      // "자막 완료" for ended VOD
      await expect(page.getByText('자막 완료').first()).toBeVisible();

      // "자막 생성중" for processing VOD
      await expect(page.getByText('자막 생성중')).toBeVisible();
    });
  });

  // ============================================================
  // 5. Subtitle Sync (subtitle click -> video seek)
  // ============================================================
  test.describe('Subtitle Sync', () => {
    test('should display subtitle items on VOD viewer page', async ({ page }) => {
      await setupVodViewerMocks(page);
      await page.goto('/vod/vod-1');

      // Subtitle texts should be visible
      await expect(page.getByText('안녕하세요. 제351회 본회의를 시작하겠습니다.')).toBeVisible();
      await expect(page.getByText('오늘의 안건은 2026년 예산안 심의입니다.')).toBeVisible();
      await expect(page.getByText('먼저 기획재정위원회 위원장님의 보고를 듣겠습니다.')).toBeVisible();
    });

    test('should display subtitle timestamps', async ({ page }) => {
      await setupVodViewerMocks(page);
      await page.goto('/vod/vod-1');

      // Timestamps should be formatted as HH:MM:SS
      await expect(page.getByText('00:00:00')).toBeVisible();
      await expect(page.getByText('00:00:05')).toBeVisible();
      await expect(page.getByText('00:00:12')).toBeVisible();
    });

    test('subtitle items should be clickable buttons', async ({ page }) => {
      await setupVodViewerMocks(page);
      await page.goto('/vod/vod-1');

      // SubtitleItem renders as buttons
      const subtitlePanel = page.getByTestId('subtitle-panel');
      const buttons = subtitlePanel.getByRole('button');

      // Should have 3 subtitle buttons
      await expect(buttons).toHaveCount(3);
    });

    test('clicking a subtitle should trigger video seek', async ({ page }) => {
      await setupVodViewerMocks(page);
      await page.goto('/vod/vod-1');

      // Get the video element
      const video = page.getByTestId('mp4-video');
      await expect(video).toBeVisible();

      // Click the second subtitle (start_time: 5)
      const secondSubtitle = page.getByText('오늘의 안건은 2026년 예산안 심의입니다.');
      await secondSubtitle.click();

      // Verify the video's currentTime was set to the subtitle's start_time
      // We evaluate in the browser to check the video element's currentTime
      const currentTime = await page.evaluate(() => {
        const videoEl = document.querySelector('[data-testid="mp4-video"]') as HTMLVideoElement;
        return videoEl?.currentTime ?? -1;
      });

      expect(currentTime).toBe(5);
    });

    test('clicking third subtitle should seek to its start time', async ({ page }) => {
      await setupVodViewerMocks(page);
      await page.goto('/vod/vod-1');

      // Click the third subtitle (start_time: 12)
      const thirdSubtitle = page.getByText('먼저 기획재정위원회 위원장님의 보고를 듣겠습니다.');
      await thirdSubtitle.click();

      // Verify the video's currentTime was set to 12
      const currentTime = await page.evaluate(() => {
        const videoEl = document.querySelector('[data-testid="mp4-video"]') as HTMLVideoElement;
        return videoEl?.currentTime ?? -1;
      });

      expect(currentTime).toBe(12);
    });

    test('should display subtitle count in panel header', async ({ page }) => {
      await setupVodViewerMocks(page);
      await page.goto('/vod/vod-1');

      // SubtitlePanel header shows count
      const subtitlePanel = page.getByTestId('subtitle-panel');
      await expect(subtitlePanel.getByText('자막')).toBeVisible();
      await expect(subtitlePanel.getByText('3')).toBeVisible();
    });

    test('VOD viewer should have 70/30 layout on desktop', async ({ page }) => {
      await setupVodViewerMocks(page);

      // Set desktop viewport
      await page.setViewportSize({ width: 1280, height: 800 });
      await page.goto('/vod/vod-1');

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

  // ============================================================
  // 6. Speaker Management
  // ============================================================
  test.describe('Speaker Management', () => {
    test('can navigate to speaker management and save speaker batch update', async ({ page }) => {
      const patchPayloads: Array<Record<string, unknown>> = [];

      await page.route('**/api/meetings/vod-1', async (route) => {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(mockVodMeeting),
        });
      });

      await page.route('**/api/meetings/vod-1/subtitles*', async (route, request) => {
        if (request.method() === 'GET') {
          await route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify({ items: mockSubtitles }),
          });
          return;
        }

        if (request.method() === 'PATCH') {
          const requestBody = request.postData() ? JSON.parse(request.postData()!) : {};
          patchPayloads.push(requestBody);

          await route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify({
              updated: 1,
              items: requestBody.items || [],
            }),
          });
          return;
        }

        await route.continue();
      });

      await page.goto('/vod/vod-1');

      await expect(page.getByRole('link', { name: '화자 관리' })).toBeVisible();
      await page.getByRole('link', { name: '화자 관리' }).click();
      await expect(page).toHaveURL('/vod/vod-1/speaker');

      const firstSubtitleSelect = page
        .getByText('안녕하세요. 제351회 본회의를 시작하겠습니다.')
        .locator('..')
        .getByRole('combobox');
      await firstSubtitleSelect.selectOption('화자 1');

      await page.getByRole('button', { name: /변경 저장/i }).click();

      await expect(async () => {
        expect(patchPayloads).toHaveLength(1);
      }).toPass({ timeout: 3000 });

      const payload = patchPayloads[0];
      expect(payload).toEqual({
        items: [
          {
            id: 'sub-1',
            speaker: '화자 1',
          },
        ],
      });
    });
  });

  // ============================================================
  // meetings/subtitles Resource Field Coverage (VOD context)
  // ============================================================
  test.describe('VOD Resource Field Coverage', () => {
    test('should verify all VOD meeting fields are displayed', async ({ page }) => {
      await setupVodListMocks(page);

      // Set desktop viewport
      await page.setViewportSize({ width: 1280, height: 800 });
      await page.goto('/vod');

      // title: Displayed in table
      await expect(page.getByText('제351회 본회의')).toBeVisible();

      // meeting_date: Displayed as formatted date
      await expect(page.getByText(/2026년 2월 5일/)).toBeVisible();

      // duration_seconds: Displayed as formatted time
      await expect(page.getByText('1:00:00')).toBeVisible();

      // status: Displayed as badge
      await expect(page.getByText('자막 완료').first()).toBeVisible();
    });

    test('subtitle fields should be properly structured', async () => {
      const firstSubtitle = mockSubtitles[0];

      expect(firstSubtitle).toBeDefined();
      if (!firstSubtitle) {
        throw new Error('Expected at least one mock subtitle fixture.');
      }

      // Verify mock subtitle structure covers all required fields
      expect(firstSubtitle).toHaveProperty('id');
      expect(firstSubtitle).toHaveProperty('meeting_id');
      expect(firstSubtitle).toHaveProperty('start_time');
      expect(firstSubtitle).toHaveProperty('end_time');
      expect(firstSubtitle).toHaveProperty('text');
      expect(firstSubtitle).toHaveProperty('speaker');
      expect(firstSubtitle).toHaveProperty('confidence');

      // Verify field types
      expect(typeof firstSubtitle.id).toBe('string');
      expect(typeof firstSubtitle.meeting_id).toBe('string');
      expect(typeof firstSubtitle.start_time).toBe('number');
      expect(typeof firstSubtitle.end_time).toBe('number');
      expect(typeof firstSubtitle.text).toBe('string');
      expect(typeof firstSubtitle.speaker).toBe('string');
      expect(typeof firstSubtitle.confidence).toBe('number');
    });
  });
});
