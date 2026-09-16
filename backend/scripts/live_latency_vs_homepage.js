// 우리 /live 와 의회 홈페이지(live.ggc.go.kr, Clappr+hls.js)의 hls.js 라이브 지연을 같은 벽시계로 N초 읽어 중앙값 차이를 낸다
// (2026-09-14, 정본 docs/live-sync-eval-2026-09.md §3·§5). 보조 측정이다 — 기준 엣지가 다르다(우리는 서버 재생목록, 홈페이지는 CDN,
// 차이 ≈ 수집기 폴링 0~1초). 객관 측정은 같은 사건의 벽시계 차이(사람) 또는 두 페이지 음성 교차상관.
// 사용: PW_ROOT=<playwright-core 가 있는 frontend> OUT=out.json node backend/scripts/live_latency_vs_homepage.js ch1 60 <chrome-headless-shell 경로>
//   오르카서버 크롬은 Chrome for Testing(메모리 playwright-cdn-stalls-use-cft). 홈페이지 플레이어는 window.xmplayer(Clappr) 에
//   원본 재생목록을 직접 load 한다(홈페이지 loadPlayerLive 와 같은 URL).
const path = require('path');
const { chromium } = require(require.resolve('playwright-core', { paths: [process.env.PW_ROOT] }));
const [channel, secsArg, exe] = process.argv.slice(2);
const SECS = Number(secsArg || 60);
const origin = `https://stream01.cdn.gov-ntruss.com/live/${channel}/playlist.m3u8`;
(async () => {
  const browser = await chromium.launch({ executablePath: exe, headless: true,
    args: ['--no-sandbox', '--autoplay-policy=no-user-gesture-required', '--ignore-certificate-errors', '--mute-audio'] });
  const ctx = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1280, height: 800 } });
  const ours = await ctx.newPage();
  const home = await ctx.newPage();
  await ours.goto(`${process.env.GGC_BASE_URL || 'http://localhost:3000'}/transcribe/live?channel=${channel}`, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await home.goto('https://live.ggc.go.kr/onair/onair.do', { waitUntil: 'domcontentloaded', timeout: 60000 });
  await home.waitForTimeout(3000);
  const probe = await home.evaluate((src) => {
    try {
      const p = window.xmplayer; if (!p) return 'no xmplayer';
      p.load(src); p.play();
      return 'loaded';
    } catch (e) { return 'err ' + e.message; }
  }, origin);
  console.log('homepage clappr:', probe);
  await ours.waitForTimeout(8000);
  const rows = [];
  const t0 = Date.now();
  for (let i = 0; i < SECS; i++) {
    const a = await ours.evaluate(() => {
      const d = window.__syncDebug || {}; const v = document.querySelector('video');
      return { lat: d.hlsLatency, tgt: d.syncTarget, ready95: d.readyLagP95, src: d.clockSource, late: d.lateCount,
        ct: v ? v.currentTime : null, paused: v ? v.paused : null, rs: v ? v.readyState : null };
    }).catch(() => null);
    const b = await home.evaluate(() => {
      try {
        const p = window.xmplayer; const pb = p && p.core && (p.core.activePlayback || (p.core.getCurrentPlayback && p.core.getCurrentPlayback()));
        const h = pb && (pb._hls || pb.hls);
        const v = pb && pb.el; 
        return { lat: h ? h.latency : null, tl: h ? h.targetLatency : null, ct: v ? v.currentTime : null, paused: v ? v.paused : null, keys: h ? null : (pb ? Object.keys(pb).filter(k=>/hls/i.test(k)).join(',') : 'no-pb') };
      } catch (e) { return { err: e.message }; }
    }).catch(() => null);
    rows.push({ t: (Date.now() - t0) / 1000, ours: a, home: b });
    if (i % 10 === 0) console.log(JSON.stringify(rows[rows.length - 1]));
    await ours.waitForTimeout(1000);
  }
  const num = (xs) => xs.filter((x) => typeof x === 'number' && isFinite(x)).sort((p, q) => p - q);
  const med = (xs) => (xs.length ? xs[Math.floor(xs.length / 2)] : null);
  const oursL = num(rows.map((r) => r.ours && r.ours.lat)); const homeL = num(rows.map((r) => r.home && r.home.lat));
  console.log(JSON.stringify({ ours_median: med(oursL), ours_n: oursL.length, home_median: med(homeL), home_n: homeL.length,
    diff_median: med(oursL) != null && med(homeL) != null ? +(med(oursL) - med(homeL)).toFixed(1) : null }));
  require('fs').writeFileSync(process.env.OUT || 'latency.json', JSON.stringify(rows, null, 1));
  await browser.close();
})().catch((e) => { console.error('FAIL', e); process.exit(1); });
