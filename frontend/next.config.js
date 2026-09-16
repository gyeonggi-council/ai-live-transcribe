const { version } = require('./package.json');

// k3s(경로 기반 /transcribe) 배포 호환: basePath 는 빌드 ARG 로 주입된다.
// Vercel(루트 서빙)에서는 빈 값이라 동작이 그대로다.
const basePath = process.env.NEXT_PUBLIC_BASE_PATH || '';

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  basePath,
  // 컨테이너 런타임(node server.js)용 — Vercel 빌드에는 영향 없다.
  output: 'standalone',
  eslint: {
    // ESLint errors in test files should not block production builds
    ignoreDuringBuilds: true,
  },
  typescript: {
    // Type checking is done separately via tsc
    ignoreBuildErrors: false,
  },
  // 백엔드 주소. ★기본값을 두지 않는다 — 비면 브라우저가 '접속한 주소 그대로'(same-origin)
  //   로 호출하고, Next 서버가 아래 rewrites 로 API_PROXY_TARGET 에 중계한다.
  env: {
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL || '',
    // ★기본값을 두지 않는다(2026-09-01 장애). 값이 비면 훅이 '접속한 주소 그대로'
    //   (same-origin + basePath)로 wss://<호스트>/transcribe/ws/... 를 만든다.
    //   옛 ngrok 주소를 기본값으로 두었더니 k3s 빌드에 그대로 박혀, 제393회 제1차
    //   본회의 생중계 중 모든 브라우저가 죽은 터널로 붙어 '연결하는 중'에서 멈췄다.
    NEXT_PUBLIC_WS_URL: process.env.NEXT_PUBLIC_WS_URL || '',
    NEXT_PUBLIC_APP_VERSION: process.env.NEXT_PUBLIC_APP_VERSION || version,
  },
  // API 프록시: 브라우저는 same-origin '/api/*'로 호출하고 Next(서버)이 백엔드로 중계한다.
  // 이렇게 하면 cross-origin CORS 사전요청(OPTIONS)이 사라져, ngrok 무료 터널이
  // 사전요청을 503으로 막던 문제를 우회한다(서버↔ngrok 중계는 인터스티셜에 안 걸림).
  async rewrites() {
    // 프록시 중계 대상(백엔드). 우선순위: API_PROXY_TARGET > NEXT_PUBLIC_API_URL.
    // 둘 다 비면 중계하지 않는다 — 같은 호스트에서 백엔드를 서빙한다는 뜻이다.
    const apiTarget = process.env.API_PROXY_TARGET || process.env.NEXT_PUBLIC_API_URL || '';
    if (!apiTarget) return [];
    return [{ source: '/api/:path*', destination: `${apiTarget}/api/:path*` }];
  },
  // 외부 이미지 허용 (경기도의회 공식 CI)
  images: {
    remotePatterns: [
      {
        protocol: 'https',
        hostname: 'www.ggc.go.kr',
        pathname: '/design/theme/asa/images/**',
      },
    ],
  },
};

module.exports = nextConfig;
