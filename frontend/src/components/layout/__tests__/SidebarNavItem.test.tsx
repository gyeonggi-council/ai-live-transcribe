import React from 'react';

import { render, screen } from '@testing-library/react';

let mockPathname = '/';

jest.mock('next/navigation', () => ({
  usePathname: () => mockPathname,
}));

import type { NavModule } from '@/config/navigation';

import SidebarNavItem from '../SidebarNavItem';

const sparklesModule: NavModule = {
  id: 'ai-assistant',
  label: 'AI 어시스턴트',
  icon: 'sparkles',
  items: [{ id: 'ai-chat', label: 'AI 질의응답', href: '/ai' }],
};

const documentDuplicateModule: NavModule = {
  id: 'stenography-mgmt',
  label: '속기관리',
  icon: 'document-duplicate',
  items: [{ id: 'steno-dashboard', label: '속기록 대시보드', href: '/stenography' }],
};

describe('SidebarNavItem', () => {
  it('renders sparkles icon for AI 어시스턴트 module (ICON_PATHS 등록 확인)', () => {
    mockPathname = '/';
    const { container } = render(
      <SidebarNavItem module={sparklesModule} collapsed={false} />,
    );
    // NavIcon(strokeWidth 1.5)이 렌더링되어야 함 — ICON_PATHS 누락 시 null 반환으로 미표시
    expect(container.querySelector('svg[stroke-width="1.5"] path[d]')).not.toBeNull();
  });

  it('renders document-duplicate icon for 속기관리 module (ICON_PATHS 등록 확인)', () => {
    mockPathname = '/';
    const { container } = render(
      <SidebarNavItem module={documentDuplicateModule} collapsed={false} />,
    );
    expect(container.querySelector('svg[stroke-width="1.5"] path[d]')).not.toBeNull();
  });

  it('applies KRDS active styles (bg-primary-5 + primary bar) to active sub item', () => {
    mockPathname = '/ai';
    render(<SidebarNavItem module={sparklesModule} collapsed={false} />);
    // 자식이 하나뿐인 모듈은 직행 링크라, 눌리는 글자는 자식 이름이 아니라
    // 모듈 이름이다 (2026-08-25 개선안 2c — 아코디언 제거).
    const link = screen.getByText('AI 어시스턴트').closest('a');
    expect(link).not.toBeNull();
    expect(link!.className).toContain('bg-primary-5');
    expect(link!.className).toContain('text-primary-dark');
    expect(link!).toHaveAttribute('aria-current', 'page');
  });
});
