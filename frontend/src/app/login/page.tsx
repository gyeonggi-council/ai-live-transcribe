'use client';

import { useEffect, useRef, useState, Suspense } from 'react';

import { useRouter } from 'next/navigation';

import QrLoginBox from '@/components/QrLoginBox';
import { useAuth } from '@/contexts/AuthContext';
import { ssoExchange } from '@/lib/auth';

// @TASK P11A-S1-T3 - 로그인 페이지 (KRDS)
// @SPEC docs/planning/06-screens.md
//
// **아이디·비밀번호 로그인은 없다**(2026-08-28 사용자 결정). 들어오는 길은 두 가지뿐이다 —
// 모바일 의정지원서비스 앱 QR, 그리고 그 QR 을 한 번만 찍게 하는 플랫폼 통합 로그인(ggc_sso).
// 폼과 함께 `lib/auth.login()` · `AuthContext.login` · 백엔드 `POST /api/auth/login` ·
// 계정 5개가 평문으로 적혀 있던 `/admin/dev-login` 페이지를 전부 걷어냈다.
// (관리자 PIN 모달 `AdminPinModal` 은 로그인이 아니라 관리 기능 앞의 별도 관문이라 그대로 둔다.)
//
// **화면 셸은 정본이다** — `main.ggc-login > .ggc-card.ggc-card--pad`
// (design/ggc-components.css §11 끝). 카드는 `.ggc-login` 의 **직계 자식**이어야
// `:has(.ggc-qr-main)` 규칙이 max-width 를 820px 로 올린다. 래퍼를 끼우지 말 것 —
// 예전에는 Tailwind `Card max-w-md`(448px) 안에 있어서, 900px 이상에서 2단으로 펴진
// QR 블록이 폭 400px 에 갇혔다(왼쪽 240px + 간격 32px → 안내가 128px). 그래서
// "너무 이상해" 보였다. 넓히는 것이 곧 고치는 것이다.

// 플랫폼 통합 로그인(ggc-sso) 화면 주소 — next 로 이 로그인 페이지를 지정해,
// /sso 에서 QR 한 번 스캔하고 돌아오면 아래 자동 교환이 무스캔으로 로그인시킨다.
const SSO_LOGIN_URL = `/sso/login?next=${encodeURIComponent('/transcribe/login')}`;

/** SSO 자동 교환 결과에 따른 화면 분기 상태 */
type SsoState = 'checking' | 'none' | 'unregistered' | 'error';

function LoginPageContent() {
  const router = useRouter();
  const { adoptSession } = useAuth();

  // SSO 자동 교환 — **페이지당 1회**(무한 루프 방지). 성공·미등록 후 재시도하지 않는다.
  const [ssoState, setSsoState] = useState<SsoState>('checking');
  const [ssoUsercode, setSsoUsercode] = useState<string | null>(null);
  const ssoTried = useRef(false);

  useEffect(() => {
    if (ssoTried.current) return;
    ssoTried.current = true;
    let cancelled = false;
    ssoExchange().then((r) => {
      if (cancelled) return;
      if (r.status === 'authenticated') {
        // QR 성공과 동일 — 토큰은 ssoExchange 가 이미 저장했다
        adoptSession(r);
        router.push('/');
      } else if (r.status === 'unregistered') {
        setSsoUsercode(r.usercode ?? null);
        setSsoState('unregistered');
      } else if (r.status === 'none') {
        setSsoState('none');
      } else {
        setSsoState('error');
      }
    });
    return () => {
      cancelled = true;
    };
  }, [adoptSession, router]);

  return (
    <main className="ggc-login" id="main">
      <div className="ggc-card ggc-card--pad">
        {/* QR 로그인 (모바일 의정지원서비스 앱) — 화면은 정본 컴포넌트 .ggc-qr 이다.
            제목·안내는 그 안의 .ggc-qr-head 가 갖는다(여기서 따로 그리지 않는다).
            SSO 교환이 403(unregistered)이면 QR unregistered 와 같은 화면으로 시작한다
            — key 로 리마운트해 initial 상태를 반영한다. */}
        <QrLoginBox
          key={ssoState === 'unregistered' ? 'sso-unregistered' : 'qr'}
          initialPhase={ssoState === 'unregistered' ? 'unregistered' : undefined}
          initialMessage={
            ssoState === 'unregistered'
              ? '통합 로그인 인증은 완료됐지만 이 서비스에서 사용할 수 없는 계정입니다. 담당자에게 문의하세요.'
              : undefined
          }
          initialUsercode={ssoState === 'unregistered' ? ssoUsercode : undefined}
          onSuccess={(res) => {
            adoptSession(res);
            router.push('/');
          }}
        />

        {/* 통합 로그인 — SSO 세션이 없을 때(401)만 노출. /sso 에서 QR 한 번 스캔하면
            업무플랫폼 전 서비스가 무스캔이 된다. basePath(/transcribe) 밖이므로 raw <a>. */}
        {(ssoState === 'none' || ssoState === 'error') && (
          <div className="ggc-qr-actions tx-login-tail">
            <a className="ggc-btn ggc-btn--secondary ggc-btn--block" href={SSO_LOGIN_URL}>
              통합 로그인 (업무플랫폼 공통)
            </a>
          </div>
        )}

        {/* 비로그인 계속 — 자막 열람은 로그인 없이도 되는 것이 이 서비스의 설계다 */}
        <p className="tx-login-guest">
          <button
            type="button"
            onClick={() => router.push('/')}
            className="text-sm text-text-muted hover:text-text-secondary underline underline-offset-2 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary rounded"
          >
            비로그인으로 계속
          </button>
        </p>
      </div>
    </main>
  );
}

export default function LoginPage() {
  return (
    <Suspense>
      <LoginPageContent />
    </Suspense>
  );
}
