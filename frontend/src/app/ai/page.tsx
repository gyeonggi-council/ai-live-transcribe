'use client';

/**
 * AI 어시스턴트 전체 화면 페이지
 *
 * @TASK P11B - AI Assistant page
 *
 * ── 2026-09-14 회의 선택형으로 개편(담당자 요청: 회의를 골라 대화·요약, 의원·사무처·집행부가 쓰게) ──
 * 좌측 272px: 회의 목록(검색 = 회의명·의원 이름) + 본인 이전 대화. 휴대폰에서는 시트로 연다.
 * 우측: 선택된 회의 칩 → 브리프(요약·결정·조치·빠른 질문, 대화가 시작되면 접힘) → 대화 → 입력(textarea).
 * - 회의를 바꾸면 새 대화다(서버가 세션을 소유자+회의에 고정한다). 이전 대화를 열면 그 회의도 함께 돌아온다.
 * - 딥링크 /ai?meeting=<id> — 회의 상세·회의록 화면의 "AI 에게 묻기".
 * - 높이는 PlatformLayout 이 주는 잔여 높이(h-full) 를 쓰고 입력창과 대화 스크롤을 분리한다(100vh-48 은 브레드크럼 줄과 어긋났다).
 * - 오류는 답변으로 위장하지 않고 재시도 버튼으로. 429 는 "오늘 한도 소진".
 *
 * ── 2026-08-25 개선안 2g(유지) ── AI 답변은 말풍선 없이 760px 읽는 열, 질문만 말풍선. 참조 발언은 누를 수 있는 카드.
 */

import React, { Suspense, useCallback, useEffect, useRef, useState } from 'react';

import Link from 'next/link';
import { useSearchParams } from 'next/navigation';

import AiMeetingBrief from '@/components/ai/AiMeetingBrief';
import AiMeetingList from '@/components/ai/AiMeetingList';
import AiSourceCard from '@/components/ai/AiSourceCard';
import RoleGuard from '@/components/RoleGuard';
import { useAuth } from '@/contexts/AuthContext';
import { useAiChat } from '@/hooks/useAiChat';
import { AI_ROLES } from '@/lib/aiAccess';
import { apiClient, getAiConversation, getAiConversations } from '@/lib/api';
import type { AiChatMessage, AiConversationSession, MeetingType } from '@/types';

/** 읽는 열 — 본문·입력·예시 질문이 모두 이 폭을 쓴다 */
const READING_COLUMN = 'mx-auto w-full max-w-[760px]';
const MAX_QUESTION = 2000;

export default function AiAssistantPage() {
  return (
    <RoleGuard
      roles={[...AI_ROLES]}
      fallback={
        <div className="p-8 text-center text-text-muted">
          <p className="mb-3">AI 어시스턴트는 로그인하거나 의회망에서 쓸 수 있습니다.</p>
          <Link href="/login" className="text-primary underline">
            로그인 하러 가기
          </Link>
        </div>
      }
    >
      <Suspense fallback={<div className="p-6 text-sm text-text-muted">불러오는 중…</div>}>
        <AiAssistantContent />
      </Suspense>
    </RoleGuard>
  );
}

function formatWhen(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getMonth() + 1}/${d.getDate()} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function AiAssistantContent() {
  const searchParams = useSearchParams();
  const { effectiveRole } = useAuth();
  const [meeting, setMeeting] = useState<MeetingType | null>(null);
  const meetingId = meeting?.id;
  const {
    messages, loading, streaming, statusText, error, rateLimited, saved, sessionId, sendMessage, retryLast, clearMessages, loadSession,
  } = useAiChat(meetingId);
  const [input, setInput] = useState('');
  const [sessions, setSessions] = useState<AiConversationSession[]>([]);
  const [sessionsLoading, setSessionsLoading] = useState(false);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [briefCollapsed, setBriefCollapsed] = useState(false);
  const composing = useRef(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  // 회의 전환·새 대화·세션 열기의 세대 번호 — 늦게 끝난 조회가 최신 선택을 덮지 않게(Codex 검토)
  const selectionGen = useRef(0);
  const canGenerate = Boolean(effectiveRole) && effectiveRole !== 'anonymous';

  // 딥링크 ?meeting=<id> — 회의 전환은 selectMeeting(새 대화·세대 번호) 한 길로만. 아래에서 selectMeeting 정의 뒤에 건다.
  const wanted = searchParams?.get('meeting') ?? null;
  const selectMeetingRef = useRef<(m: MeetingType) => void>(() => {});
  useEffect(() => {
    if (!wanted || wanted === meetingId) return undefined;
    const gen = selectionGen.current;
    let cancelled = false;
    apiClient<MeetingType>(`/api/meetings/${wanted}`)
      .then((m) => {
        if (!cancelled && m?.id && gen === selectionGen.current) selectMeetingRef.current(m);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wanted]);

  // 본인 세션 목록 (best-effort — 손님 표식이 없거나 외부 비로그인은 401 → 빈 목록)
  const reloadSessions = useCallback(async () => {
    setSessionsLoading(true);
    try {
      setSessions(await getAiConversations());
    } catch {
      setSessions([]);
    } finally {
      setSessionsLoading(false);
    }
  }, []);
  useEffect(() => {
    reloadSessions();
  }, [reloadSessions, messages.length]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // 대화가 시작되면 브리프는 접힌다
  useEffect(() => {
    if (messages.length > 0) setBriefCollapsed(true);
  }, [messages.length]);

  const selectMeeting = useCallback(
    (m: MeetingType) => {
      if (m.id === meetingId) {
        setSheetOpen(false);
        return;
      }
      selectionGen.current += 1;
      setMeeting(m);
      clearMessages();
      setBriefCollapsed(false);
      setSheetOpen(false);
    },
    [meetingId, clearMessages]
  );

  selectMeetingRef.current = selectMeeting;

  const newChat = useCallback(() => {
    selectionGen.current += 1;
    clearMessages();
    setBriefCollapsed(false);
    setSheetOpen(false);
  }, [clearMessages]);

  const openSession = useCallback(
    async (sess: AiConversationSession) => {
      const gen = ++selectionGen.current;
      try {
        const items = await getAiConversation(sess.session_id);
        if (gen !== selectionGen.current) return;
        const msgs: AiChatMessage[] = items.map((it) => ({
          role: it.role,
          content: it.content,
          sources: it.sources ?? undefined,
        }));
        let nextMeeting: MeetingType | null = null;
        if (sess.meeting_context_id) {
          try {
            const m = await apiClient<MeetingType>(`/api/meetings/${sess.meeting_context_id}`);
            nextMeeting = m?.id ? m : null;
          } catch {
            nextMeeting = null;
          }
          if (gen !== selectionGen.current) return;
        }
        setMeeting(nextMeeting);
        loadSession(sess.session_id, msgs);
        setBriefCollapsed(true);
        setSheetOpen(false);
      } catch {
        /* 404 등 — 목록을 다시 읽는다 */
        reloadSessions();
      }
    },
    [loadSession, reloadSessions]
  );

  const submit = useCallback(async () => {
    const q = input.trim();
    if (!q || loading || !meeting) return;
    setInput('');
    await sendMessage(q);
  }, [input, loading, meeting, sendMessage]);

  const handleSubmit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      await submit();
    },
    [submit]
  );

  const onKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      // 한국어 IME 조합 중 Enter 는 글자 확정이지 전송이 아니다. Shift+Enter 는 줄바꿈.
      if (e.key === 'Enter' && !e.shiftKey && !composing.current && !e.nativeEvent.isComposing) {
        e.preventDefault();
        submit();
      }
    },
    [submit]
  );

  const sidePanel = (
    <div className="flex h-full min-h-0 flex-col gap-3 p-3">
      <button
        type="button"
        onClick={newChat}
        className="flex h-[34px] w-full shrink-0 items-center justify-center gap-1.5 rounded-md bg-primary text-[13.5px] font-semibold text-white transition-colors hover:bg-primary-light"
      >
        <svg className="h-[15px] w-[15px]" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" d="M12 5v14M5 12h14" />
        </svg>
        새 대화
      </button>
      <div className="min-h-0 flex-[3] flex flex-col gap-1.5">
        <span className="text-[11px] font-bold tracking-[0.08em] text-text-dim">회의 선택</span>
        <div className="min-h-0 flex-1">
          <AiMeetingList selectedId={meetingId ?? null} onSelect={selectMeeting} />
        </div>
      </div>
      <div className="min-h-0 flex-[2] flex flex-col gap-1.5 border-t border-border pt-2">
        <span className="text-[11px] font-bold tracking-[0.08em] text-text-dim">이전 대화</span>
        <div className="min-h-0 flex-1 overflow-y-auto" data-testid="ai-session-list">
          {sessionsLoading && sessions.length === 0 && <p className="px-1 text-xs text-text-muted">불러오는 중…</p>}
          {sessions.length === 0 && !sessionsLoading && <p className="px-1 text-xs text-text-muted">대화 이력이 없습니다.</p>}
          {sessions.map((sess) => {
            const on = sess.session_id === sessionId;
            return (
              <button
                key={sess.session_id}
                type="button"
                data-testid="ai-session-row"
                onClick={() => openSession(sess)}
                className={`mb-0.5 w-full rounded-md px-2.5 py-2 text-left transition-colors ${
                  on
                    ? 'bg-primary-5 text-primary-dark shadow-[inset_2px_0_0_0_var(--ggc-primary)]'
                    : 'text-text-secondary hover:bg-surface-raised'
                }`}
              >
                <p className={`truncate text-[13px] leading-snug ${on ? 'font-semibold' : 'font-medium'}`}>
                  {sess.first_question || '(질문 없음)'}
                </p>
                <p className="mt-0.5 truncate text-[11.5px] tabular-nums text-text-dim">
                  {sess.meeting_title ? `${sess.meeting_title} · ` : ''}
                  {formatWhen(sess.last_active_at)} · {sess.message_count}개
                </p>
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );

  return (
    <div className="flex h-full min-h-0">
      {/* 좌측 패널 — lg 이상 */}
      <aside className="hidden w-[272px] shrink-0 flex-col border-r border-border bg-surface lg:flex">{sidePanel}</aside>

      {/* 휴대폰 시트 */}
      {sheetOpen && (
        <div className="fixed inset-0 z-40 flex lg:hidden" role="dialog" aria-modal="true" aria-label="회의와 이전 대화">
          <div className="h-full w-[86%] max-w-[360px] bg-surface shadow-xl">{sidePanel}</div>
          <button type="button" className="flex-1 bg-black/30" aria-label="닫기" onClick={() => setSheetOpen(false)} />
        </div>
      )}

      {/* 우측: 대화 영역 */}
      <main className="flex min-w-0 flex-1 flex-col">
        {/* 회의 칩 줄 */}
        <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-border px-4 py-2 sm:px-8">
          <button
            type="button"
            onClick={() => setSheetOpen(true)}
            className="rounded-md border border-border px-2 py-1 text-[12px] lg:hidden"
            data-testid="ai-open-sheet"
          >
            회의 고르기
          </button>
          <span
            data-testid="ai-context-chip"
            className="inline-flex min-w-0 max-w-full items-center gap-1.5 rounded-full border border-border bg-surface-raised px-3 py-1 text-[12.5px] text-text"
          >
            <span className="shrink-0 text-[10px] font-bold text-primary">회의</span>
            <span className="truncate">{meeting ? `${meeting.title} · ${meeting.meeting_date}` : '왼쪽에서 회의를 골라 주세요'}</span>
          </span>
          <button type="button" onClick={newChat} className="ml-auto text-[12px] text-text-muted underline lg:hidden">
            새 대화
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4 sm:px-8" role="log" aria-label="AI 대화">
          <div className={`${READING_COLUMN} flex flex-col gap-5`}>
            {meeting && (
              <AiMeetingBrief
                key={meeting.id}
                meeting={meeting}
                canGenerate={canGenerate}
                onAsk={(q) => sendMessage(q)}
                collapsed={briefCollapsed}
                onToggle={() => setBriefCollapsed((v) => !v)}
              />
            )}

            {messages.length === 0 && !meeting && (
              <div className="flex flex-col items-center justify-center py-10 text-text-muted">
                <p className="mb-2 text-lg font-medium text-text">AI 어시스턴트</p>
                <p className="text-sm">왼쪽에서 회의를 고르면 그 회의의 자막·요약을 바탕으로 답합니다.</p>
              </div>
            )}

            {messages.map((msg, idx) => (
              <ChatMessage key={idx} message={msg} />
            ))}

            {loading && !streaming && (
              <div className="flex items-center gap-2 text-sm text-text-muted" role="status">
                <span className="grid h-[22px] w-[22px] place-items-center rounded-[5px] bg-primary-5 text-[10px] font-bold text-primary">
                  AI
                </span>
                {statusText ?? '답변 생성 중...'}
              </div>
            )}

            {error && (
              <div
                role="alert"
                data-testid="ai-error"
                className="flex flex-wrap items-center gap-3 rounded-lg border border-red-200 bg-red-50 px-3.5 py-2.5 text-[13px] text-red-800"
              >
                <span className="min-w-0 flex-1">{rateLimited ? '오늘 AI 대화 한도를 다 썼습니다. 내일 00시(한국시간)에 다시 열립니다.' : error}</span>
                {!rateLimited && (
                  <button
                    type="button"
                    onClick={retryLast}
                    className="rounded-md border border-red-300 bg-white px-2.5 py-1 text-[12.5px] font-semibold text-red-800 hover:bg-red-100"
                  >
                    다시 시도
                  </button>
                )}
              </div>
            )}

            {saved === false && (
              <p className="text-[12px] text-text-dim" data-testid="ai-not-saved">
                이 브라우저는 손님 표식이 없어 대화가 저장되지 않습니다 — 후속 질문의 맥락이 이어지지 않습니다. 로그인하면 저장됩니다.
              </p>
            )}
            <div ref={messagesEndRef} />
          </div>
        </div>

        {/* 입력 — 본문과 같은 읽는 열 */}
        <div className="shrink-0 border-t border-border px-4 pb-3 pt-3 sm:px-8">
          <form onSubmit={handleSubmit} className={`${READING_COLUMN} flex flex-col gap-1.5`}>
            <div className="flex items-end gap-2">
              <textarea
                value={input}
                onChange={(e) => setInput(e.target.value.slice(0, MAX_QUESTION))}
                onKeyDown={onKeyDown}
                onCompositionStart={() => {
                  composing.current = true;
                }}
                onCompositionEnd={() => {
                  composing.current = false;
                }}
                rows={2}
                placeholder={meeting ? '이 회의에 대해 질문하세요 (Enter 전송 · Shift+Enter 줄바꿈)' : '회의를 먼저 골라 주세요'}
                className="min-h-[44px] min-w-0 flex-1 resize-none rounded-lg border border-border-strong bg-surface px-3.5 py-2.5 text-[14.5px] leading-relaxed text-text placeholder-text-muted focus:border-brand focus:outline-none"
                disabled={loading || !meeting}
                aria-label="AI 질문 입력"
              />
              <button
                type="submit"
                disabled={loading || !meeting || !input.trim()}
                className="inline-flex h-11 shrink-0 items-center gap-1.5 rounded-lg bg-primary px-5 text-[14.5px] font-semibold text-white transition-colors hover:bg-primary-light disabled:opacity-50"
              >
                전송
                <svg className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 12h13m0 0l-5-5m5 5l-5 5" />
                </svg>
              </button>
            </div>
            <span className="self-end text-[11px] tabular-nums text-text-dim">
              {input.length}/{MAX_QUESTION}
            </span>
          </form>
        </div>
      </main>
    </div>
  );
}

function ChatMessage({ message }: { message: AiChatMessage }) {
  // 질문 — 말풍선을 유지한다. 누가 말했는지 구분이 필요한 쪽은 질문이다.
  if (message.role === 'user') {
    return (
      <div className="flex justify-end">
        <span className="max-w-[82%] whitespace-pre-wrap rounded-[12px_12px_4px_12px] bg-primary-5 px-3.5 py-2.5 text-[14.5px] leading-relaxed text-text">
          {message.content}
        </span>
      </div>
    );
  }

  // 답변 — 말풍선 없이 읽는 글
  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-2">
        <span className="grid h-[22px] w-[22px] place-items-center rounded-[5px] bg-primary text-[10px] font-bold text-white">
          AI
        </span>
        <span className="text-xs font-semibold text-text-muted">
          AI 답변
          {message.sources && message.sources.length > 0 && ` · 자막 ${message.sources.length}건 참조`}
        </span>
      </div>

      <p className="whitespace-pre-wrap text-[15.5px] leading-[1.8] text-text">{message.content}</p>

      {message.sources && message.sources.length > 0 && (
        <div className="mt-0.5 flex flex-col gap-1.5">
          <span className="text-[11px] font-bold tracking-[0.08em] text-text-dim">참조한 발언</span>
          {message.sources.map((src, i) => (
            <AiSourceCard key={i} source={src} />
          ))}
        </div>
      )}
    </div>
  );
}
