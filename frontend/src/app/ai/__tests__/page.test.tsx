import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

// jsdom에서 scrollIntoView 미지원
beforeAll(() => {
  Element.prototype.scrollIntoView = jest.fn();
});

import AiAssistantPage from '../page';

const mockSendMessage = jest.fn();
const mockClearMessages = jest.fn();
const mockLoadSession = jest.fn();

let mockMessages: Array<{ role: string; content: string }> = [];
let mockLoading = false;
let mockError: string | null = null;

jest.mock('@/hooks/useAiChat', () => ({
  useAiChat: () => ({
    messages: mockMessages,
    loading: mockLoading,
    error: mockError,
    rateLimited: false,
    saved: null,
    sessionId: 'test-session',
    sendMessage: mockSendMessage,
    retryLast: jest.fn(),
    clearMessages: mockClearMessages,
    loadSession: mockLoadSession,
  }),
}));

jest.mock('@/contexts/AuthContext', () => ({
  useAuth: () => ({
    user: { id: '1', username: 'admin', display_name: '관리자', role: 'admin' },
    effectiveRole: 'admin',
    councilNetwork: false,
    loading: false,
    error: null,
    login: jest.fn(),
    logout: jest.fn(),
  }),
}));

jest.mock('next/navigation', () => ({
  useSearchParams: () => new URLSearchParams(''),
}));

const MEETING = {
  id: 'm-1',
  title: '제393회 제3차 도시환경위원회',
  meeting_date: '2026-09-02',
  stream_url: null,
  vod_url: 'https://kms/x.mp4',
  status: 'ended',
  duration_seconds: 7200,
  subtitle_stage: 'ai',
  created_at: '',
  updated_at: '',
};
const NO_SUB = { ...MEETING, id: 'm-2', title: '자막 없는 회의', subtitle_stage: 'none' };

jest.mock('@/hooks/useVodList', () => ({
  useVodList: () => ({ vods: [MEETING, NO_SUB], isLoading: false, error: null, hasNext: false }),
}));

const mockGetAiConversations = jest.fn().mockResolvedValue([]);
const mockGetAiConversation = jest.fn();
jest.mock('@/lib/api', () => ({
  ApiError: class ApiError extends Error {},
  apiClient: jest.fn(),
  aiChat: jest.fn(),
  getAiConversations: (...a: unknown[]) => mockGetAiConversations(...a),
  getAiConversation: (...a: unknown[]) => mockGetAiConversation(...a),
  getSummary: jest.fn().mockRejectedValue(new Error('404')),
  generateSummary: jest.fn(),
  findClipMeetingsByMember: jest.fn().mockResolvedValue({ name: '', meeting_ids: [] }),
}));

jest.mock('next/link', () => {
  return function MockLink({ children, href }: { children: React.ReactNode; href: string }) {
    return <a href={href}>{children}</a>;
  };
});

describe('AiAssistantPage', () => {
  beforeEach(() => {
    mockMessages = [];
    mockLoading = false;
    mockError = null;
    mockSendMessage.mockClear();
    mockClearMessages.mockClear();
    mockLoadSession.mockClear();
    mockGetAiConversations.mockResolvedValue([]);
  });

  it('renders the AI assistant page with meeting list', () => {
    render(<AiAssistantPage />);
    expect(screen.getByText('AI 어시스턴트')).toBeInTheDocument();
    expect(screen.getByTestId('ai-context-chip')).toHaveTextContent('왼쪽에서 회의를 골라 주세요');
    expect(screen.getByLabelText('AI 질문 입력')).toBeDisabled();
    expect(screen.getAllByTestId('ai-meeting-row')).toHaveLength(2);
  });

  it('selecting a meeting starts a new chat bound to it and shows the brief', async () => {
    render(<AiAssistantPage />);
    await userEvent.click(screen.getByText('제393회 제3차 도시환경위원회'));
    expect(mockClearMessages).toHaveBeenCalled();
    expect(screen.getByTestId('ai-context-chip')).toHaveTextContent('제393회 제3차 도시환경위원회');
    expect(screen.getByTestId('ai-meeting-brief')).toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId('ai-brief-generate')).toBeInTheDocument());
  });

  it('a meeting without subtitles cannot be selected', async () => {
    render(<AiAssistantPage />);
    const rows = screen.getAllByTestId('ai-meeting-row');
    expect(rows[1]).toBeDisabled();
  });

  it('sends a message on Enter (textarea) and on submit', async () => {
    render(<AiAssistantPage />);
    await userEvent.click(screen.getByText('제393회 제3차 도시환경위원회'));
    const input = screen.getByLabelText('AI 질문 입력');
    await userEvent.type(input, '테스트 질문');
    await userEvent.click(screen.getByRole('button', { name: '전송' }));
    expect(mockSendMessage).toHaveBeenCalledWith('테스트 질문');

    await userEvent.type(input, '두 번째{enter}');
    expect(mockSendMessage).toHaveBeenCalledWith('두 번째');
  });

  it('sends a quick question from the brief', async () => {
    render(<AiAssistantPage />);
    await userEvent.click(screen.getByText('제393회 제3차 도시환경위원회'));
    await userEvent.click(screen.getByText('주요 결정사항은 무엇인가'));
    expect(mockSendMessage).toHaveBeenCalledWith('주요 결정사항은 무엇인가');
  });

  it('opens a previous session with its sources', async () => {
    mockGetAiConversations.mockResolvedValue([
      {
        session_id: 's-1',
        first_question: '지난 질문',
        message_count: 2,
        meeting_context_id: null,
        meeting_title: null,
        created_at: '2026-09-14T01:00:00+09:00',
        last_active_at: '2026-09-14T01:00:00+09:00',
      },
    ]);
    mockGetAiConversation.mockResolvedValue([
      { id: 'a', session_id: 's-1', role: 'user', content: '지난 질문', sources: null, meeting_context_id: null, created_at: '' },
      { id: 'b', session_id: 's-1', role: 'assistant', content: '지난 답', sources: [{ meeting_id: 'm-1', meeting_title: 't', start_time: 3, text_snippet: 'x', source_type: 'subtitle' }], meeting_context_id: null, created_at: '' },
    ]);
    render(<AiAssistantPage />);
    await userEvent.click(await screen.findByTestId('ai-session-row'));
    await waitFor(() => expect(mockLoadSession).toHaveBeenCalled());
    const msgs = mockLoadSession.mock.calls[0][1];
    expect(msgs[1].sources).toHaveLength(1);
  });

  it('shows the error with a retry button', () => {
    mockError = 'AI 서비스가 잠시 응답하지 않습니다.';
    render(<AiAssistantPage />);
    expect(screen.getByTestId('ai-error')).toHaveTextContent('AI 서비스가 잠시 응답하지 않습니다.');
    expect(screen.getByRole('button', { name: '다시 시도' })).toBeInTheDocument();
  });
});
