'use client';

/**
 * AI 채팅 패널 컴포넌트
 *
 * @TASK P11B - AI Assistant chat panel
 *
 * 우측 고정/접힘 패널. 메시지 목록 + 입력바.
 * meetingContextId를 전달하면 특정 회의 컨텍스트로 한정.
 */

import React, { useCallback, useEffect, useRef, useState } from 'react';

import AiSourceCard from '@/components/ai/AiSourceCard';
import { Button, Input } from '@/components/ui';
import { useAiChat } from '@/hooks/useAiChat';
import { getAiConversation, getAiConversations } from '@/lib/api';
import type { AiChatMessage, AiConversationSession } from '@/types';

interface AiChatPanelProps {
  /** 특정 회의 컨텍스트로 한정 */
  meetingContextId?: string;
  /** 초기 접힘 상태 */
  defaultCollapsed?: boolean;
  /** 답변 출처의 시간대(초)를 재생하는 콜백 (회의록 페이지 등에서 제공) */
  onPlayAt?: (seconds: number) => void;
}

export default function AiChatPanel({
  meetingContextId,
  defaultCollapsed = true,
  onPlayAt,
}: AiChatPanelProps) {
  const { messages, loading, streaming, statusText, error, rateLimited, sessionId, sendMessage, retryLast, clearMessages, loadSession } =
    useAiChat(meetingContextId);
  const [collapsed, setCollapsed] = useState(defaultCollapsed);
  const [input, setInput] = useState('');
  const [sessions, setSessions] = useState<AiConversationSession[]>([]);
  const [panelWidth, setPanelWidth] = useState(560);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // 새 메시지 시 스크롤
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // 저장된 패널 폭 복원
  useEffect(() => {
    const saved =
      typeof window !== 'undefined' ? window.localStorage.getItem('ai_panel_width') : null;
    if (saved) setPanelWidth(Math.min(900, Math.max(360, Number(saved) || 560)));
  }, []);

  // 본인 대화 목록(이 회의 것만) — 2026-09-14 부터 공유 이력이 아니라 본인 세션이다(로그인 또는 손님 표식). 실패(401)는 빈 목록.
  useEffect(() => {
    if (collapsed) return;
    let cancelled = false;
    getAiConversations()
      .then((rows) => {
        if (!cancelled) setSessions(rows.filter((r) => !meetingContextId || r.meeting_context_id === meetingContextId));
      })
      .catch(() => {
        if (!cancelled) setSessions([]);
      });
    return () => {
      cancelled = true;
    };
  }, [collapsed, meetingContextId, messages.length]);

  // 세션 열기·새 대화의 세대 번호 — 늦게 끝난 조회가 새 대화를 옛 세션으로 되돌리지 않게(Codex 2차)
  const openGen = useRef(0);
  const openSession = useCallback(
    async (sid: string) => {
      const gen = ++openGen.current;
      try {
        const items = await getAiConversation(sid);
        if (gen !== openGen.current) return;
        loadSession(
          sid,
          items.map((i) => ({ role: i.role, content: i.content, sources: i.sources ?? undefined })),
        );
      } catch {
        /* 404 — 목록이 낡았다. 다음 갱신 때 사라진다 */
      }
    },
    [loadSession],
  );

  // 폭 조절 드래그 (패널 왼쪽 모서리)
  const startResize = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    const onMove = (ev: MouseEvent) => {
      setPanelWidth(Math.min(900, Math.max(360, window.innerWidth - ev.clientX)));
    };
    const onUp = () => {
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
      setPanelWidth((w) => {
        try {
          window.localStorage.setItem('ai_panel_width', String(Math.round(w)));
        } catch {
          /* ignore */
        }
        return w;
      });
    };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
  }, []);

  const handleSubmit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      if (!input.trim() || loading) return;
      const q = input.trim();
      setInput('');
      await sendMessage(q);
    },
    [input, loading, sendMessage]
  );

  if (collapsed) {
    return (
      <button
        type="button"
        onClick={() => setCollapsed(false)}
        className="fixed right-4 bottom-4 z-50 flex h-12 w-12 items-center justify-center rounded-full bg-primary text-white shadow-lg hover:bg-primary-dark focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
        aria-label="AI 어시스턴트 열기"
      >
        AI
      </button>
    );
  }

  return (
    <div
      className="fixed right-0 top-0 z-40 flex h-full flex-col border-l border-gray-200 bg-white shadow-lg"
      style={{ width: panelWidth, maxWidth: '100vw' }}
    >
      {/* 폭 조절 핸들 (왼쪽 모서리 드래그) */}
      <div
        onMouseDown={startResize}
        className="absolute left-0 top-0 z-10 h-full w-1.5 cursor-col-resize hover:bg-primary-light/50 active:bg-primary/60"
        title="드래그하여 폭 조절"
      />

      {/* Header */}
      <div className="flex items-center justify-between border-b border-gray-200 px-4 py-3 pl-5">
        <h3 className="text-sm font-semibold text-gray-900">AI 어시스턴트</h3>
        <button
          type="button"
          onClick={() => setCollapsed(true)}
          className="text-gray-400 hover:text-gray-600"
          aria-label="AI 어시스턴트 닫기"
        >
          X
        </button>
      </div>

      {/* 본문: 좌측 대화 목록 + 우측 채팅 */}
      <div className="flex flex-1 min-h-0">
        {/* 좌측 대화 목록 (히스토리) */}
        <div className="w-32 sm:w-44 flex-shrink-0 border-r border-gray-200 bg-gray-50 flex flex-col">
          <div className="px-2 py-2 border-b border-gray-200">
            <button
              type="button"
              onClick={() => {
                  openGen.current += 1;
                  clearMessages();
                }}
              className="w-full text-xs font-medium text-primary hover:bg-primary-5 rounded px-2 py-1.5 border border-primary-10"
            >
              + 새 대화
            </button>
          </div>
          <div className="flex-1 overflow-y-auto p-1.5 space-y-1">
            <p className="text-[11px] text-gray-400 px-1 pb-1">이전 대화</p>
            {sessions.length === 0 && (
              <p className="text-[11px] text-gray-400 px-1">대화 기록이 없습니다.</p>
            )}
            {sessions.map((s) => (
              <button
                key={s.session_id}
                type="button"
                onClick={() => openSession(s.session_id)}
                className={`w-full text-left text-xs rounded px-2 py-1.5 border transition-colors ${
                  s.session_id === sessionId
                    ? 'bg-primary-10 border-primary-30 text-primary-dark'
                    : 'border-transparent hover:bg-primary-5 hover:border-primary-10 text-gray-700'
                }`}
                title="이 대화를 불러와 이어서 질문합니다"
              >
                <span className="block truncate">{(s.first_question || '대화').slice(0, 40)}</span>
                <span className="text-[10px] text-gray-400">{s.message_count}개 메시지</span>
              </button>
            ))}
          </div>
        </div>

        {/* 우측 채팅 */}
        <div className="flex-1 flex flex-col min-w-0">
          <div
            className="flex-1 overflow-y-auto p-4 space-y-3"
            role="log"
            aria-label="AI 대화"
          >
            {messages.length === 0 && (
              <p className="text-center text-sm text-gray-400 mt-8">
                회의 자료에 대해 질문해 보세요.
                <br />
                왼쪽에서 이전 대화를 불러올 수도 있어요.
              </p>
            )}
            {messages.map((msg, idx) => (
              <MessageBubble key={idx} message={msg} onPlayAt={onPlayAt} />
            ))}
            {loading && !streaming && (
              <div className="flex items-center gap-2 text-sm text-gray-500" role="status">
                <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-primary border-t-transparent" />
                {statusText ?? '답변 생성 중...'}
              </div>
            )}
            {error && (
              <div role="alert" className="flex flex-wrap items-center gap-2 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-800">
                <span className="min-w-0 flex-1">
                  {rateLimited ? '오늘 AI 대화 한도를 다 썼습니다. 내일 00시(한국시간)에 다시 열립니다.' : error}
                </span>
                {!rateLimited && (
                  <button type="button" onClick={retryLast} className="rounded border border-red-300 bg-white px-2 py-0.5 font-semibold hover:bg-red-100">
                    다시 시도
                  </button>
                )}
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>

          {/* Input */}
          <form onSubmit={handleSubmit} className="border-t border-gray-200 p-3 flex gap-2">
            <div className="min-w-0 flex-1">
              <Input
                type="text"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder="질문을 입력하세요..."
                disabled={loading}
                aria-label="AI 질문 입력"
              />
            </div>
            <Button type="submit" disabled={loading || !input.trim()}>
              전송
            </Button>
          </form>
        </div>
      </div>
    </div>
  );
}

function MessageBubble({
  message,
  onPlayAt,
}: {
  message: AiChatMessage;
  onPlayAt?: (seconds: number) => void;
}) {
  const isUser = message.role === 'user';

  // 질문만 말풍선이다 (2026-08-25 개선안 2g). AI 답변은 문단이라 말풍선에 넣으면
  // 폭이 내용에 따라 들쭉날쭉해지고 줄바꿈 지점이 매번 달라진다.
  if (isUser) {
    return (
      <div className="flex justify-end">
        <span className="max-w-[85%] whitespace-pre-wrap rounded-[12px_12px_4px_12px] bg-primary-5 px-3 py-2 text-sm leading-relaxed text-gray-900">
          {message.content}
        </span>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      <p className="whitespace-pre-wrap text-sm leading-[1.75] text-gray-800">{message.content}</p>

      {/* 참조한 발언 — /ai 와 같은 카드(components/ai/AiSourceCard). onPlayAt 이 있으면 그 자리에서 재생, 없으면 /vod/{id}?t= */}
      {message.sources && message.sources.length > 0 && (
        <div className="flex flex-col gap-1">
          <span className="text-[11px] font-bold tracking-[0.08em] text-text-dim">참조한 발언</span>
          {message.sources.map((src, i) => (
            <AiSourceCard key={i} source={src} onPlayAt={onPlayAt} compact />
          ))}
        </div>
      )}
    </div>
  );
}
