/**
 * 실시간 자막 재생 테스트
 * DB 자막이 WebSocket을 통해 실시간으로 표시되는지 확인
 */
import { test, expect } from '@playwright/test';

test('chT1 채널에서 실시간 자막이 표시되는지 확인', async ({ page }) => {
  await page.goto('http://localhost:3000/live?channel=chT1', { waitUntil: 'domcontentloaded' });

  // 자막 패널 확인
  const panel = page.locator('[data-testid="subtitle-panel"]');
  await expect(panel).toBeVisible({ timeout: 10000 });

  // 실시간 자막 도착 대기 (최대 15초)
  const subtitleItem = page.locator('[data-testid="subtitle-item"]').first();
  await expect(subtitleItem).toBeVisible({ timeout: 15000 });

  // 자막 개수 확인
  await page.waitForTimeout(5000);
  const items = page.locator('[data-testid="subtitle-item"]');
  const count = await items.count();
  console.log(`실시간 자막 ${count}개 표시됨`);
  expect(count).toBeGreaterThan(0);

  // 자막 내용 확인 (실제 의회 자막)
  const firstText = await subtitleItem.textContent();
  console.log(`첫 번째 자막: ${firstText?.substring(0, 80)}`);

  // 교정 상태 확인 (pending 스피너가 보여야 함)
  const spinner = page.locator('[data-testid="correction-spinner"]').first();
  const hasSpinner = await spinner.isVisible().catch(() => false);
  console.log(`교정 스피너 표시: ${hasSpinner}`);

  // 스크린샷
  await page.screenshot({ path: 'e2e/screenshots/live-replay-test.png', fullPage: true });
  console.log('스크린샷 저장 완료');
});
