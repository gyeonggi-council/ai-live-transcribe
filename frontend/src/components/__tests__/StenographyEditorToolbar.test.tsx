import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import StenographyEditorToolbar from '../StenographyEditorToolbar';

import type { StenographyRecord } from '../../types';

describe('StenographyEditorToolbar', () => {
  const mockRecord: StenographyRecord = {
    id: 'rec-1',
    meeting_id: 'meeting-1',
    content: '테스트 내용',
    stenographer_name: '홍길동',
    status: 'draft',
    file_path: null,
    filename: null,
    file_size: null,
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z',
  };

  const defaultProps = {
    record: mockRecord,
    isDirty: false,
    isSaving: false,
    lineCount: 42,
    onSave: jest.fn(),
    onImportFromText: jest.fn(),
    onImportFromSubtitles: jest.fn(),
    onToggleFindReplace: jest.fn(),
    onToggleComparison: jest.fn(),
    isComparisonOpen: false,
    onBack: jest.fn(),
  };

  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('renders toolbar with basic info', () => {
    render(<StenographyEditorToolbar {...defaultProps} />);

    expect(screen.getByText('속기록 편집')).toBeInTheDocument();
    expect(screen.getByText(/홍길동/)).toBeInTheDocument();
    expect(screen.getByText('42줄')).toBeInTheDocument();
  });

  it('renders status badge', () => {
    render(<StenographyEditorToolbar {...defaultProps} />);

    expect(screen.getByText('임시')).toBeInTheDocument();
  });

  it('save button disabled when not dirty', () => {
    render(<StenographyEditorToolbar {...defaultProps} />);

    expect(screen.getByTestId('steno-save-btn')).toBeDisabled();
  });

  it('save button enabled when dirty', () => {
    render(<StenographyEditorToolbar {...defaultProps} isDirty />);

    const saveButton = screen.getByTestId('steno-save-btn');
    expect(saveButton).not.toBeDisabled();
    expect(saveButton).toHaveTextContent('● 저장');
  });

  it('calls onSave when save clicked', async () => {
    const user = userEvent.setup();
    render(<StenographyEditorToolbar {...defaultProps} isDirty />);

    await user.click(screen.getByTestId('steno-save-btn'));

    expect(defaultProps.onSave).toHaveBeenCalledTimes(1);
  });

  it('shows import dropdown on click', async () => {
    const user = userEvent.setup();
    render(<StenographyEditorToolbar {...defaultProps} />);

    await user.click(screen.getByRole('button', { name: /가져오기/i }));

    expect(screen.getByRole('button', { name: '텍스트에서 가져오기' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'STT 자막에서 가져오기' })).toBeInTheDocument();
  });

  it('calls onImportFromText from dropdown', async () => {
    const user = userEvent.setup();
    render(<StenographyEditorToolbar {...defaultProps} />);

    await user.click(screen.getByRole('button', { name: /가져오기/i }));
    await user.click(screen.getByRole('button', { name: '텍스트에서 가져오기' }));

    expect(defaultProps.onImportFromText).toHaveBeenCalledTimes(1);
  });

  it('calls onImportFromSubtitles from dropdown', async () => {
    const user = userEvent.setup();
    render(<StenographyEditorToolbar {...defaultProps} />);

    await user.click(screen.getByRole('button', { name: /가져오기/i }));
    await user.click(screen.getByRole('button', { name: 'STT 자막에서 가져오기' }));

    expect(defaultProps.onImportFromSubtitles).toHaveBeenCalledTimes(1);
  });

  it('calls onBack when back button clicked', async () => {
    const user = userEvent.setup();
    render(<StenographyEditorToolbar {...defaultProps} />);

    await user.click(screen.getByRole('button', { name: '돌아가기' }));

    expect(defaultProps.onBack).toHaveBeenCalledTimes(1);
  });

  it('calls onToggleComparison', async () => {
    const user = userEvent.setup();
    render(<StenographyEditorToolbar {...defaultProps} />);

    await user.click(screen.getByTestId('steno-compare-btn'));

    expect(defaultProps.onToggleComparison).toHaveBeenCalledTimes(1);
  });
});
