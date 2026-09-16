'use client';

/**
 * ngrok 무료 도메인 브라우저 경고(interstitial, ERR_NGROK_6024) 우회 — 임시 조치.
 *
 * ngrok 무료는 브라우저 User-Agent로 오는 요청에 HTML 경고 페이지를 앞단에 끼워넣어,
 * fetch()가 JSON/파일 대신 HTML을 받게 만든다. 유일한 우회는 `ngrok-skip-browser-warning`
 * 요청 헤더뿐이다. 현재 프론트는 same-origin `/api/*`로 호출하고 Vercel rewrite가 그 요청을
 * (헤더 포함) ngrok 백엔드로 그대로 중계하므로, `/api/*` 요청에 이 헤더를 주입하면 우회된다.
 *
 * apiClient는 이미 헤더를 붙이지만 다운로드/내보내기 등 bare fetch는 안 붙여서 hwpx/docx
 * 내보내기가 interstitial을 받아 깨졌다 → 여기서 window.fetch를 감싸 모든 `/api/*`(및 직접
 * ngrok) 요청에 헤더를 보강한다. 비-ngrok 백엔드(NCP 등)에선 서버가 무시하므로 무해.
 * EventSource(SSE)/WebSocket은 헤더를 못 붙이지만 채널상태는 폴링 폴백, 실시간 자막 WS는
 * interstitial 미적용이라 영향 없음.
 */
if (typeof window !== 'undefined') {
  const w = window as Window & { __ngrokFetchPatched?: boolean };
  if (!w.__ngrokFetchPatched) {
    w.__ngrokFetchPatched = true;
    const originalFetch = window.fetch.bind(window);
    window.fetch = (input: RequestInfo | URL, init?: RequestInit) => {
      const url =
        typeof input === 'string'
          ? input
          : input instanceof URL
            ? input.href
            : input.url;
      // same-origin '/api/*'(프록시→ngrok) 또는 직접 ngrok 요청에만 헤더 주입
      if (!url.includes('/api/') && !url.includes('ngrok')) {
        return originalFetch(input, init);
      }
      const headers = new Headers(
        init?.headers ?? (input instanceof Request ? input.headers : undefined),
      );
      headers.set('ngrok-skip-browser-warning', 'true');
      return originalFetch(input, { ...init, headers });
    };
  }
}

/** 렌더 출력 없음 — fetch 패치를 클라이언트에서 일찍 설치하기 위한 마운트 지점. */
export default function NgrokCompat() {
  return null;
}
