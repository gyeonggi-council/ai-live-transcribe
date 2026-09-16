/**
 * Replay 모드 E2E 테스트
 * VOD MP4 재생 + DB 자막 replay가 동시에 동작하는지 확인
 */
import { test, expect } from '@playwright/test';

const MEETING_ID = 'b80c8cfd-d831-484f-94cd-539ea742bdda';

test('Replay 모드: MP4 영상 + 실시간 자막이 함께 표시되는지 확인', async ({ page }) => {
  await page.goto(
    `http://localhost:3000/live?channel=chT1&replay_meeting=${MEETING_ID}`,
    { waitUntil: 'domcontentloaded' }
  );

  // 1. Replay 비디오 플레이어 확인
  const replayVideo = page.locator('[data-testid="replay-video"]');
  await expect(replayVideo).toBeVisible({ timeout: 15000 });
  console.log('MP4 비디오 플레이어 표시 확인');

  // 비디오 소스 확인
  const src = await replayVideo.getAttribute('src');
  console.log(`비디오 소스: ${src?.substring(0, 60)}...`);
  expect(src).toContain('.mp4');

  // 2. REPLAY 배지 확인
  const replayBadge = page.getByText('REPLAY');
  await expect(replayBadge).toBeVisible({ timeout: 5000 });
  console.log('REPLAY 배지 표시 확인');

  // 3. 자막 패널 확인
  const panel = page.locator('[data-testid="subtitle-panel"]');
  await expect(panel).toBeVisible({ timeout: 10000 });

  // 4. 실시간 자막 도착 대기 (최대 15초)
  const subtitleItem = page.locator('[data-testid="subtitle-item"]').first();
  await expect(subtitleItem).toBeVisible({ timeout: 15000 });

  // 5. 자막 개수 확인
  await page.waitForTimeout(5000);
  const items = page.locator('[data-testid="subtitle-item"]');
  const count = await items.count();
  console.log(`실시간 자막 ${count}개 표시됨`);
  expect(count).toBeGreaterThan(0);

  // 6. 교정 스피너 확인 (pending 상태)
  const spinner = page.locator('[data-testid="correction-spinner"]').first();
  const hasSpinner = await spinner.isVisible().catch(() => false);
  console.log(`교정 스피너 표시: ${hasSpinner}`);

  // 7. 스크린샷
  await page.screenshot({ path: 'e2e/screenshots/replay-with-video.png', fullPage: true });
  console.log('스크린샷 저장 완료');
});
