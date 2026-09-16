import { NextResponse } from 'next/server';

/**
 * 웹앱(PWA) 매니페스트 — 브라우저의 "앱으로 설치" 로 바탕화면 아이콘·독립 창을 만든다.
 *
 * 왜 있나(2026-09-10): 설치형 영상추출기(exe)가 담당자 PC 의 응용프로그램 제어 정책에
 * 막혀 실행되지 않는다(경로를 Program Files 로 옮겨도 동일 — 서명·해시 허용목록 기준).
 * 웹앱은 새 exe 가 아니라 브라우저 안에서 도는 것이라 그 정책에 걸리지 않는다.
 *
 * ⚠ 서비스워커는 일부러 두지 않았다. 오프라인 캐시가 붙으면 배포 뒤에도 담당자 화면이
 *   옛 버전으로 남는다 — 이 서비스는 거의 매일 배포한다. 설치는 서비스워커 없이도
 *   Edge/Chrome 메뉴의 "앱으로 설치" 로 된다(자동 설치 배너만 안 뜬다).
 *
 * ⚠ 파일 이름이 `app/manifest.ts` 가 아니라 여기인 이유 — Next 14 는 그 규약 파일을 보면
 *   <link rel="manifest" href="/manifest.webmanifest"> 를 **자동으로** 걸고 basePath 를
 *   붙이지 않는다. 그리고 그 링크가 layout 의 `metadata.manifest` 를 덮는다. 루트(/)는
 *   문서 허브라 그 주소는 307 로 새 나가 웹앱이 이름·아이콘 없이 설치됐다(2026-09-10 실측).
 *   규약이 아닌 라우트로 두고 layout 에서 basePath 를 붙여 직접 건다. 되돌리지 말 것.
 *   ★폴더 이름에 점(.)을 넣으면(`site.webmanifest`) Next 가 라우트로 등록하지 않아 404 다 —
 *   메타데이터 파일 규약으로 오인한다. 그래서 확장자 없는 이름을 쓴다. 매니페스트는
 *   파일 이름이 아니라 Content-Type(application/manifest+json)으로 인식된다.
 *
 * basePath 는 빌드 ARG(next.config.js 와 같은 값)라 URL 에 직접 붙여야 한다 —
 * Next 가 매니페스트 안의 경로까지 고쳐 주지는 않는다.
 */
const basePath = process.env.NEXT_PUBLIC_BASE_PATH || '';

export const dynamic = 'force-static';

export function GET() {
  return NextResponse.json({
    id: `${basePath}/`,
    name: '경기도의회 자막서비스',
    short_name: '자막서비스',
    description: '회의 영상 자막 조회와 의원 발언영상 추출',
    lang: 'ko',
    start_url: `${basePath}/`,
    scope: `${basePath}/`,
    display: 'standalone',
    background_color: '#ffffff',
    theme_color: '#3c5d93',
    icons: [
      { src: `${basePath}/icons/icon-192.png`, sizes: '192x192', type: 'image/png', purpose: 'any' },
      { src: `${basePath}/icons/icon-512.png`, sizes: '512x512', type: 'image/png', purpose: 'any' },
      // maskable: 윈도우·안드로이드가 아이콘을 자기 모양으로 잘라낼 때 쓰는 판(글리프가 안전영역 안)
      { src: `${basePath}/icons/icon-maskable-512.png`, sizes: '512x512', type: 'image/png', purpose: 'maskable' },
    ],
    // 작업표시줄 아이콘 오른쪽 클릭 → 바로 그 화면으로
    shortcuts: [
      { name: '발언영상 추출', short_name: '발언영상', url: `${basePath}/clips` },
      { name: '실시간 자막', short_name: '실시간', url: `${basePath}/live` },
      { name: '회의 목록', short_name: '회의', url: `${basePath}/vod` },
    ],
  }, { headers: { 'content-type': 'application/manifest+json' } });
}
