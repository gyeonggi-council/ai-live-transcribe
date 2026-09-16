'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import AdminPinModal from '@/components/AdminPinModal';
import EmptyState from '@/components/EmptyState';
import PageHeader from '@/components/PageHeader';
import Pagination from '@/components/Pagination';
import SearchInput from '@/components/SearchInput';
import { TableSkeleton } from '@/components/Skeleton';
import { Button, Card } from '@/components/ui';
import VodTable, { isAiGenerationCandidate } from '@/components/VodTable';
import { useAuth } from '@/contexts/AuthContext';
import { useVodList } from '@/hooks/useVodList';
import { API_BASE_URL, getSttBatchStatus, startSttBatch } from '@/lib/api';
import { getToken } from '@/lib/auth';

/**
 * 관리 시작 회기 — 이 회기(≥) 이후의 회의만 관리·표시한다 (사용자 정책 2026-07-07).
 * 새 회기(392·393·394…)는 KMS 일괄 등록으로 자동 유입되며 코드 수정이 필요 없다.
 */
const MIN_MANAGED_SESSION = 391;

/** 관리 시작 회기의 개회일 — 회기 번호가 없는 생중계 스텁의 '관리 대상' 판별 폴백 */
const MANAGED_ERA_START = '2026-06-09';

/** 제목에서 "제XXX회" 회차 번호 추출 (기간 밖이라도 명시적 회차 일치는 포함) */
function extractSessionNumber(title: string | null | undefined): number | null {
  if (!title) return null;
  const match = title.match(/제\s*(\d+)\s*회/);
  return match?.[1] ? Number(match[1]) : null;
}

/** 회의의 회기 번호 — 제목 우선(KMS 제목이 진실), 없으면 DB session_no */
function sessionOf(v: { title?: string | null; session_no?: number | null }): number | null {
  return extractSessionNumber(v.title) ?? v.session_no ?? null;
}

/** 오늘 날짜 (로컬 KST 기준 YYYY-MM-DD) */
function todayLocal(): string {
  return new Date().toLocaleDateString('sv-SE');
}

/**
 * 회의의 위원회명 — DB 값이 우선이고, 없으면 제목에서 뽑는다.
 * 목록 API 는 committee 를 채워주지 않는 회의가 많아(단건 조회에서만 채널 기준으로 보강)
 * 제목 폴백이 없으면 위원회 필터가 대부분 '미분류'가 된다.
 */
function committeeOf(v: { committee?: string | null; title?: string | null }): string | null {
  if (v.committee) return v.committee;
  const matches = (v.title || '').match(/[가-힣]{2,}위원회|본회의/g);
  return matches?.[matches.length - 1] ?? null;
}

export default function VodListPage() {
  const { user } = useAuth();
  const isAdmin = user?.role === 'admin';
  const [currentPage, setCurrentPage] = useState(1);
  // 백엔드에서 충분한 건수를 받아 클라이언트에서 회차/오늘 필터.
  // live 상태도 포함하여 진행 중인 상임위가 바로 보이게 한다.
  const { vods, isLoading, error, totalPages, mutate: refreshVods } = useVodList({
    page: currentPage,
    perPage: 200,
    statuses: 'live,processing,ended',
  });

  // ── VOD 일괄 등록 (등록만 — AI 자막은 별도 버튼으로 명시적 실행) ────────
  const [bulkLoading, setBulkLoading] = useState(false);
  const [bulkResult, setBulkResult] = useState<null | {
    matched: number;
    created: number;
    promoted: number;
    duplicate: number;
    unmatched: number;
    errors: number;
  }>(null);

  // ── AI 자막 생성 (체크된 회의 순차 처리) ────────────────────────────────
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [genProgress, setGenProgress] = useState<null | {
    current: number;
    total: number;
    title: string;
    done: string[];
    failed: string[];
    /** 현재 회의의 세부 진행률 (0~1) — 다운로드/청크 전사/저장 단계 */
    stepProgress: number | null;
    /** 현재 단계 설명 ("OpenAI 전사 3/8 청크" 등) */
    stepMessage: string | null;
  }>(null);
  const genActiveRef = useRef(false);

  // PIN 모달 — 어떤 액션을 위해 열렸는지 추적
  const [pinOpen, setPinOpen] = useState(false);
  const pendingActionRef = useRef<null | 'bulk' | 'generate'>(null);

  const runBulkMatch = useCallback(async () => {
    setBulkLoading(true);
    setBulkResult(null);
    try {
      const token = getToken();
      // ★등록만 수행 — 자막 재생성은 절대 트리거하지 않는다 (비용/혼란 방지)
      const res = await fetch(
        `${API_BASE_URL}/api/admin/vod-bulk-match?regenerate=false&regenerate_existing=false`,
        {
          method: 'POST',
          headers: token ? { Authorization: `Bearer ${token}` } : {},
        },
      );
      if (!res.ok) {
        const detail = await res.json().catch(() => ({}));
        throw new Error(detail.detail || `HTTP ${res.status}`);
      }
      const data = await res.json();
      setBulkResult({
        matched: data.matched_count ?? 0,
        created: data.created_count ?? 0,
        promoted: data.promoted_count ?? 0,
        duplicate: data.duplicate_count ?? 0,
        unmatched: data.unmatched_count ?? 0,
        errors: data.error_count ?? 0,
      });
      refreshVods();
    } catch (e) {
      alert(`VOD 일괄 등록 실패: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBulkLoading(false);
    }
  }, [refreshVods]);

  const titleOf = useCallback(
    (id: string) => vods.find((v) => v.id === id)?.title ?? id,
    [vods],
  );

  /** 서버 배치 진행 상태를 폴링해 진행 표시로 변환 (완료까지) */
  const pollBatch = useCallback(
    async (total: number) => {
      genActiveRef.current = true;
      const deadline = Date.now() + 6 * 60 * 60 * 1000; // 안전 상한 6시간
      while (Date.now() < deadline) {
        try {
          const s = await getSttBatchStatus();
          const processed = s.done.length + s.failed.length;
          setGenProgress({
            current: Math.min(processed + (s.current ? 1 : 0), total),
            total,
            title: s.current ? titleOf(s.current) : '',
            done: s.done.map(titleOf),
            failed: s.failed.map((f) => `${titleOf(f.meeting_id)} (${f.reason})`),
            stepProgress: s.current_progress?.progress ?? null,
            stepMessage: s.current_progress?.message ?? null,
          });
          if (!s.running) break;
        } catch {
          // 일시적 오류 — 계속 폴링
        }
        await new Promise((r) => setTimeout(r, 3000));
        refreshVods();
      }
      genActiveRef.current = false;
      setSelectedIds(new Set());
      refreshVods();
    },
    [titleOf, refreshVods],
  );

  /** 선택된 회의들의 AI 자막 생성 — 서버 큐에 등록하면 페이지를 닫아도 계속 처리된다 */
  const runAiGeneration = useCallback(async () => {
    const ids = Array.from(selectedIds);
    if (ids.length === 0) return;
    try {
      const res = await startSttBatch(ids);
      await pollBatch(res.total);
      return;
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      if (msg.includes('409') || msg.includes('이미')) {
        // 다른 곳에서 시작된 배치가 진행 중 — 그 진행 상황에 합류
        await pollBatch(ids.length);
        return;
      }
      alert(`AI 자막 생성 시작 실패: ${msg}`);
    }
  }, [selectedIds, pollBatch]);

  // 페이지 (재)진입 시 서버 배치가 진행 중이면 진행 표시에 자동 합류
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const s = await getSttBatchStatus();
        if (!cancelled && s.running) {
          const total =
            s.done.length + s.failed.length + s.pending.length + (s.current ? 1 : 0);
          void pollBatch(total);
        }
      } catch {
        // 배치 상태 조회 실패는 무시
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const confirmAndGenerate = useCallback(() => {
    const n = selectedIds.size;
    const ok = window.confirm(
      `선택한 ${n}개 회의의 AI 자막을 생성할까요?\n\n` +
        `· 회의당 약 10분 소요 (순차 처리)\n` +
        `· 기존 라이브 자막은 더 정확한 AI 자막으로 교체됩니다\n` +
        `· OpenAI 비용이 발생합니다 (영상 1시간당 약 $0.4)`,
    );
    if (ok) void runAiGeneration();
  }, [selectedIds, runAiGeneration]);

  const requireAdmin = (action: 'bulk' | 'generate') => {
    if (isAdmin) {
      if (action === 'bulk') void runBulkMatch();
      else confirmAndGenerate();
    } else {
      pendingActionRef.current = action;
      setPinOpen(true);
    }
  };

  const handleToggleSelect = useCallback((id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  // ── 회기(제N회) 동적 그룹핑 — 391회 이후만 관리 (의회 홈페이지 연동) ──────
  // 데이터에 존재하는 회기 번호를 추출해 탭으로 노출한다. 새 회기(392·393·394…)가
  // KMS 일괄 등록으로 유입되면 탭이 자동으로 생긴다.
  const sessionNumbers = useMemo(() => {
    const set = new Set<number>();
    vods.forEach((v) => {
      const s = sessionOf(v);
      if (s !== null && s >= MIN_MANAGED_SESSION) set.add(s);
    });
    return Array.from(set).sort((a, b) => b - a); // 최신 회기 먼저
  }, [vods]);

  // 선택 회기 — null이면 아직 미선택(데이터 로드 후 최신 회기로 자동 설정)
  const [selectedSession, setSelectedSession] = useState<number | 'all' | null>(null);
  const activeSession: number | 'all' =
    selectedSession ?? (sessionNumbers[0] ?? 'all');

  // 회기별 회의 수 (탭 라벨용) — 관리 대상만
  const sessionCounts = useMemo(() => {
    const counts = new Map<number, number>();
    vods.forEach((v) => {
      const s = sessionOf(v);
      if (s !== null && s >= MIN_MANAGED_SESSION) {
        counts.set(s, (counts.get(s) ?? 0) + 1);
      }
    });
    return counts;
  }, [vods]);

  // 선택 회기 필터 + 정렬(의회 홈페이지와 동일):
  // ① 생중계(live)·오늘 회의 최상단 → ② 의회 번호(kms_no) 내림차순 → ③ 날짜 내림차순.
  // 회기 번호가 없는 스텁(예: '본회의 생중계')은 생중계/오늘 회의면 최신 회기 탭과
  // 전체 탭에 노출 — KMS 변환 완료 후 일괄 등록되면 정식 회기 제목으로 승격된다.
  const filteredVods = useMemo(() => {
    const today = todayLocal();
    const latestSession = sessionNumbers[0] ?? null;
    const list = vods.filter((v) => {
      const s = sessionOf(v);
      // '오늘' 회의만 회기 미상이어도 최신 탭에 노출 — status가 live로 남은
      // 과거 좀비 스텁(예: 6/29 생중계)이 상단을 차지하지 않게 날짜로 판정.
      const isToday = (v.meeting_date || '').slice(0, 10) === today;
      if (s !== null && s < MIN_MANAGED_SESSION) return false; // 이전 회기 제외
      if (activeSession === 'all') {
        // 전체: 관리 회기 전부 + (회기 미상이지만 관리 시대 이후) 스텁
        return s !== null || (v.meeting_date || '').slice(0, 10) >= MANAGED_ERA_START;
      }
      if (s === activeSession) return true;
      // 회기 미상 스텁은 오늘 회의에 한해 최신 회기 탭에 노출
      return s === null && isToday && activeSession === latestSession;
    });
    return list.sort((a, b) => {
      // ① 생중계 최상단
      const aLive = a.status === 'live' ? 1 : 0;
      const bLive = b.status === 'live' ? 1 : 0;
      if (aLive !== bLive) return bLive - aLive;
      // ② 오늘 회의 우선 — KMS 미등록(번호 없음) 당일 회의가 아래로 가라앉지 않게
      const aToday = (a.meeting_date || '').slice(0, 10) === today ? 1 : 0;
      const bToday = (b.meeting_date || '').slice(0, 10) === today ? 1 : 0;
      if (aToday !== bToday) return bToday - aToday;
      // ③ 의회 번호 내림차순 — 번호 있는 회의가 위, 둘 다 있으면 큰 번호 먼저
      const aNo = a.kms_no ?? -1;
      const bNo = b.kms_no ?? -1;
      if (aNo !== bNo) return bNo - aNo;
      // ④ 번호 둘 다 없으면 날짜 내림차순
      return (b.meeting_date || '').localeCompare(a.meeting_date || '');
    });
  }, [vods, activeSession, sessionNumbers]);

  // ── 검색 · 위원회 · 상태 필터 ──────────────────────────────────────────
  // 회기 선택(위)에서 좁힌 목록을 다시 세 갈래로 좁힌다. 순서가 중요하다 —
  // 상태 칩의 건수는 '검색·위원회까지 적용한 뒤'의 건수여야 화면과 일치한다.
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedCommittee, setSelectedCommittee] = useState<string>('all');

  /** 선택 회기에 실제로 존재하는 위원회 목록 (드롭다운 항목) */
  const committees = useMemo(() => {
    const set = new Set<string>();
    filteredVods.forEach((v) => {
      const c = committeeOf(v);
      if (c) set.add(c);
    });
    return Array.from(set).sort((a, b) => a.localeCompare(b, 'ko'));
  }, [filteredVods]);

  /** 검색어 + 위원회까지 적용한 목록 — 상태 칩 건수의 모집단 */
  const scopedVods = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    return filteredVods.filter((v) => {
      if (selectedCommittee !== 'all' && committeeOf(v) !== selectedCommittee) return false;
      if (!q) return true;
      const haystack = `${v.title ?? ''} ${committeeOf(v) ?? ''}`.toLowerCase();
      return haystack.includes(q);
    });
  }, [filteredVods, selectedCommittee, searchQuery]);

  // 선택 회기의 기간 (해당 회기 회의들의 최소~최대 날짜)
  const sessionRange = useMemo(() => {
    if (activeSession === 'all') return null;
    const dates = vods
      .filter((v) => sessionOf(v) === activeSession)
      .map((v) => (v.meeting_date || '').slice(0, 10))
      .filter(Boolean)
      .sort();
    if (dates.length === 0) return null;
    return { start: dates[0], end: dates[dates.length - 1] };
  }, [vods, activeSession]);

  const candidateCount = useMemo(
    () => scopedVods.filter(isAiGenerationCandidate).length,
    [scopedVods],
  );

  const handlePageChange = (page: number) => {
    setCurrentPage(page);
  };

  const sessionLabel =
    activeSession === 'all' ? `제${MIN_MANAGED_SESSION}회 이후 전체` : `제${activeSession}회`;
  // 제목 옆에는 **세는 값만** 둔다 — 회기 · 기간 · 건수. 문장("의회 홈페이지와 연동됩니다")은
  // 아래 줄로 내렸다 (2026-08-25 개선안 2f). 한 줄에 다 붙이면 폭에 따라 접히는 자리가
  // 매번 달라 제목이 흔들려 보였다.
  const sessionMeta = [
    sessionLabel,
    activeSession !== 'all' && sessionRange
      ? `${sessionRange.start} ~ ${(sessionRange.end ?? '').slice(5)}`
      : null,
    `${scopedVods.length}건`,
  ]
    .filter(Boolean)
    .join(' · ');
  const generating = genActiveRef.current && genProgress !== null;

  return (
    <div className="p-6">
      <div className="mx-auto max-w-[1360px]">
        <PageHeader
          title="회의 목록"
          meta={sessionMeta}
          description="의회 홈페이지(최근회의영상)와 연동됩니다."
          actions={
            /* 관리 기능(VOD 일괄 등록·AI 자막 생성)은 관리자에게만 노출한다.
               2026-08-22 시안: 목록의 주목적은 '회의를 찾는 것'이므로 상단을
               관리 버튼이 차지하지 않는다. */
            isAdmin ? (
            <div className="flex items-center gap-2">
              <Button
                variant="secondary"
                size="sm"
                onClick={() => requireAdmin('bulk')}
                disabled={bulkLoading || generating}
                className="gap-1.5 font-semibold"
                title="KMS 최근회의영상에서 VOD 주소를 찾아 등록만 합니다 (자막 생성 안 함)"
                data-testid="vod-bulk-match-button"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2.25}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M4 4v5h5M20 20v-5h-5M4 9a9 9 0 0115.5-3M20 15a9 9 0 01-15.5 3" />
                </svg>
                {bulkLoading ? '등록 중...' : 'VOD 일괄 등록'}
              </Button>
              {/* AI 자막 생성 — 관리자 로그인 시에만 노출 (비용 발생 작업, 사용자 요청 2026-06-12) */}
              {isAdmin && (
              <button
                type="button"
                onClick={() => requireAdmin('generate')}
                disabled={selectedIds.size === 0 || generating}
                className="inline-flex items-center gap-1.5 px-3 py-2 text-sm font-semibold text-white bg-success hover:bg-success/90 disabled:opacity-50 rounded-md transition-colors shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
                title={
                  candidateCount === 0
                    ? 'AI 자막을 생성할 수 있는 회의가 없습니다 (VOD 등록 필요)'
                    : '체크한 회의의 AI 자막을 순차 생성합니다 (관리자)'
                }
                data-testid="ai-generate-button"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2.25}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09z" />
                </svg>
                {generating
                  ? 'AI 자막 생성 중...'
                  : `AI 자막 생성${selectedIds.size > 0 ? ` (${selectedIds.size})` : ''}`}
              </button>
              )}
            </div>
            ) : undefined
          }
        />

        {/* 찾기 영역 — 한 줄 (2026-08-22 지시). 상태 칩은 제거했다 —
            카드마다 진행바가 이미 단계를 말하고, 칩까지 있으면 상단이 세 줄이 된다. */}
        <div className="mb-4 flex flex-wrap items-center gap-2" data-testid="meeting-filters">
          <div className="min-w-[12rem] flex-1">
            <SearchInput
              onSearch={setSearchQuery}
              onClear={() => setSearchQuery('')}
              placeholder="회의명·위원회명 검색"
            />
          </div>

          {sessionNumbers.length > 0 && (
            <select
              value={activeSession === 'all' ? 'all' : String(activeSession)}
              onChange={(e) =>
                setSelectedSession(e.target.value === 'all' ? 'all' : Number(e.target.value))
              }
              aria-label="회기 선택"
              data-testid="session-select"
              className="shrink-0 rounded-md border border-border-strong bg-white px-3 py-2 text-sm text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
            >
              {sessionNumbers.map((n) => (
                <option key={n} value={n}>
                  제{n}회 ({sessionCounts.get(n) ?? 0})
                </option>
              ))}
              <option value="all">제{MIN_MANAGED_SESSION}회 이후 전체</option>
            </select>
          )}

          <select
            value={selectedCommittee}
            onChange={(e) => setSelectedCommittee(e.target.value)}
            aria-label="위원회 선택"
            data-testid="committee-select"
            className="min-w-0 shrink-0 rounded-md border border-border-strong bg-white px-3 py-2 text-sm text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
          >
            <option value="all">전체 위원회</option>
            {committees.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </div>

        {bulkResult && (
          <div
            className="mb-4 p-3 rounded-md border border-success/30 bg-success/10 text-sm text-success"
            data-testid="bulk-result"
          >
            <strong>VOD 일괄 등록 결과</strong> — 새 회의 등록 {bulkResult.created}건, 기존 회의에 영상 연결 {bulkResult.matched}건
            {bulkResult.promoted > 0 && `, 회기 먼저 표시 ${bulkResult.promoted}건 (영상 변환 대기)`}
            {bulkResult.matched + bulkResult.created + bulkResult.promoted === 0 && (
              <span>{' '}— 의회 홈페이지의 회의가 모두 이미 등록되어 있어 새로 추가된 건이 없습니다.</span>
            )}
            {bulkResult.errors > 0 && `, 처리 오류 ${bulkResult.errors}건`}
            {bulkResult.promoted > 0 && (
              <span className="block mt-1 text-xs text-success">
                방금 방송한 회기는 정식 제목·회기 탭으로 먼저 표시됩니다. KMS 영상 변환(방송 직후 몇 시간)이 끝나면 영상이 자동 연결됩니다.
              </span>
            )}
            <span className="block mt-1 text-xs text-success">
              {bulkResult.created > 0
                ? '새로 등록된 회의는 영상만 연결됐습니다. AI 자막이 필요하면 해당 회의를 체크한 뒤 [AI 자막 생성]을 눌러주세요.'
                : '자막은 생성하지 않았습니다. AI 자막이 필요한 회의를 체크한 뒤 [AI 자막 생성] 버튼을 눌러주세요.'}
            </span>
          </div>
        )}

        {genProgress && (
          <div
            className="mb-4 p-3 rounded-md border border-primary-20 bg-primary-5 text-sm text-primary-dark space-y-1"
            data-testid="generate-progress"
          >
            {generating ? (
              <div className="space-y-1.5">
                <div className="flex items-center gap-2">
                  <span className="inline-block w-3.5 h-3.5 border-2 border-primary border-t-transparent rounded-full animate-spin shrink-0" aria-hidden="true" />
                  <span>
                    🤖 <strong>AI 자막 생성 중 ({genProgress.current}/{genProgress.total}번째 회의)</strong> — {genProgress.title}
                  </span>
                </div>
                {/* 현재 회의 세부 진행률 바 + % (서버 실측: 다운로드→전사 청크→저장) */}
                <div className="flex items-center gap-2" data-testid="generate-step-progress">
                  <div className="flex-1 h-2 rounded-full bg-primary-10 overflow-hidden">
                    <div
                      className="h-full bg-primary rounded-full transition-all duration-700 ease-out"
                      style={{ width: `${Math.round((genProgress.stepProgress ?? 0) * 100)}%` }}
                    />
                  </div>
                  <span className="tabular-nums text-xs font-semibold text-primary-dark w-9 text-right">
                    {Math.round((genProgress.stepProgress ?? 0) * 100)}%
                  </span>
                </div>
                <span className="block text-xs text-primary-dark">
                  현재 단계: {genProgress.stepMessage || '준비 중'} · 회의당 약 10분 — 페이지를 닫거나 이동해도 서버에서 계속 진행됩니다
                </span>
              </div>
            ) : (
              <div>
                <strong>AI 자막 생성 완료</strong> — 성공 {genProgress.done.length}건
                {genProgress.failed.length > 0 && `, 실패 ${genProgress.failed.length}건 (${genProgress.failed.join(', ')})`}
              </div>
            )}
          </div>
        )}

        {isLoading ? (
          <TableSkeleton rows={8} columns={5} />
        ) : error ? (
          <Card padding="lg">
            <div className="py-8 text-center space-y-3">
              <svg className="w-12 h-12 mx-auto text-gray-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
              </svg>
              <p className="text-error font-medium">데이터를 불러올 수 없습니다</p>
              <p className="text-sm text-gray-500">백엔드 연결을 확인해주세요.</p>
              <Button
                variant="primary"
                onClick={() => window.location.reload()}
                className="mt-2"
              >
                다시 시도
              </Button>
            </div>
          </Card>
        ) : scopedVods.length === 0 ? (
          <Card padding="none">
            <EmptyState
              title="표시할 회의가 없습니다"
              description={
                scopedVods.length > 0 || searchQuery || selectedCommittee !== 'all'
                  ? '검색어·위원회·상태 조건에 맞는 회의가 없습니다. 조건을 넓혀보세요.'
                  : `${sessionLabel} 회기에 등록된 회의가 아직 없습니다. 회기 시작 후 [VOD 일괄 등록]을 누르면 의회 홈페이지에서 자동으로 가져옵니다.`
              }
            />
          </Card>
        ) : (
          <div className="space-y-6">
            <VodTable
              vods={scopedVods}
              selectable={isAdmin} // 체크박스는 AI 자막 생성(관리자 전용)용이라 함께 숨김
              selectedIds={selectedIds}
              onToggleSelect={handleToggleSelect}
            />

            {totalPages > 1 && (
              <Pagination
                currentPage={currentPage}
                totalPages={totalPages}
                onPageChange={handlePageChange}
              />
            )}
          </div>
        )}
      </div>

      <AdminPinModal
        open={pinOpen}
        onClose={() => {
          setPinOpen(false);
          pendingActionRef.current = null;
        }}
        onSuccess={() => {
          const action = pendingActionRef.current;
          pendingActionRef.current = null;
          if (action === 'bulk') void runBulkMatch();
          else if (action === 'generate') confirmAndGenerate();
        }}
        description="이 작업은 관리자 권한이 필요합니다. 4자리 PIN을 입력해 주세요."
      />
    </div>
  );
}
