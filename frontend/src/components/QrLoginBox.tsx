'use client';

import { useEffect, useRef, useState } from 'react';

import { QRCodeSVG } from 'qrcode.react';

import { createQrSession, pollQrSession } from '@/lib/auth';
import type { TokenResponse } from '@/lib/auth';

// 설치 QR 은 정적 자산이라 basePath 프리픽스를 직접 붙인다 —
// next/image 와 달리 <img> 에는 Next 가 붙여 주지 않는다(k3s 는 /transcribe 프리픽스).
const INSTALL_QR_SRC = `${process.env.NEXT_PUBLIC_BASE_PATH || ''}/app-install-qr.svg`;

// 모바일 의정지원서비스 앱 QR 로그인 블록 — 세션 5분 유효·1회용, 3초 폴링.
// QR payload 스키마(type/sessionId/apiUrl)는 앱이 읽는 계약이므로 바꾸지 말 것.
//
// **화면은 정본 컴포넌트 `.ggc-qr` 이다**(design/ggc-components.css §11, 2026-08-22).
// 예전에는 Tailwind 유틸리티와 이 앱의 Button/Callout 으로 직접 그렸고, 그래서
// 10개 서비스의 로그인 화면이 시각적으로 셋으로 갈렸다. 마크업 구조를 바꾸지 말 것 —
// 실물과 상태 6종은 design/examples/login.html 에서 볼 수 있다.

// 상태 이름 여섯은 플랫폼 정본이다 — 같은 뜻에 다른 이름을 만들지 말 것.
// (이 파일은 'issuing' 을 쓰고 있었다. 2026-08-22 'loading' 으로 통일)
type Phase = 'idle' | 'loading' | 'showing' | 'expired' | 'unregistered' | 'error';

type Veil = { badge: string; label: string; text: string };
const VEIL_EXPIRED: Veil = { badge: 'ggc-badge--pending', label: '만료', text: '유효시간이 지났습니다' };
const VEIL: Partial<Record<Phase, Veil>> = {
  expired: VEIL_EXPIRED,
  unregistered: { badge: 'ggc-badge--rejected', label: '미등록', text: '계정이 없습니다' },
  error: { badge: 'ggc-badge--rejected', label: '오류', text: '잠시 후 다시 시도해 주세요' },
};

function mmss(sec: number) {
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return `${m}:${s < 10 ? '0' : ''}${s}`;
}

interface QrLoginBoxProps {
  onSuccess: (res: TokenResponse) => void;
  /** SSO 교환이 unregistered(403)로 끝났을 때 QR unregistered 와 같은 화면으로 시작한다.
      마운트 시 초기값으로만 쓰인다 — 나중에 바꾸려면 key 로 리마운트할 것. */
  initialPhase?: 'unregistered';
  initialMessage?: string | null;
  initialUsercode?: string | null;
}

export default function QrLoginBox({
  onSuccess,
  initialPhase,
  initialMessage,
  initialUsercode,
}: QrLoginBoxProps) {
  const [phase, setPhase] = useState<Phase>(initialPhase ?? 'idle');
  const [payload, setPayload] = useState('');
  const [message, setMessage] = useState<string | null>(initialMessage ?? null);
  const [usercode, setUsercode] = useState<string | null>(initialUsercode ?? null);
  const [remain, setRemain] = useState(0);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);
  const ticker = useRef<ReturnType<typeof setInterval> | null>(null);

  function stop() {
    if (timer.current) clearInterval(timer.current);
    if (ticker.current) clearInterval(ticker.current);
    timer.current = null;
    ticker.current = null;
  }
  useEffect(() => stop, []);

  // 접속하자마자 QR 을 판다(2026-08-28 사용자 결정) — "QR 로그인 시작" 을 한 번 더 누르게
  // 할 이유가 없다. ref 가드: React 개발 모드는 effect 를 두 번 돌리는데 상류 QR 세션은
  // 5분·1회용이라 두 번 발급하면 첫 장이 그대로 버려진다.
  // 미등록으로 되돌아온 참(initialPhase)이면 그 상태를 보여야 하므로 건너뛴다.
  const autoStarted = useRef(false);
  useEffect(() => {
    if (autoStarted.current || initialPhase) return;
    autoStarted.current = true;
    void start();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function start() {
    stop();
    setPhase('loading');
    setMessage(null);
    setUsercode(null);

    let session;
    try {
      session = await createQrSession();
    } catch (err) {
      setPhase('error');
      setMessage(err instanceof Error ? err.message : 'QR 세션 발급에 실패했습니다');
      return;
    }

    setPayload(
      JSON.stringify({ type: 'ggc_qr_login', sessionId: session.sessionId, apiUrl: session.apiUrl }),
    );
    setPhase('showing');
    const ttl = session.ttl || 300;
    const deadline = Date.now() + ttl * 1000;
    const { sessionId } = session;
    setRemain(ttl);

    // 남은 시간을 눈으로 보여 준다 — QR 은 5분·1회용이라 사용자가 "지금 이게
    // 살아 있나" 를 알아야 한다.
    ticker.current = setInterval(() => {
      setRemain(Math.max(0, Math.ceil((deadline - Date.now()) / 1000)));
    }, 1000);

    timer.current = setInterval(async () => {
      if (Date.now() > deadline) {
        stop();
        setPhase('expired');
        return;
      }
      try {
        const d = await pollQrSession(sessionId);
        if (d.status === 'authenticated') {
          stop();
          onSuccess(d);
        } else if (d.status === 'expired') {
          stop();
          setPhase('expired');
        } else if (d.status === 'unregistered') {
          stop();
          setPhase('unregistered');
          setMessage(
            (d.detail ?? '인증은 완료됐지만 이 서비스에 등록된 계정이 없습니다.') +
              (d.user_name ? ` (${d.user_name})` : ''),
          );
          setUsercode(d.usercode ?? null);
        }
        // pending 은 계속 폴링
      } catch {
        // 일시적 네트워크/중계 오류는 다음 폴링에서 재시도
      }
    }, 3000);
  }

  const veil = VEIL[phase] ?? VEIL_EXPIRED;
  const meta =
    phase === 'loading'
      ? 'QR 을 준비하고 있습니다…'
      : phase === 'idle'
        ? 'QR 은 발급 후 5분간 유효하며 1회만 사용됩니다'
        : null;
  const action =
    phase === 'idle'
      ? '모바일 의정지원서비스 앱 QR 로그인'
      : phase === 'loading' || phase === 'showing'
        ? null
        : phase === 'error'
          ? '다시 시도'
          : '새 QR 발급';

  return (
    <div className="ggc-qr">
      {/* 왼쪽: 찍는 것 — 900px 이상에서 2단이 된다(ggc-components.css §11 v1.3) */}
      <div className="ggc-qr-main">
      <div className="ggc-qr-stage" data-state={phase} role="status" aria-live="polite">
        <div className="ggc-qr-frame">
          {/* 크기·오류정정 레벨은 명세 3.2 권장값(200px·level M) — 앱 스캔 인식률 확보용이라 줄이지 말 것 */}
          {payload ? <QRCodeSVG value={payload} size={200} level="M" marginSize={2} /> : null}
        </div>
        <div className="ggc-qr-spinner" />
        <div className="ggc-qr-veil">
          <span className={`ggc-badge ${veil.badge}`}>{veil.label}</span>
          <p className="ggc-qr-veil-text">{veil.text}</p>
        </div>
      </div>

      {phase === 'showing' ? (
        <p className="ggc-qr-meta">
          남은 시간 <span className="ggc-qr-timer">{mmss(remain)}</span> · 이 코드는 1회용입니다
        </p>
      ) : meta ? (
        <p className="ggc-qr-meta">{meta}</p>
      ) : null}
      </div>

      {/* 오른쪽: 읽는 것 */}
      <div className="ggc-qr-aside">
      {/* 머리는 정본상 aside 의 첫 자식이다(§11 마크업 계약). 2단에서 왼쪽 정렬이 되고,
          한 줄로 쌓일 때는 가운데 정렬로 돌아간다 — 페이지가 따로 제목을 그리면
          같은 말이 두 번 나오므로 여기 하나만 둔다. */}
      <div className="ggc-qr-head">
        <p className="ggc-qr-eyebrow">경기도의회사무처 · 실시간 자막</p>
        <h1 className="ggc-qr-title">모바일 의정지원서비스 앱으로 로그인</h1>
        <p className="ggc-qr-lead">이 서비스는 앱 QR 로그인만 지원합니다.</p>
      </div>

      <ol className="ggc-qr-steps">
        <li>
          휴대폰에서 <strong>모바일 의정지원서비스</strong> 앱을 실행합니다
        </li>
        <li>
          앱 메뉴에서 <strong>QR 로그인</strong>을 선택합니다
        </li>
        <li>위 코드를 화면에 맞춰 스캔합니다</li>
      </ol>
      <details className="ggc-qr-install">
        <summary>앱이 없으신가요? 설치하기</summary>
        <div className="ggc-qr-install-body">
          <div className="ggc-qr-install-qr">
            <img src={INSTALL_QR_SRC} alt="모바일 의정지원서비스 앱 설치 QR 코드" width={120} height={120} />
          </div>
          <p className="ggc-qr-install-url">
            휴대폰 카메라로 QR 을 찍거나 아래 주소로 접속하세요.
            <br />
            <a href="https://magent.ggc.go.kr/app/download">magent.ggc.go.kr/app/download</a>
          </p>
          <p className="ggc-qr-install-stores">
            <a href="https://play.google.com/store/apps/details?id=kr.go.ggc.portal.app">Google Play</a>
            <a href="https://apps.apple.com/kr/app/%EA%B2%BD%EA%B8%B0%EB%8F%84%EC%9D%98%ED%9A%8C-%EB%AA%A8%EB%B0%94%EC%9D%BC-%EC%9D%98%EC%A0%95%EC%A7%80%EC%9B%90%EC%84%9C%EB%B9%84%EC%8A%A4/id6788616270">App Store</a>
          </p>
        </div>
      </details>

      {message ? (
        <p className="ggc-qr-callout ggc-qr-callout--danger" role="alert">
          {message}
        </p>
      ) : null}
      {usercode ? <p className="ggc-qr-usercode">{usercode}</p> : null}

      {action ? (
        <div className="ggc-qr-actions">
          <button
            type="button"
            className="ggc-btn ggc-btn--secondary ggc-btn--block"
            onClick={start}
          >
            {action}
          </button>
        </div>
      ) : null}
      </div>
    </div>
  );
}
