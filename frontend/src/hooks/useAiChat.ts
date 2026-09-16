/**
 * AI 채팅 훅 - RAG Q&A 인터페이스
 *
 * @TASK P11B - AI Assistant hook
 *
 * 2026-09-14 — 회의 선택형 `/ai` 개편에 맞춰:
 * - 세션은 서버가 소유자·회의에 고정한다. 회의를 바꾸는 쪽(화면)이 clearMessages() 로 새 대화를 시작한다 —
 *   훅이 meetingContextId 변화를 보고 스스로 비우지 않는다(loadSession 과 서로 초기화하는 경합을 막는다).
 * - 요청 세대 번호: 새 대화·세션 불러오기 뒤에 늦게 도착한 옛 응답은 버린다(A 회의 답이 B 회의 대화에 붙던 문제).
 * - 오류는 답변 말풍선으로 위장하지 않고 error 로 낸다. 화면이 재시도 버튼을 그린다(retryLast).
 *
 * 2026-09-15 — 답을 글자 조각으로 받는다(aiChatStream, 담당자 요청 "AI 답변 속도"). 첫 조각에 답 말풍선이 생기고
 * 끝나면 서버 정리본·출처로 바뀐다. 도중 실패하면 반쪽 답은 지우고 error. 새 대화·세션 전환·화면 이탈 시 흐름을 끊는다.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import { logAccess } from '@/hooks/useAccessLog';
import { ApiError, aiChatStream } from '@/lib/api';
import type { AiSearchScope } from '@/lib/api';
import type { AiChatMessage } from '@/types';

export interface UseAiChatReturn {
  messages: AiChatMessage[];
  loading: boolean;
  /** 답의 첫 조각이 도착해 흘러나오는 중 — 이때는 "답변 생성 중…" 대신 답 자체가 보인다 */
  streaming: boolean;
  /** 에이전트가 도구로 찾는 중이면 그 안내("자막 검색 중… '보안'"), 아니면 null */
  statusText: string | null;
  error: string | null;
  /** 429 — 오늘 한도 소진(내일 00시 KST) */
  rateLimited: boolean;
  /** false = 서버가 이력을 저장하지 못했다(손님 표식 없음) — 후속 질문 맥락이 안 이어진다 */
  saved: boolean | null;
  sessionId: string;
  sendMessage: (question: string) => Promise<void>;
  /** 실패한 마지막 질문을 다시 보낸다 */
  retryLast: () => Promise<void>;
  clearMessages: () => void;
  /** 이전 대화를 불러와 그 세션으로 이어서 대화 (멀티턴 지속) */
  loadSession: (sessionId: string, msgs: AiChatMessage[]) => void;
}

function newSessionId(): string {
  return typeof crypto !== 'undefined' && crypto.randomUUID
    ? crypto.randomUUID()
    : Math.random().toString(36).slice(2);
}

function describeError(err: unknown): { message: string; rateLimited: boolean } {
  if (err instanceof ApiError) {
    if (err.status === 429) return { message: err.message, rateLimited: true };
    if (err.status === 404) return { message: '이 대화를 더 이어갈 수 없습니다. 새 대화를 시작해 주세요.', rateLimited: false };
    if (err.status === 502 || err.status === 503) return { message: err.message || 'AI 서비스가 잠시 응답하지 않습니다.', rateLimited: false };
    return { message: err.message, rateLimited: false };
  }
  return { message: err instanceof Error ? err.message : 'AI 응답 생성 중 오류가 발생했습니다.', rateLimited: false };
}

/** 조각을 모아 이만큼마다 화면에 반영한다 — 조각마다 다시 그리면 긴 답에서 스크롤이 버벅인다 */
const FLUSH_MS = 50;

export function useAiChat(meetingContextId?: string, scope?: AiSearchScope): UseAiChatReturn {
  const [messages, setMessages] = useState<AiChatMessage[]>([]);
  const [loading, setLoading] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [statusText, setStatusText] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [rateLimited, setRateLimited] = useState(false);
  const [saved, setSaved] = useState<boolean | null>(null);
  const [sessionId, setSessionId] = useState<string>(newSessionId);
  const generation = useRef(0);
  const lastQuestion = useRef<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const sendMessage = useCallback(
    async (question: string) => {
      const q = question.trim();
      if (!q) return;
      // 답이 오는 중에는 새 질문을 받지 않는다 — 브리프의 빠른 질문은 입력창과 달리 잠기지 않는다.
      // 앞 요청을 끊고 새로 보내면 두 요청의 세대가 같아 끊긴 쪽이 새 요청의 로딩을 풀고 반쪽 답을 남겼다(Codex 검토 2026-09-15)
      if (abortRef.current) return;
      logAccess('ai', { meetingId: meetingContextId ?? null });  // 접속 통계(2026-09-16)
      const gen = generation.current;
      lastQuestion.current = q;
      const ac = new AbortController();
      abortRef.current = ac;

      setMessages((prev) => [...prev, { role: 'user', content: q }]);
      setLoading(true);
      setStreaming(false);
      setStatusText(null);
      setError(null);
      setRateLimited(false);

      // 조각 버퍼 — 첫 조각에 빈 답 말풍선을 만들고, 이후는 FLUSH_MS 마다 이어 붙인다
      let started = false;
      let pending = '';
      let timer: ReturnType<typeof setTimeout> | null = null;
      const flush = () => {
        timer = null;
        if (!pending || gen !== generation.current) return;
        const piece = pending;
        pending = '';
        setMessages((prev) => {
          const last = prev[prev.length - 1];
          if (!started) return prev;
          if (last?.role === 'assistant') return [...prev.slice(0, -1), { ...last, content: last.content + piece }];
          return [...prev, { role: 'assistant', content: piece }];
        });
      };
      const onStatus = (t: string) => {
        if (gen === generation.current) setStatusText(t);
      };
      // 에이전트가 본문을 쓰다 도구 호출로 바꿨다 — 반쪽 답 말풍선을 지우고 다음 조각부터 새로 쓴다
      const onReset = () => {
        if (gen !== generation.current) return;
        if (timer) clearTimeout(timer);
        timer = null;
        pending = '';
        if (started) {
          started = false;
          setStreaming(false);
          setMessages((prev) => (prev[prev.length - 1]?.role === 'assistant' ? prev.slice(0, -1) : prev));
        }
      };
      const onDelta = (t: string) => {
        if (gen !== generation.current) return;
        if (!started) {
          started = true;
          setStatusText(null);
          setStreaming(true);
          setMessages((prev) => [...prev, { role: 'assistant', content: t }]);
          return;
        }
        pending += t;
        if (!timer) timer = setTimeout(flush, FLUSH_MS);
      };

      try {
        const res = await aiChatStream(q, sessionId, meetingContextId, { onDelta, onStatus, onReset, signal: ac.signal, scope });
        if (timer) clearTimeout(timer);
        if (gen !== generation.current) return; // 그 사이 새 대화·다른 세션으로 옮겨갔다
        // 흘려받은 원문을 서버 정리본(마크다운 제거)·출처로 바꾼다
        setMessages((prev) => {
          const base = started && prev[prev.length - 1]?.role === 'assistant' ? prev.slice(0, -1) : prev;
          return [...base, { role: 'assistant', content: res.answer, sources: res.sources }];
        });
        setSessionId(res.session_id);
        setSaved(res.saved ?? true);
      } catch (err) {
        if (timer) clearTimeout(timer);
        if (gen !== generation.current || ac.signal.aborted) return;
        // 반쪽 답은 지운다 — 질문 말풍선만 남아야 retryLast 가 그 질문을 다시 보낸다
        if (started) setMessages((prev) => (prev[prev.length - 1]?.role === 'assistant' ? prev.slice(0, -1) : prev));
        const d = describeError(err);
        setError(d.message);
        setRateLimited(d.rateLimited);
      } finally {
        if (gen === generation.current) {
          setLoading(false);
          setStreaming(false);
          setStatusText(null);
        }
        if (abortRef.current === ac) abortRef.current = null;
      }
    },
    [sessionId, meetingContextId, scope]
  );

  const retryLast = useCallback(async () => {
    const q = lastQuestion.current;
    if (!q) return;
    // 실패한 질문 말풍선은 이미 떠 있다 — 지우고 다시 보낸다
    setMessages((prev) => (prev.at(-1)?.role === 'user' ? prev.slice(0, -1) : prev));
    await sendMessage(q);
  }, [sendMessage]);

  const clearMessages = useCallback(() => {
    generation.current += 1;
    abortRef.current?.abort();
    abortRef.current = null; // 끊긴 요청의 finally 를 기다리지 않고 바로 새 질문을 받는다
    lastQuestion.current = null;
    setMessages([]);
    setSessionId(newSessionId());
    setError(null);
    setRateLimited(false);
    setSaved(null);
    setLoading(false);
    setStreaming(false);
  }, []);

  const loadSession = useCallback((sid: string, msgs: AiChatMessage[]) => {
    generation.current += 1;
    abortRef.current?.abort();
    abortRef.current = null;
    lastQuestion.current = null;
    setSessionId(sid);
    setMessages(msgs);
    setError(null);
    setRateLimited(false);
    setSaved(true);
    setLoading(false);
    setStreaming(false);
  }, []);

  // 화면을 떠나면 받던 흐름을 끊는다
  useEffect(() => () => abortRef.current?.abort(), []);

  return {
    messages, loading, streaming, statusText, error, rateLimited, saved, sessionId, sendMessage, retryLast, clearMessages, loadSession,
  };
}
