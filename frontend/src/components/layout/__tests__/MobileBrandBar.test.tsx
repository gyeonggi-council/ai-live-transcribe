import React from 'react';

import { render, screen } from '@testing-library/react';

import MobileBrandBar from '../MobileBrandBar';

/**
 * 모바일 의회 마크 — **어디에 붙고 어디에 안 붙는가**가 이 컴포넌트의 전부다.
 * 경로만 보고 `/live` 를 통째로 빼는 바람에 채널 선택 화면에서도 마크가 사라진
 * 적이 있다(2026-08-25). 그 판단을 여기에 고정한다.
 */

let mockPath = '/';
let mockQuery = new URLSearchParams();

jest.mock('next/navigation', () => ({
  usePathname: () => mockPath,
  useSearchParams: () => mockQuery,
}));

function renderAt(path: string, query = '') {
  mockPath = path;
  mockQuery = new URLSearchParams(query);
  return render(<MobileBrandBar />);
}

describe('MobileBrandBar', () => {
  it('대시보드에 의회 마크를 보인다', () => {
    renderAt('/');
    expect(screen.getByAltText('경기도의회')).toBeInTheDocument();
    expect(screen.getByText('경기도의회')).toBeInTheDocument();
  });

  it('통합검색·회의 목록 같은 일반 화면에도 보인다', () => {
    const { unmount } = renderAt('/search');
    expect(screen.getByAltText('경기도의회')).toBeInTheDocument();
    unmount();

    renderAt('/vod');
    expect(screen.getByAltText('경기도의회')).toBeInTheDocument();
  });

  it('실시간 방송의 채널 선택 화면에는 보인다 (채널 미선택)', () => {
    renderAt('/live');
    expect(screen.getByAltText('경기도의회')).toBeInTheDocument();
  });

  it('실시간 방송을 보고 있을 때는 숨긴다 (채널 선택됨)', () => {
    const { container } = renderAt('/live', 'channel=ch8');
    expect(container).toBeEmptyDOMElement();
  });

  it('회의 상세(시청 화면)에서는 숨긴다', () => {
    const { container } = renderAt('/vod/05c71103-9e9e-47db-be26-323c3d9813f7');
    expect(container).toBeEmptyDOMElement();
  });

  it('데스크톱에서는 CSS 로 감춘다 (lg:hidden)', () => {
    const { container } = renderAt('/');
    expect(container.firstElementChild).toHaveClass('lg:hidden');
  });
});
