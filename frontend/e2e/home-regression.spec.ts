import { expect, test } from '@playwright/test';

test.describe('Home regression', () => {
  test('renders KPI cards with real API responses', async ({ page }) => {
    await page.route('**/api/stats/overview', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          total_meetings: 77,
          total_subtitles: 12345,
          total_duration: 0,
          average_confidence: 0.95,
        }),
      });
    });

    await page.route('**/api/meetings?status=processing&limit=100', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([{ id: 'm1' }, { id: 'm2' }]),
      });
    });

    await page.route('**/api/meetings/live*', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: 'null' });
    });

    await page.route('**/api/meetings?status=processing,ended&limit=5', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' });
    });

    await page.goto('/');

    await expect(page.getByText('77건')).toBeVisible();
    await expect(page.getByText('12,345개')).toBeVisible();
    await expect(page.getByText('2건')).toBeVisible();
  });

  test('supports retry CTA on live/vod error states', async ({ page }) => {
    await page.route('**/api/stats/overview', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ total_meetings: 1, total_subtitles: 1, total_duration: 0, average_confidence: 1 }),
      });
    });

    await page.route('**/api/meetings?status=processing&limit=100', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' });
    });

    await page.route('**/api/meetings/live*', async (route) => {
      await route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ detail: 'fail' }) });
    });

    await page.route('**/api/meetings?status=processing,ended&limit=5', async (route) => {
      await route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ detail: 'fail' }) });
    });

    await page.goto('/');

    const retryButtons = page.getByRole('button', { name: '다시 시도' });
    await expect(retryButtons).toHaveCount(2);
  });
});
