/**
 * StenographyAiPanel 테스트
 *
 * @TASK P11C-T12.2 - AI 보조 패널 테스트
 * @TEST frontend/src/components/__tests__/StenographyAiPanel.test.tsx
 */

import React from 'react';

import { render, screen, fireEvent, waitFor } from '@testing-library/react';

const mockAiDetectSpeakers = jest.fn();
const mockAiProofread = jest.fn();
const mockAiDetectParagraphs = jest.fn();

jest.mock('../../lib/api', () => ({
  aiDetectSpeakers: (...args: unknown[]) => mockAiDetectSpeakers(...args),
  aiProofread: (...args: unknown[]) => mockAiProofread(...args),
  aiDetectParagraphs: (...args: unknown[]) => mockAiDetectParagraphs(...args),
}));

import StenographyAiPanel from '../StenographyAiPanel';

describe('StenographyAiPanel', () => {
  const defaultProps = {
    meetingId: 'meeting-1',
    recordId: 'record-1',
    isOpen: true,
    onToggle: jest.fn(),
    onApplySpeakers: jest.fn(),
    onApplyProofread: jest.fn(),
    onApplyParagraphs: jest.fn(),
  };

  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('renders with three AI action buttons when open', () => {
    render(<StenographyAiPanel {...defaultProps} />);

    expect(screen.getByRole('button', { name: /화자 자동 구분/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /맞춤법 교정/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /문단 구분/i })).toBeInTheDocument();
  });

  it('calls aiDetectSpeakers when speaker button clicked', async () => {
    mockAiDetectSpeakers.mockResolvedValue({
      suggestions: [
        { line_id: 'line-1', suggested_speaker: 'Kim' },
      ],
      count: 1,
    });

    render(<StenographyAiPanel {...defaultProps} />);

    const btn = screen.getByRole('button', { name: /화자 자동 구분/i });
    fireEvent.click(btn);

    await waitFor(() => {
      expect(mockAiDetectSpeakers).toHaveBeenCalledWith('meeting-1', 'record-1');
    });
  });

  it('calls aiProofread when proofread button clicked', async () => {
    mockAiProofread.mockResolvedValue({
      corrections: [
        { line_id: 'line-1', original_text: 'old', corrected_text: 'new', changes: ['fix'] },
      ],
      count: 1,
    });

    render(<StenographyAiPanel {...defaultProps} />);

    const btn = screen.getByRole('button', { name: /맞춤법 교정/i });
    fireEvent.click(btn);

    await waitFor(() => {
      expect(mockAiProofread).toHaveBeenCalledWith('meeting-1', 'record-1');
    });
  });

  it('does not render content when closed', () => {
    render(<StenographyAiPanel {...defaultProps} isOpen={false} />);

    expect(screen.queryByRole('button', { name: /화자 자동 구분/i })).not.toBeInTheDocument();
  });
});
