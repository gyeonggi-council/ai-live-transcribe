'use client';

import { useEffect, useState } from 'react';

/**
 * CSS 미디어 쿼리를 JS 에서도 읽는다.
 *
 * 쓰는 자리는 **CSS 로는 못 하는 분기**뿐이다 — 예를 들어 실시간 자막 화면에서
 * '지금 발언'을 PC 는 영상 아래 카드로, 모바일은 목록 마지막 줄로 두는데, 두 벌을
 * `hidden lg:block` 으로 깔면 같은 자막이 DOM 에 두 번 들어가 스크린리더가
 * 같은 발언을 두 번 읽는다 (2026-08-25 개선안 2e).
 *
 * SSR 에는 `matchMedia` 가 없으므로 첫 렌더는 항상 `false` 다. 즉 **모바일 쪽이
 * 기본값**이며, 마운트 직후 한 번 보정된다. 반대로 두면 좁은 화면이 잠깐 PC
 * 레이아웃으로 그려졌다 접힌다.
 */
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(false);

  useEffect(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return;

    const mql = window.matchMedia(query);
    setMatches(mql.matches);

    const onChange = (e: MediaQueryListEvent) => setMatches(e.matches);
    mql.addEventListener('change', onChange);
    return () => mql.removeEventListener('change', onChange);
  }, [query]);

  return matches;
}

/** Tailwind `lg` 중단점(1024px) — 이 저장소의 PC/모바일 경계다 */
export function useIsDesktop(): boolean {
  return useMediaQuery('(min-width: 1024px)');
}

export default useMediaQuery;
