import React from 'react';

import { fireEvent, render, screen } from '@testing-library/react';

import type { CouncilorType, SubtitleType } from '@/types';

import ProseTranscriptEditor from '../ProseTranscriptEditor';


// Mock CouncilorPicker
jest.mock('../CouncilorPicker', () => {
  return function MockCouncilorPicker({
    value,
    onChange,
  }: {
    value: string;
    onChange: (speaker: string) => void;
  }) {
    return (
      <input
        data-testid="mock-councilor-picker"
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    );
  };
});

// Mock API
jest.mock('@/lib/api', () => ({
  getCouncilors: jest.fn().mockResolvedValue([]),
}));

const mockSubtitles: SubtitleType[] = [
  {
    id: 'sub-1',
    meeting_id: 'meeting-1',
    start_time: 0,
    end_time: 10,
    text: '안녕하세요.',
    speaker: '김의원',
    confidence: 0.9,
    created_at: '2026-01-01',
  },
  {
    id: 'sub-2',
    meeting_id: 'meeting-1',
    start_time: 10,
    end_time: 20,
    text: '오늘 회의를 시작하겠습니다.',
    speaker: '김의원',
    confidence: 0.85,
    created_at: '2026-01-01',
  },
  {
    id: 'sub-3',
    meeting_id: 'meeting-1',
    start_time: 20,
    end_time: 30,
    text: '네, 감사합니다.',
    speaker: '이의원',
    confidence: 0.88,
    created_at: '2026-01-01',
  },
];

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
  },
];

// jsdom doesn't support scrollIntoView
beforeAll(() => {
  Element.prototype.scrollIntoView = jest.fn();
});

describe('ProseTranscriptEditor', () => {
  const defaultProps = {
    subtitles: mockSubtitles,
    currentTime: 5,
    councilors: mockCouncilors,
    onTextChange: jest.fn(),
    onSpeakerChange: jest.fn(),
    onSeek: jest.fn(),
  };

  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('renders the editor container', () => {
    render(<ProseTranscriptEditor {...defaultProps} />);
    expect(screen.getByTestId('prose-transcript-editor')).toBeInTheDocument();
  });

  it('groups subtitles by speaker into paragraphs', () => {
    render(<ProseTranscriptEditor {...defaultProps} />);

    // 같은 화자 연속 → 하나의 문단 (김의원 sub-1 + sub-2)
    // 다른 화자 → 새 문단 (이의원 sub-3)
    const paragraphs = screen.getAllByTestId(/^prose-paragraph-/);
    expect(paragraphs.length).toBe(2); // 김의원 문단 + 이의원 문단
  });

  it('concatenates text for same-speaker paragraphs', () => {
    render(<ProseTranscriptEditor {...defaultProps} />);

    const firstParagraph = screen.getByTestId('prose-paragraph-0');
    expect(firstParagraph).toHaveValue(
      '안녕하세요. 오늘 회의를 시작하겠습니다.'
    );
  });

  it('shows empty state when no subtitles', () => {
    render(<ProseTranscriptEditor {...defaultProps} subtitles={[]} />);
    expect(screen.getByText('자막이 없습니다.')).toBeInTheDocument();
  });

  it('calls onSeek when time button is clicked', () => {
    render(<ProseTranscriptEditor {...defaultProps} />);

    const timeButton = screen.getByText('00:00 ~ 00:20');
    fireEvent.click(timeButton);
    expect(defaultProps.onSeek).toHaveBeenCalledWith(0);
  });

  it('calls onTextChange when editing paragraph text', () => {
    render(<ProseTranscriptEditor {...defaultProps} />);

    const textarea = screen.getByTestId('prose-paragraph-0');
    fireEvent.change(textarea, { target: { value: '수정된 텍스트입니다.' } });

    expect(defaultProps.onTextChange).toHaveBeenCalled();
  });
});
