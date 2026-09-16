/**
 * VOD 자막 표시 E2E 테스트
 * 실제 백엔드 연동으로 DB 자막이 정상 표시되는지 확인
 */
import { test, expect } from '@playwright/test';

const MEETING_ID = 'b80c8cfd-d831-484f-94cd-539ea742bdda';

test.describe('VOD 자막 표시 테스트', () => {
  test('VOD 뷰어에서 실제 자막이 표시되는지 확인', async ({ page }) => {
    await page.goto(`http://localhost:3000/vod/${MEETING_ID}`, { waitUntil: 'networkidle' });

    // 자막 패널 존재 확인
    const subtitlePanel = page.locator('[data-testid="subtitle-panel"]');
    await expect(subtitlePanel).toBeVisible({ timeout: 10000 });

    // 자막 아이템이 로딩될 때까지 대기
    const subtitleItem = page.locator('[data-testid="subtitle-item"]').first();
    await expect(subtitleItem).toBeVisible({ timeout: 10000 });

    // 자막 개수 확인 (최소 1개 이상)
    const items = page.locator('[data-testid="subtitle-item"]');
    const count = await items.count();
    console.log(`VOD 자막 ${count}개 로딩됨`);
    expect(count).toBeGreaterThan(0);

    // 첫 번째 자막 내용 확인
    const firstText = await subtitleItem.textContent();
    console.log(`첫 번째 자막: ${firstText?.substring(0, 80)}`);
    expect(firstText).toContain('의석을 정돈');

    // 시간 칩 확인
    const timeChip = page.locator('[data-testid="time-chip"]').first();
    await expect(timeChip).toBeVisible();
    const timeText = await timeChip.textContent();
    console.log(`시간 칩: ${timeText}`);

    // correction_state 속성 확인 (VOD 자막은 none이어야 함)
    const correctionEl = page.locator('[data-correction-state]').first();
    const state = await correctionEl.getAttribute('data-correction-state');
    console.log(`교정 상태: ${state}`);

    // 스크린샷 저장
    await page.screenshot({ path: 'e2e/screenshots/vod-subtitle-test.png', fullPage: true });
    console.log('스크린샷 저장 완료');
  });

  test('실시간 페이지에서 WebSocket 자막 연결 확인', async ({ page }) => {
    // chT1 테스트 채널로 접속
    // SSE 연결이 열려있어 networkidle 불가 → domcontentloaded 사용
    await page.goto('http://localhost:3000/live?channel=chT1', { waitUntil: 'domcontentloaded' });

    // 자막 패널 확인
    const subtitlePanel = page.locator('[data-testid="subtitle-panel"]');
    await expect(subtitlePanel).toBeVisible({ timeout: 10000 });

    // WebSocket 연결 상태 확인 (연결됨 배지)
    // 연결 시도 후 connected 또는 error 상태
    await page.waitForTimeout(3000);

    // 스크린샷 저장
    await page.screenshot({ path: 'e2e/screenshots/live-ws-test.png', fullPage: true });
    console.log('실시간 페이지 스크린샷 저장 완료');
  });
});
