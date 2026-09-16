// 라이브 화면 종단 동기 측정 (2026-09-11, 정본 docs/live-sync-eval-2026-09.md):
// 영상이 내보내는 음성(captureStream)과 화면에 자막이 뜬 순간을 같은 벽시계로 기록한다.
// 채점은 scripts/eval_live_timing.py --e2e <outPrefix> (파드에서 — ffmpeg·기준값 모델).
// 사용: node backend/scripts/live_sync_capture.js <url> <seconds> <outPrefix>
//   playwright-core 는 frontend 의존성의 것을 쓴다 (없으면 PW_FRONTEND=<frontend 폴더>).
const path = require('path');
const fs = require('fs');
const { chromium } = require(require.resolve('playwright-core', {
  paths: [process.env.PW_FRONTEND || path.join(__dirname, '..', '..', 'frontend')],
}));

const [url, secsArg, outPrefix] = process.argv.slice(2);
const SECS = Number(secsArg || 360);

(async () => {
  const browser = await chromium.launch({
    channel: 'chrome',
    headless: true,
    args: ['--autoplay-policy=no-user-gesture-required', '--ignore-certificate-errors'],
  });
  const page = await browser.newPage({ ignoreHTTPSErrors: true, viewport: { width: 1400, height: 900 } });
  // WS 자막 수신 기록 (페이지 스크립트보다 먼저 설치)
  await page.addInitScript(() => {
    window.__cap = { ws: [], dom: [], clock: [] };
    const Orig = window.WebSocket;
    window.WebSocket = function (...a) {
      const ws = new Orig(...a);
      ws.addEventListener('message', (ev) => {
        try {
          const m = JSON.parse(ev.data);
          if (m.type === 'subtitle_created') {
            const s = (m.payload && m.payload.subtitle) || m.subtitle || {};
            window.__cap.ws.push({ wall: Date.now(), id: s.id, text: s.text, start: s.start_time, end: s.end_time });
          }
        } catch {}
      });
      return ws;
    };
    window.WebSocket.prototype = Orig.prototype;
    Object.assign(window.WebSocket, Orig);
  });
  await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 60000 });

  // 동기화 성립 + 재생 대기
  const t0 = Date.now();
  while (Date.now() - t0 < 120000) {
    const ok = await page.evaluate(() => {
      const v = document.querySelector('video');
      const d = window.__syncDebug;
      return !!(v && !v.paused && v.currentTime > 0 && d && d.isSynced);
    }).catch(() => false);
    if (ok) break;
    await page.waitForTimeout(1000);
  }
  console.log('synced after', (Date.now() - t0) / 1000, 's', await page.evaluate(() => JSON.stringify(window.__syncDebug)));
  await page.waitForTimeout(5000);

  // DOM 자막 등장 + 시계 샘플 + 음성 녹음 시작
  const recStart = await page.evaluate(() => new Promise((resolve) => {
    const v = document.querySelector('video');
    v.muted = false;
    const seen = new Set(Array.from(document.querySelectorAll('[data-testid="subtitle-item"] [data-subtitle-text]')).map((e) => e.textContent.trim()));
    new MutationObserver(() => {
      for (const e of document.querySelectorAll('[data-testid="subtitle-item"] [data-subtitle-text]')) {
        const t = e.textContent.replace(/(교정 중|교정됨)$/, '').trim();
        if (!seen.has(t)) { seen.add(t); window.__cap.dom.push({ wall: Date.now(), text: t }); }
      }
    }).observe(document.body, { childList: true, subtree: true, characterData: true });
    setInterval(() => {
      const d = window.__syncDebug || {};
      window.__cap.clock.push({
        wall: Date.now(), vc: d.videoClock, src: d.clockSource, ct: v.currentTime, lat: d.hlsLatency, ac: d.audioClock,
      });
    }, 200);
    const stream = v.captureStream();
    const rec = new MediaRecorder(new MediaStream(stream.getAudioTracks()), { mimeType: 'audio/webm;codecs=opus' });
    window.__chunks = [];
    rec.ondataavailable = (e) => { if (e.data.size) window.__chunks.push(e.data); };
    rec.onstart = () => resolve(Date.now());
    window.__rec = rec;
    rec.start(1000);
  }));
  console.log('recording', SECS, 's from', recStart);
  await page.waitForTimeout(SECS * 1000);

  const b64 = await page.evaluate(() => new Promise((resolve) => {
    window.__rec.onstop = async () => {
      const buf = await new Blob(window.__chunks, { type: 'audio/webm' }).arrayBuffer();
      let s = ''; const u = new Uint8Array(buf);
      for (let i = 0; i < u.length; i += 0x8000) s += String.fromCharCode.apply(null, u.subarray(i, i + 0x8000));
      resolve(btoa(s));
    };
    window.__rec.stop();
  }));
  fs.writeFileSync(outPrefix + '.webm', Buffer.from(b64, 'base64'));
  const cap = await page.evaluate(() => window.__cap);
  fs.writeFileSync(outPrefix + '.json', JSON.stringify({ url, recStart, ...cap }, null, 0));
  console.log('saved', outPrefix, 'ws', cap.ws.length, 'dom', cap.dom.length, 'clock', cap.clock.length, 'audio bytes', b64.length * 0.75);
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
