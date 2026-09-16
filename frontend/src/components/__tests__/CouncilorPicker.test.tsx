import React from 'react';

import { fireEvent, render, screen, waitFor } from '@testing-library/react';

import type { CouncilorType } from '@/types';

import CouncilorPicker from '../CouncilorPicker';


const mockCouncilors: CouncilorType[] = [
  {
    id: 'c1',
    name: '김의원',
    party: '민주당',
    district: '수원시',
    term: 11,
    is_active: true,
    mi_code: 'M001',
    profile_image_url: null,
    committees: [],
    office_number: null,
    synced_at: null,
    name_english: null,
    name_chinese: null,
    district_detail: null,
    email: null,
  },
  {
    id: 'c2',
    name: '이의원',
    party: '국민의힘',
    district: '성남시',
    term: 11,
    is_active: true,
    mi_code: 'M002',
    profile_image_url: 'https://example.com/photo.jpg',
    committees: [{ name: '보건복지위원회', role: '위원' }],
    office_number: null,
    synced_at: null,
    name_english: null,
    name_chinese: null,
    district_detail: null,
    email: null,
  },
];

const mockGetCouncilors = jest.fn();
jest.mock('@/lib/api', () => ({
  getCouncilors: (...args: unknown[]) => mockGetCouncilors(...args),
}));

describe('CouncilorPicker', () => {
  const defaultProps = {
    value: '',
    onChange: jest.fn(),
  };

  beforeEach(() => {
    jest.clearAllMocks();
    mockGetCouncilors.mockResolvedValue(mockCouncilors);
  });

  it('renders input with placeholder', () => {
    render(<CouncilorPicker {...defaultProps} />);
    expect(screen.getByPlaceholderText('화자 선택 또는 입력')).toBeInTheDocument();
  });

  it('shows dropdown on focus', async () => {
    render(<CouncilorPicker {...defaultProps} />);

    const input = screen.getByPlaceholderText('화자 선택 또는 입력');
    fireEvent.focus(input);

    await waitFor(() => {
      expect(screen.getByText('(화자 미지정)')).toBeInTheDocument();
    });
  });

  it('shows councilor list with names', async () => {
    render(<CouncilorPicker {...defaultProps} />);

    const input = screen.getByPlaceholderText('화자 선택 또는 입력');
    fireEvent.focus(input);

    await waitFor(() => {
      expect(screen.getByText('김의원')).toBeInTheDocument();
      expect(screen.getByText('이의원')).toBeInTheDocument();
    });
  });

  it('shows party info for councilors', async () => {
    render(<CouncilorPicker {...defaultProps} />);

    const input = screen.getByPlaceholderText('화자 선택 또는 입력');
    fireEvent.focus(input);

    await waitFor(() => {
      expect(screen.getByText('(민주당)')).toBeInTheDocument();
      expect(screen.getByText('(국민의힘)')).toBeInTheDocument();
    });
  });

  it('calls onChange with councilor name on selection', async () => {
    render(<CouncilorPicker {...defaultProps} />);

    const input = screen.getByPlaceholderText('화자 선택 또는 입력');
    fireEvent.focus(input);

    await waitFor(() => {
      expect(screen.getByText('김의원')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText('김의원'));
    expect(defaultProps.onChange).toHaveBeenCalledWith('김의원', mockCouncilors[0]);
  });

  it('allows direct text input', () => {
    render(<CouncilorPicker {...defaultProps} />);

    const input = screen.getByPlaceholderText('화자 선택 또는 입력');
    fireEvent.change(input, { target: { value: '외부 발언자' } });
    fireEvent.keyDown(input, { key: 'Enter' });

    expect(defaultProps.onChange).toHaveBeenCalledWith('외부 발언자');
  });

  it('calls onChange with empty string for unassigned option', async () => {
    render(<CouncilorPicker {...defaultProps} value="김의원" />);

    const input = screen.getByPlaceholderText('화자 선택 또는 입력');
    fireEvent.focus(input);

    await waitFor(() => {
      expect(screen.getByText('(화자 미지정)')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText('(화자 미지정)'));
    expect(defaultProps.onChange).toHaveBeenCalledWith('');
  });
});
