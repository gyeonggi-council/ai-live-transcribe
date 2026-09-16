import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import StenographyLineEditor from '../StenographyLineEditor';

import type { StenographyLine } from '../../types';

describe('StenographyLineEditor', () => {
  const mockLine: StenographyLine = {
    id: 'line-1',
    record_id: 'record-1',
    sequence_no: 10,
    text: '테스트 내용입니다.',
    speaker: '화자 1',
    start_ms: 5000,
    end_ms: 8000,
    starts_new_paragraph: false,
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z',
  };

  const defaultProps = {
    line: mockLine,
    isActive: false,
    speakerOptions: ['화자 1', '화자 2', '화자 3'],
    onTextChange: jest.fn(),
    onSpeakerChange: jest.fn(),
    onTimingChange: jest.fn(),
    onParagraphToggle: jest.fn(),
    onSeek: jest.fn(),
    onFocus: jest.fn(),
  };

  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('renders line text', () => {
    render(<StenographyLineEditor {...defaultProps} />);

    expect(screen.getByDisplayValue('테스트 내용입니다.')).toBeInTheDocument();
  });

  it('renders sequence number', () => {
    render(<StenographyLineEditor {...defaultProps} />);

    expect(screen.getByText('10')).toBeInTheDocument();
  });

  it('renders speaker dropdown with options', () => {
    render(<StenographyLineEditor {...defaultProps} />);

    expect(screen.getByRole('option', { name: '(미지정)' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: '화자 1' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: '화자 2' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: '화자 3' })).toBeInTheDocument();
  });

  it('renders time inputs', () => {
    render(<StenographyLineEditor {...defaultProps} />);

    expect(screen.getByDisplayValue('00:05.0')).toBeInTheDocument();
    expect(screen.getByDisplayValue('00:08.0')).toBeInTheDocument();
  });

  it('calls onTextChange on blur after text edit', async () => {
    const user = userEvent.setup();
    render(<StenographyLineEditor {...defaultProps} />);

    const textarea = screen.getByTestId('steno-text-line-1');
    await user.clear(textarea);
    await user.type(textarea, '새로운 텍스트');
    await user.tab();

    expect(defaultProps.onTextChange).toHaveBeenCalledWith('line-1', '새로운 텍스트');
  });

  it('calls onSpeakerChange on dropdown change', async () => {
    const user = userEvent.setup();
    render(<StenographyLineEditor {...defaultProps} />);

    const speakerSelect = screen.getByTestId('steno-speaker-line-1');
    await user.selectOptions(speakerSelect, '화자 2');

    expect(defaultProps.onSpeakerChange).toHaveBeenCalledWith('line-1', '화자 2');
  });

  it('calls onSeek when start time clicked', async () => {
    const user = userEvent.setup();
    render(<StenographyLineEditor {...defaultProps} />);

    await user.click(screen.getByTitle('시작 시점으로 이동'));

    expect(defaultProps.onSeek).toHaveBeenCalledWith(5000);
  });

  it('calls onParagraphToggle on paragraph button click', async () => {
    const user = userEvent.setup();
    render(<StenographyLineEditor {...defaultProps} />);

    await user.click(screen.getByTestId('steno-paragraph-line-1'));

    expect(defaultProps.onParagraphToggle).toHaveBeenCalledWith('line-1', true);
  });

  it('shows active styling when isActive', () => {
    render(<StenographyLineEditor {...defaultProps} isActive />);

    expect(screen.getByTestId('steno-line-line-1')).toHaveClass('bg-primary-5');
  });

  it('shows paragraph break border when starts_new_paragraph', () => {
    render(
      <StenographyLineEditor
        {...defaultProps}
        line={{ ...mockLine, starts_new_paragraph: true }}
      />
    );

    expect(screen.getByTestId('steno-line-line-1')).toHaveClass('border-t-2');
  });
});
