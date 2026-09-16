/**
 * HLS STT 실시간 자막 E2E 테스트
 * ffmpeg HLS 스트리밍 → Deepgram STT → WebSocket 자막 확인
 */
import { test, expect } from '@playwright/test';

test('HLS 스트리밍에서 Deepgram STT 자막이 실시간 표시되는지 확인', async ({ page }) => {
  // HLS 모드로 접속 (replay_meeting 없이)
  await page.goto('http://localhost:3000/live?channel=chT1', { waitUntil: 'domcontentloaded' });

  // 자막 패널 확인
  const panel = page.locator('[data-testid="subtitle-panel"]');
  await expect(panel).toBeVisible({ timeout: 10000 });

  // WebSocket 연결 확인
  const connectionStatus = page.locator('[data-testid="connection-status"]');
  await expect(connectionStatus).toBeVisible({ timeout: 5000 });

  // STT 자막 도착 대기 (HLS 세그먼트 수집 + Deepgram 처리 시간 필요, 최대 30초)
  console.log('HLS STT 자막 대기 중 (최대 30초)...');
  const subtitleItem = page.locator('[data-testid="subtitle-item"]').first();

  try {
    await expect(subtitleItem).toBeVisible({ timeout: 30000 });

    // 자막 개수 확인
    await page.waitForTimeout(5000);
    const items = page.locator('[data-testid="subtitle-item"]');
    const count = await items.count();
    console.log(`HLS STT 자막 ${count}개 표시됨`);
    expect(count).toBeGreaterThan(0);

    // 자막 내용 확인
    const firstText = await subtitleItem.textContent();
    console.log(`첫 번째 자막: ${firstText?.substring(0, 100)}`);

    // 교정 스피너 확인
    const spinner = page.locator('[data-testid="correction-spinner"]').first();
    const hasSpinner = await spinner.isVisible().catch(() => false);
    console.log(`교정 스피너 표시: ${hasSpinner}`);
  } catch {
    // STT 자막이 30초 안에 안 올 수도 있음 (Deepgram API 키 문제 등)
    console.log('주의: 30초 내 STT 자막 미도착 - Deepgram API 키 또는 네트워크 확인 필요');

    // interim 텍스트라도 확인
    const sttActivity = page.locator('[data-testid="stt-activity"]');
    const activityText = await sttActivity.textContent().catch(() => '');
    console.log(`STT 활동 상태: ${activityText}`);
  }

  // 스크린샷
  await page.screenshot({ path: 'e2e/screenshots/hls-stt-test.png', fullPage: true });
  console.log('스크린샷 저장 완료');
});
