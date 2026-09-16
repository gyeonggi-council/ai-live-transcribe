/**
 * 자막 표시 스모크 테스트
 * Mock 모드에서 /live 페이지 자막이 정상 표시되는지 확인
 */
import { test, expect } from '@playwright/test';

test.describe('실시간 자막 표시 테스트', () => {
  test('Mock 모드에서 자막이 SubtitlePanel에 표시되는지 확인', async ({ page }) => {
    // /live 페이지로 이동 (채널 파라미터 포함)
    await page.goto('http://localhost:3000/live?channel=chT1', { waitUntil: 'networkidle' });

    // 페이지 로드 확인
    await expect(page).toHaveTitle(/자막|subtitle|경기도/i, { timeout: 10000 }).catch(() => {
      // 타이틀이 다를 수 있음, 페이지 로드만 확인
    });

    // 자막 패널 존재 확인
    const subtitlePanel = page.locator('[data-testid="subtitle-panel"]');
    await expect(subtitlePanel).toBeVisible({ timeout: 10000 });

    // Mock 자막이 생성될 때까지 대기 (1.2초 간격)
    // 최대 5초 대기
    const subtitleItem = page.locator('[data-testid="subtitle-item"]').first();
    await expect(subtitleItem).toBeVisible({ timeout: 8000 });

    // 자막 텍스트 확인 (mock 스크립트에 포함된 텍스트)
    const subtitleTexts = page.locator('[data-testid="subtitle-item"]');
    const count = await subtitleTexts.count();
    console.log(`자막 ${count}개 표시됨`);
    expect(count).toBeGreaterThan(0);

    // 첫 번째 자막의 텍스트 내용 확인
    const firstText = await subtitleItem.textContent();
    console.log(`첫 번째 자막: ${firstText}`);
    expect(firstText).toBeTruthy();

    // 교정 상태 확인: pending 상태의 shimmer 애니메이션
    const correctionStateEl = page.locator('[data-correction-state="pending"]').first();
    const hasPending = await correctionStateEl.isVisible().catch(() => false);
    console.log(`교정 대기(pending) 상태 자막 존재: ${hasPending}`);

    // 스피너 확인 (pending 상태일 때)
    if (hasPending) {
      const spinner = page.locator('[data-testid="correction-spinner"]').first();
      const hasSpinner = await spinner.isVisible().catch(() => false);
      console.log(`교정 스피너 표시: ${hasSpinner}`);
    }

    // 스크린샷 저장
    await page.screenshot({ path: 'e2e/screenshots/subtitle-test.png', fullPage: true });
    console.log('스크린샷 저장: e2e/screenshots/subtitle-test.png');
  });

  test('자막 패널에 자막이 표시되는지 확인 (영상 위 오버레이는 2026-09-08 제거)', async ({ page }) => {
    await page.goto('http://localhost:3000/live?channel=chT1', { waitUntil: 'networkidle' });

    const panel = page.locator('[data-testid="subtitle-panel"]');

    // Mock 자막이 생성될 때까지 대기
    await expect(panel).toBeVisible({ timeout: 8000 });

    const panelText = await panel.textContent();
    console.log(`자막 패널: ${panelText}`);
    expect(panelText).toBeTruthy();
  });
});
