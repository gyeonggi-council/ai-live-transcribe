/**
 * 속기사 대시보드 페이지 테스트
 *
 * @TASK P11C-T12.1 - 속기사 대시보드 테스트
 * @TEST frontend/src/app/stenography/__tests__/page.test.tsx
 */

import React from 'react';

import { render, screen, fireEvent, waitFor } from '@testing-library/react';

// Mock dependencies
jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: jest.fn() }),
  usePathname: () => '/stenography',
}));

const mockSetTitle = jest.fn();
jest.mock('../../../contexts/BreadcrumbContext', () => ({
  useBreadcrumb: () => ({ setTitle: mockSetTitle }),
}));

const mockGetAllStenographyRecords = jest.fn();
jest.mock('../../../lib/api', () => ({
  getAllStenographyRecords: (...args: unknown[]) => mockGetAllStenographyRecords(...args),
}));

import StenographyDashboardPage from '../page';

describe('StenographyDashboardPage', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockGetAllStenographyRecords.mockResolvedValue({
      items: [],
      total: 0,
    });
  });

  it('renders the dashboard with tab buttons', async () => {
    render(<StenographyDashboardPage />);

    await waitFor(() => {
      expect(screen.getByText('속기록 대시보드')).toBeInTheDocument();
    });

    // Stats cards + tab buttons both contain these labels (2 each)
    expect(screen.getAllByText(/대기/i).length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByText(/진행중/i).length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByText(/완료/i).length).toBeGreaterThanOrEqual(2);
  });

  it('loads records on mount', async () => {
    mockGetAllStenographyRecords.mockResolvedValue({
      items: [
        {
          id: 'rec-1',
          meeting_id: 'm-1',
          content: 'test content',
          stenographer_name: 'Kim',
          status: 'draft',
          file_path: null,
          filename: null,
          file_size: null,
          created_at: '2026-03-19T00:00:00Z',
          updated_at: '2026-03-19T00:00:00Z',
        },
      ],
      total: 1,
    });

    render(<StenographyDashboardPage />);

    await waitFor(() => {
      expect(mockGetAllStenographyRecords).toHaveBeenCalled();
    });
  });

  it('switches tabs when clicked', async () => {
    render(<StenographyDashboardPage />);

    await waitFor(() => {
      expect(screen.getByText('속기록 대시보드')).toBeInTheDocument();
    });

    // Click the tab buttons (border-b-2 style tabs) - they include count text like "진행중 (0)"
    const submittedTabs = screen.getAllByText(/진행중/i);
    // Click the last one (the tab button, not the stat card)
    fireEvent.click(submittedTabs[submittedTabs.length - 1]);

    await waitFor(() => {
      expect(mockGetAllStenographyRecords).toHaveBeenCalledWith('submitted', 50, 0);
    });
  });

  it('shows empty state when no records', async () => {
    mockGetAllStenographyRecords.mockResolvedValue({ items: [], total: 0 });

    render(<StenographyDashboardPage />);

    await waitFor(() => {
      expect(screen.getByText(/등록된 속기록이 없습니다/i)).toBeInTheDocument();
    });
  });
});
