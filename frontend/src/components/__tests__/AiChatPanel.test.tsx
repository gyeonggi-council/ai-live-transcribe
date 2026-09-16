import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

// jsdom에서 scrollIntoView 미지원
beforeAll(() => {
  Element.prototype.scrollIntoView = jest.fn();
});

import AiChatPanel from '../AiChatPanel';

// Mock useAiChat hook
const mockSendMessage = jest.fn();
const mockClearMessages = jest.fn();

jest.mock('@/hooks/useAiChat', () => ({
  useAiChat: () => ({
    messages: mockMessages,
    loading: mockLoading,
    error: null,
    rateLimited: false,
    sessionId: 'test-session',
    sendMessage: mockSendMessage,
    retryLast: jest.fn(),
    clearMessages: mockClearMessages,
    loadSession: jest.fn(),
  }),
}));

jest.mock('@/lib/api', () => ({
  getAiConversations: jest.fn().mockResolvedValue([]),
  getAiConversation: jest.fn(),
}));

jest.mock('next/link', () => {
  return function MockLink({ children, href }: { children: React.ReactNode; href: string }) {
    return <a href={href}>{children}</a>;
  };
});

let mockMessages: Array<{ role: string; content: string; sources?: Array<Record<string, unknown>> }> = [];
let mockLoading = false;

describe('AiChatPanel', () => {
  beforeEach(() => {
    mockMessages = [];
    mockLoading = false;
    mockSendMessage.mockClear();
    mockClearMessages.mockClear();
  });

  it('renders collapsed button by default', () => {
    render(<AiChatPanel />);
    expect(
      screen.getByRole('button', { name: 'AI 어시스턴트 열기' })
    ).toBeInTheDocument();
  });

  it('opens panel when collapsed button is clicked', async () => {
    render(<AiChatPanel />);
    const openBtn = screen.getByRole('button', { name: 'AI 어시스턴트 열기' });
    await userEvent.click(openBtn);

    expect(screen.getByText('AI 어시스턴트')).toBeInTheDocument();
    expect(
      screen.getByPlaceholderText('질문을 입력하세요...')
    ).toBeInTheDocument();
  });

  it('shows empty state message when no messages', async () => {
    render(<AiChatPanel defaultCollapsed={false} />);
    expect(
      screen.getByText(/회의 자료에 대해 질문해 보세요\./)
    ).toBeInTheDocument();
  });

  it('calls sendMessage on form submit', async () => {
    render(<AiChatPanel defaultCollapsed={false} />);
    const input = screen.getByPlaceholderText('질문을 입력하세요...');
    const sendBtn = screen.getByText('전송');

    await userEvent.type(input, '테스트 질문');
    await userEvent.click(sendBtn);

    expect(mockSendMessage).toHaveBeenCalledWith('테스트 질문');
  });
});
