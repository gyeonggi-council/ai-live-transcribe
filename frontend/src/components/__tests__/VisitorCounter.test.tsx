import { render, screen, waitFor } from '@testing-library/react';

import { getVisitorStats, recordVisit } from '@/lib/api';

import VisitorCounter from '../VisitorCounter';

jest.mock('@/lib/api', () => ({
  getVisitorStats: jest.fn(),
  recordVisit: jest.fn(),
}));

const mockGet = getVisitorStats as jest.Mock;
const mockRecord = recordVisit as jest.Mock;

describe('VisitorCounter', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    window.localStorage.clear();
  });

  it('오늘 첫 접속이면 recordVisit를 호출하고 오늘/누적을 표시한다', async () => {
    mockRecord.mockResolvedValue({ today: 12, total: 3456 });

    render(<VisitorCounter />);

    await waitFor(() => expect(screen.getByTestId('visitor-counter')).toBeInTheDocument());
    expect(mockRecord).toHaveBeenCalledTimes(1);
    expect(mockGet).not.toHaveBeenCalled();
    // 천단위 콤마 포맷
    expect(screen.getByText('12')).toBeInTheDocument();
    expect(screen.getByText('3,456')).toBeInTheDocument();
  });

  it('오늘 이미 방문했으면 recordVisit 대신 getVisitorStats만 호출한다', async () => {
    const d = new Date();
    const key = `ggc_visit_${d.getFullYear()}-${`${d.getMonth() + 1}`.padStart(2, '0')}-${`${d.getDate()}`.padStart(2, '0')}`;
    window.localStorage.setItem(key, '1');
    mockGet.mockResolvedValue({ today: 5, total: 100 });

    render(<VisitorCounter />);

    await waitFor(() => expect(screen.getByTestId('visitor-counter')).toBeInTheDocument());
    expect(mockGet).toHaveBeenCalledTimes(1);
    expect(mockRecord).not.toHaveBeenCalled();
    expect(screen.getByText('5')).toBeInTheDocument();
    expect(screen.getByText('100')).toBeInTheDocument();
  });

  it('첫 접속 집계 후 localStorage에 오늘 방문 플래그를 남긴다', async () => {
    mockRecord.mockResolvedValue({ today: 1, total: 1 });

    render(<VisitorCounter />);

    await waitFor(() => expect(screen.getByTestId('visitor-counter')).toBeInTheDocument());
    const d = new Date();
    const key = `ggc_visit_${d.getFullYear()}-${`${d.getMonth() + 1}`.padStart(2, '0')}-${`${d.getDate()}`.padStart(2, '0')}`;
    expect(window.localStorage.getItem(key)).toBe('1');
  });

  it('누르면 접속 통계 화면으로 간다 (2026-09-16)', async () => {
    mockRecord.mockResolvedValue({ today: 12, total: 3456 });

    render(<VisitorCounter />);

    const counter = await screen.findByTestId('visitor-counter');
    expect(counter.tagName).toBe('A');
    expect(counter).toHaveAttribute('href', '/visits');
  });

  it('집계 실패 시 아무것도 렌더링하지 않는다', async () => {
    mockRecord.mockRejectedValue(new Error('network'));

    const { container } = render(<VisitorCounter />);

    await waitFor(() => expect(mockRecord).toHaveBeenCalled());
    expect(screen.queryByTestId('visitor-counter')).not.toBeInTheDocument();
    expect(container).toBeEmptyDOMElement();
  });
});
