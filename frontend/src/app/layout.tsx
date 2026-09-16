import { JetBrains_Mono } from 'next/font/google';
import localFont from 'next/font/local';

import { PlatformLayout } from '@/components/layout';
import NgrokCompat from '@/components/NgrokCompat';
import { ToastProvider } from '@/components/Toast';
import { AuthProvider } from '@/contexts/AuthContext';
import { BreadcrumbProvider } from '@/contexts/BreadcrumbContext';
import { SidebarProvider } from '@/contexts/SidebarContext';

import './globals.css';

import type { Metadata, Viewport } from 'next';

// k3s 는 /transcribe 아래에 서빙한다. Next 는 app/manifest.ts 를 자동으로 <link rel="manifest">
// 로 걸어 주지만 그 href 에 basePath 를 붙이지 않아 '/manifest.webmanifest' 로 나간다 —
// 루트는 문서 허브라 404 이고 웹앱 설치가 이름·아이콘 없이 된다(2026-09-10 실측). 직접 지정한다.
const basePath = process.env.NEXT_PUBLIC_BASE_PATH || '';

// Pretendard GOV 폰트 (KRDS 정부 서체, local font)
const pretendard = localFont({
  src: [
    {
      path: '../fonts/PretendardGOV-Regular.subset.woff2',
      weight: '400',
      style: 'normal',
    },
    {
      path: '../fonts/PretendardGOV-Medium.subset.woff2',
      weight: '500',
      style: 'normal',
    },
    {
      // SemiBold(600) 서브셋 부재로 600~700 범위를 Bold로 렌더 — 의도적 매핑
      path: '../fonts/PretendardGOV-Bold.subset.woff2',
      weight: '600 700',
      style: 'normal',
    },
  ],
  variable: '--font-pretendard',
  display: 'swap',
  fallback: ['Pretendard', 'system-ui', '-apple-system', 'BlinkMacSystemFont', 'sans-serif'],
});

// JetBrains Mono 폰트 (코드/시간용)
const jetbrainsMono = JetBrains_Mono({
  subsets: ['latin'],
  variable: '--font-jetbrains-mono',
  display: 'swap',
});

export const metadata: Metadata = {
  title: '경기도의회 실시간 자막 서비스',
  description: '경기도의회 회의 영상에 실시간/VOD 자막을 제공하는 서비스입니다.',
  keywords: ['경기도의회', '실시간 자막', 'VOD', '회의 자막', '음성 인식'],
  authors: [{ name: '경기도의회' }],
  // 웹앱(PWA)으로 설치했을 때의 이름·표시 — manifest.ts 와 짝이다
  manifest: `${basePath}/pwa-manifest`,
  appleWebApp: { capable: true, title: '자막서비스', statusBarStyle: 'default' },
};

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  // 설치한 웹앱의 제목 표시줄 색 (의회 네이비 — design/ggc-tokens.css 정본 값)
  themeColor: '#3c5d93',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ko" className={`${pretendard.variable} ${jetbrainsMono.variable}`}>
      <body className={pretendard.className}>
        <NgrokCompat />
        <ToastProvider>
          <AuthProvider>
            <SidebarProvider>
              <BreadcrumbProvider>
                <PlatformLayout>{children}</PlatformLayout>
              </BreadcrumbProvider>
            </SidebarProvider>
          </AuthProvider>
        </ToastProvider>
      </body>
    </html>
  );
}
