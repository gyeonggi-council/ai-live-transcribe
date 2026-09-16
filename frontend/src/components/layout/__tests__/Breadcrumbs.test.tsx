import React from 'react';

import { render, screen } from '@testing-library/react';

let mockPathname = '/';

jest.mock('next/navigation', () => ({
  usePathname: () => mockPathname,
}));

jest.mock('@/contexts/BreadcrumbContext', () => ({
  useBreadcrumb: () => ({
    dynamicTitle: null,
    setTitle: jest.fn(),
  }),
}));

import Breadcrumbs from '../Breadcrumbs';

describe('Breadcrumbs', () => {
  it('renders nothing for / (home has no breadcrumbs)', () => {
    mockPathname = '/';
    const { container } = render(<Breadcrumbs />);
    expect(container.innerHTML).toBe('');
  });

  it('renders live breadcrumb for /live', () => {
    mockPathname = '/live';
    render(<Breadcrumbs />);
    expect(screen.getByText('실시간 방송')).toBeInTheDocument();
  });

  it('renders vod breadcrumb for /vod', () => {
    mockPathname = '/vod';
    render(<Breadcrumbs />);
    expect(screen.getByText('회의 목록')).toBeInTheDocument();
  });

  it('renders bills breadcrumb for /bills', () => {
    mockPathname = '/bills';
    render(<Breadcrumbs />);
    expect(screen.getByText('의안 목록')).toBeInTheDocument();
  });

  it('renders search breadcrumb for /search', () => {
    mockPathname = '/search';
    render(<Breadcrumbs />);
    expect(screen.getByText('검색')).toBeInTheDocument();
  });

  it('renders admin breadcrumb for /admin', () => {
    mockPathname = '/admin';
    render(<Breadcrumbs />);
    expect(screen.getByText('시스템 상태')).toBeInTheDocument();
  });

  it('renders dynamic VOD detail breadcrumb', () => {
    mockPathname = '/vod/some-id';
    render(<Breadcrumbs />);
    expect(screen.getByText('VOD 상세')).toBeInTheDocument();
  });

  it('renders edit breadcrumb for /vod/[id]/edit', () => {
    mockPathname = '/vod/some-id/edit';
    render(<Breadcrumbs />);
    expect(screen.getByText('자막 편집')).toBeInTheDocument();
  });

  it('renders verify breadcrumb for /vod/[id]/verify', () => {
    mockPathname = '/vod/some-id/verify';
    render(<Breadcrumbs />);
    expect(screen.getByText('자막 검증')).toBeInTheDocument();
  });

  it('renders speaker breadcrumb for /vod/[id]/speaker', () => {
    mockPathname = '/vod/some-id/speaker';
    render(<Breadcrumbs />);
    expect(screen.getByText('화자 식별')).toBeInTheDocument();
  });
});
