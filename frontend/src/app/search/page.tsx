'use client';

import React, { useState, useEffect, useMemo } from 'react';

import { useRouter, useSearchParams } from 'next/navigation';

import PageHeader from '@/components/PageHeader';
import Pagination from '@/components/Pagination';
import SearchResultPreview from '@/components/search/SearchResultPreview';
import { Button, Callout, Card, Input } from '@/components/ui';
import { globalSearch } from '@/lib/api';
import type { SearchResultItem, SearchResponse } from '@/lib/api';

/**
 * 통합검색 (/search)
 *
 * ── 2026-08-25 개선안 2h ────────────────────────────────────────────────────
 * - **결과를 회의별로 묶는다.** "47건이 회의 6건에서 나왔다"는 사실이 예전에는 전혀
 *   보이지 않았다. 같은 회의에서 열 번 언급되면 그 열 줄이 목록을 채워, 정작
 *   "어느 회의에서 이 얘기를 했나"를 알 수 없었다. API 응답에 이미
 *   `meeting_id · meeting_title · meeting_date` 가 있어 화면단 묶기만으로 된다.
 * - **기간·발언자 필터를 접어두지 않는다.** 현재 값이 적힌 칩으로 항상 노출한다 —
 *   검색 결과가 왜 이만큼인지 접지 않고 보인다.
 * - 결과 줄을 **시간 칩 + 발언자 + 본문**으로 자막 패널과 같은 어휘로 맞췄다.
 * - 이전/다음 버튼 두 개를 회의 목록에서 쓰는 `Pagination` 으로 교체 —
 *   몇 페이지 중 몇 번째인지 알 수 있다.
 *
 * ── 2026-08-25 그 자리에서 보기 ──────────────────────────────────────────────
 * 결과 줄을 누르면 **회의 상세로 페이지를 옮기지 않고 그 줄 바로 아래에서** 해당
 * 발언 시점부터 영상을 재생한다. 검색은 "이게 내가 찾던 발언인가"를 여러 건 훑어
 * 확인하는 일인데, 예전에는 한 건 확인할 때마다 화면이 통째로 바뀌고 뒤로가기로
 * 돌아와야 했다 — 결과가 47건이면 그 왕복을 47번 한다.
 * 회의 상세로 가는 것은 영상 옆 **[이 회의로 이동]** 을 눌렀을 때뿐이고,
 * 그때는 `?t=` 로 시점을 넘겨 같은 자리에서 이어 본다.
 */

/** 초 → "00:12:41" — 자막 패널·AI 참조 카드와 같은 모양 */
function formatAt(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${pad(Math.floor(s / 3600))}:${pad(Math.floor((s % 3600) / 60))}:${pad(s % 60)}`;
}

/** 검색어 하이라이트 */
function highlightText(text: string, query: string): React.ReactNode {
  if (!query) return text;
  const parts = text.split(new RegExp(`(${query})`, 'gi'));
  return parts.map((part, i) =>
    part.toLowerCase() === query.toLowerCase() ? (
      <mark key={i} className="rounded-sm bg-highlight px-0.5 text-text">
        {part}
      </mark>
    ) : (
      part
    ),
  );
}

interface SearchGroup {
  meetingId: string;
  title: string;
  date: string;
  hits: SearchResultItem[];
}

/** 이 페이지에 실린 결과를 회의별로 묶는다 (응답 순서를 유지) */
function groupByMeeting(items: SearchResultItem[]): SearchGroup[] {
  const order: string[] = [];
  const map = new Map<string, SearchGroup>();

  items.forEach((item) => {
    const key = item.meeting_id;
    let group = map.get(key);
    if (!group) {
      group = {
        meetingId: key,
        title: item.meeting_title,
        date: item.meeting_date,
        hits: [],
      };
      map.set(key, group);
      order.push(key);
    }
    group.hits.push(item);
  });

  return order.map((k) => map.get(k)!);
}

/** 결과 줄 하나 — 시간 칩 + 발언자 + 본문 */
function HitRow({
  item,
  query,
  active,
  onOpen,
}: {
  item: SearchResultItem;
  query: string;
  /** 이 줄의 미리보기가 지금 펼쳐져 있는가 */
  active: boolean;
  onOpen: (item: SearchResultItem) => void;
}) {
  return (
    <button
      type="button"
      onClick={() => onOpen(item)}
      data-testid="search-hit"
      aria-expanded={active}
      className={`flex w-full items-start gap-3 border-b border-border-subtle px-4 py-3 text-left transition-colors last:border-b-0 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-primary ${
        active ? 'bg-primary-5' : 'hover:bg-primary-5/40'
      }`}
    >
      <span className="mt-0.5 inline-flex shrink-0 items-center gap-1 rounded bg-primary/10 px-1.5 py-0.5 font-mono text-[11.5px] text-primary">
        <span className="text-[9px] leading-none" aria-hidden="true">
          ▶
        </span>
        {formatAt(item.start_time)}
      </span>
      {item.speaker && (
        <span className="mt-px shrink-0 rounded-full bg-blue-50 px-2 py-0.5 text-xs font-semibold text-blue-700">
          {item.speaker}
        </span>
      )}
      <span className="min-w-0 flex-1 text-[14.5px] leading-relaxed text-text-secondary">
        {highlightText(item.text, query)}
      </span>
      {/* 펼쳐지면 화살표가 아래를 가리킨다 — 이동이 아니라 '여기서 열림'이라는 표시 */}
      <svg
        className={`mt-1 h-[15px] w-[15px] shrink-0 transition-transform ${
          active ? 'rotate-90 text-primary' : 'text-text-dim'
        }`}
        fill="none"
        stroke="currentColor"
        strokeWidth={2}
        viewBox="0 0 24 24"
        aria-hidden="true"
      >
        <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
      </svg>
    </button>
  );
}

/**
 * 검색 페이지 컨텐츠 (Suspense 내부)
 */
function SearchPageContent() {
  const router = useRouter();
  const searchParams = useSearchParams();

  // URL 쿼리에서 초기값 추출
  const initialQuery = searchParams.get('q') || '';
  const initialDateFrom = searchParams.get('date_from') || '';
  const initialDateTo = searchParams.get('date_to') || '';
  const initialSpeaker = searchParams.get('speaker') || '';

  // 상태
  const [query, setQuery] = useState(initialQuery);
  const [dateFrom, setDateFrom] = useState(initialDateFrom);
  const [dateTo, setDateTo] = useState(initialDateTo);
  const [speaker, setSpeaker] = useState(initialSpeaker);
  /** 필터는 접어두지 않는다 — 다만 '값을 고치는 자리'는 칩을 눌렀을 때만 편다 */
  const [editingFilters, setEditingFilters] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [results, setResults] = useState<SearchResponse | null>(null);
  const [offset, setOffset] = useState(0);
  /**
   * 지금 펼쳐 놓은 미리보기 — **페이지 전체에 하나뿐**이다.
   * 목록에 영상을 여러 개 깔지 않는 것이 핵심이다(서비스 CLAUDE.md: KMS MP4 는
   * moov 가 파일 끝에 있어 1시간짜리가 937MB — 목록에 preload 를 깔았다가
   * "느리다" 신고를 받은 전례가 있다).
   */
  const [preview, setPreview] = useState<SearchResultItem | null>(null);
  /** 같은 줄을 다시 눌러도 그 시점으로 되돌아가게 하는 증가값 */
  const [seekNonce, setSeekNonce] = useState(0);

  const limit = 20;

  // 검색 실행
  const executeSearch = async (newOffset = 0) => {
    if (!query.trim()) {
      setError('검색어를 입력해주세요');
      return;
    }

    setIsLoading(true);
    setError(null);
    // 결과 집합이 바뀌면 열려 있던 미리보기는 의미가 없다 — 먼저 닫는다
    setPreview(null);

    try {
      const response = await globalSearch({
        q: query,
        date_from: dateFrom || undefined,
        date_to: dateTo || undefined,
        speaker: speaker || undefined,
        limit,
        offset: newOffset,
      });

      setResults(response);
      setOffset(newOffset);

      // URL 업데이트
      const params = new URLSearchParams({ q: query });
      if (dateFrom) params.set('date_from', dateFrom);
      if (dateTo) params.set('date_to', dateTo);
      if (speaker) params.set('speaker', speaker);
      router.replace(`/search?${params.toString()}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : '검색 중 오류가 발생했습니다');
      setResults(null);
    } finally {
      setIsLoading(false);
    }
  };

  // 검색 버튼 클릭
  const handleSearch = () => {
    executeSearch(0);
  };

  // Enter 키 핸들링
  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      handleSearch();
    }
  };

  // 결과 클릭 → **페이지를 옮기지 않고** 그 줄 아래에서 그 발언 시점부터 재생.
  // 같은 줄을 다시 누르면 닫힌다.
  const handleResultClick = (item: SearchResultItem) => {
    setPreview((prev) => (prev?.subtitle_id === item.subtitle_id ? null : item));
    setSeekNonce((n) => n + 1);
  };

  // 영상 옆 [이 회의로 이동] — 예전에 줄 클릭이 하던 그 이동이다.
  // `?t=` 는 회의 상세가 읽어 그 시점에서 이어 본다.
  const handleOpenMeeting = (item: SearchResultItem) => {
    router.push(`/vod/${item.meeting_id}?t=${Math.floor(item.start_time)}`);
  };

  // 초기 로드 시 쿼리가 있으면 자동 검색
  useEffect(() => {
    if (initialQuery) {
      executeSearch(0);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const groups = useMemo(() => groupByMeeting(results?.items ?? []), [results]);
  const totalPages = results ? Math.max(1, Math.ceil(results.total / limit)) : 1;
  const currentPage = Math.floor(offset / limit) + 1;

  const dateLabel =
    dateFrom || dateTo ? `${dateFrom || '처음'} ~ ${dateTo || '오늘'}` : '전체';

  return (
    <div className="p-6">
      <div className="mx-auto flex max-w-[1000px] flex-col gap-4">
        <PageHeader
          title="통합검색"
          description="회의 자막 전문을 키워드·기간·발언자로 찾습니다."
          className="mb-1"
        />

        {/* 검색 한 줄 */}
        <div className="flex gap-2">
          <div className="min-w-0 flex-1">
            <Input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyPress={handleKeyPress}
              placeholder="검색어를 입력하세요"
            />
          </div>
          <Button onClick={handleSearch} loading={isLoading} variant="primary" size="md" className="px-6">
            {isLoading ? '검색 중...' : '검색'}
          </Button>
        </div>

        {/* 필터 — 접지 않는다. 현재 값이 칩에 적혀 있고, 누르면 그 자리에서 고친다 */}
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => setEditingFilters((v) => !v)}
            data-testid="filter-chip-date"
            aria-expanded={editingFilters}
            className="inline-flex h-8 items-center gap-1.5 rounded-md border border-border-strong bg-surface px-3 text-[13px] text-text-secondary transition-colors hover:bg-surface-raised"
          >
            <svg className="h-3.5 w-3.5 text-text-dim" fill="none" stroke="currentColor" strokeWidth={1.75} viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M6.75 3v2.25M17.25 3v2.25M3 18.75V7.5a2.25 2.25 0 012.25-2.25h13.5A2.25 2.25 0 0121 7.5v11.25m-18 0A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75m-18 0v-7.5A2.25 2.25 0 015.25 9h13.5A2.25 2.25 0 0121 11.25v7.5" />
            </svg>
            기간 <span className="font-semibold tabular-nums text-text">{dateLabel}</span>
          </button>

          <button
            type="button"
            onClick={() => setEditingFilters((v) => !v)}
            data-testid="filter-chip-speaker"
            aria-expanded={editingFilters}
            className="inline-flex h-8 items-center gap-1.5 rounded-md border border-border-strong bg-surface px-3 text-[13px] text-text-secondary transition-colors hover:bg-surface-raised"
          >
            <svg className="h-3.5 w-3.5 text-text-dim" fill="none" stroke="currentColor" strokeWidth={1.75} viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M15 19.128a9.38 9.38 0 002.625.372 9.337 9.337 0 004.121-.952 4.125 4.125 0 00-7.533-2.493M15 19.128v-.003c0-1.113-.285-2.16-.786-3.07M15 19.128v.106A12.318 12.318 0 018.624 21c-2.331 0-4.512-.645-6.374-1.766l-.001-.109a6.375 6.375 0 0111.964-3.07M12 6.375a3.375 3.375 0 11-6.75 0 3.375 3.375 0 016.75 0zm8.25 2.25a2.625 2.625 0 11-5.25 0 2.625 2.625 0 015.25 0z" />
            </svg>
            발언자{' '}
            <span className={speaker ? 'font-semibold text-text' : 'text-text-dim'}>
              {speaker || '전체'}
            </span>
          </button>

          {results && (
            <span className="ml-auto text-[13px] text-text-muted">
              <b className="tabular-nums text-text">{results.total}건</b> · 회의{' '}
              <b className="tabular-nums text-text">{groups.length}</b>건에서
            </span>
          )}
        </div>

        {editingFilters && (
          <Card padding="md" className="flex flex-col gap-3">
            <div>
              <label className="mb-1 block text-sm font-medium text-text-secondary">날짜 범위</label>
              <div className="flex items-center gap-2">
                <input
                  type="date"
                  value={dateFrom}
                  onChange={(e) => setDateFrom(e.target.value)}
                  className="rounded-md border border-gray-300 bg-white px-3 py-2 text-text focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/30"
                />
                <span className="text-text-muted">~</span>
                <input
                  type="date"
                  value={dateTo}
                  onChange={(e) => setDateTo(e.target.value)}
                  className="rounded-md border border-gray-300 bg-white px-3 py-2 text-text focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/30"
                />
              </div>
            </div>
            <Input
              type="text"
              label="화자 필터"
              value={speaker}
              onChange={(e) => setSpeaker(e.target.value)}
              placeholder="화자 이름 입력 (예: 화자 1)"
            />
          </Card>
        )}

        {/* 에러 메시지 */}
        {error && <Callout variant="danger">{error}</Callout>}

        {/* 결과 — 회의별로 묶는다 */}
        {results && (
          <>
            {results.items.length === 0 && (
              <Card padding="none" className="p-8 text-center text-text-muted">
                검색 결과가 없습니다
              </Card>
            )}

            {groups.length > 0 && (
              <div className="flex flex-col gap-3.5" data-testid="search-groups">
                {groups.map((group) => (
                  <div
                    key={group.meetingId}
                    data-testid="search-group"
                    className="overflow-hidden rounded-[10px] border border-border bg-surface"
                  >
                    <div className="flex items-center gap-3 border-b border-border bg-gray-50 px-4 py-2.5">
                      <span className="min-w-0 flex-1 truncate text-[14.5px] font-bold tracking-heading text-text">
                        {group.title}
                      </span>
                      <span className="shrink-0 text-[12.5px] tabular-nums text-text-muted">
                        {group.date}
                      </span>
                      <span className="inline-flex h-[22px] shrink-0 items-center rounded-full bg-primary-5 px-2.5 text-[11.5px] font-bold tabular-nums text-primary-dark">
                        {group.hits.length}건
                      </span>
                    </div>
                    {/* 줄과 미리보기를 **같은 부모의 평평한 배열**로 낸다.
                        Fragment 로 감싸 중첩시키면 다른 줄을 눌렀을 때 부모가 바뀌어
                        영상이 통째로 다시 로드된다. 평평하게 두고 미리보기 key 를
                        회의 단위로 고정하면 React 가 DOM 노드를 '옮기기'만 해서,
                        같은 회의 안에서는 재생이 끊기지 않고 시점만 이동한다. */}
                    {group.hits.flatMap((item) => {
                      const isOpen = preview?.subtitle_id === item.subtitle_id;
                      const row = (
                        <HitRow
                          key={item.subtitle_id}
                          item={item}
                          query={query}
                          active={isOpen}
                          onOpen={handleResultClick}
                        />
                      );
                      if (!isOpen) return [row];
                      return [
                        row,
                        <SearchResultPreview
                          key={`preview-${group.meetingId}`}
                          meetingId={item.meeting_id}
                          startTime={item.start_time}
                          seekNonce={seekNonce}
                          timeLabel={formatAt(item.start_time)}
                          hit={{ text: item.text, speaker: item.speaker }}
                          onOpenMeeting={() => handleOpenMeeting(item)}
                          onClose={() => setPreview(null)}
                        />,
                      ];
                    })}
                  </div>
                ))}
              </div>
            )}

            {/* 회의 목록에서 쓰는 페이지네이션 그대로 — 몇 페이지 중 몇 번째인지 보인다 */}
            {results.items.length > 0 && totalPages > 1 && (
              <Pagination
                currentPage={currentPage}
                totalPages={totalPages}
                onPageChange={(page) => executeSearch((page - 1) * limit)}
              />
            )}
          </>
        )}
      </div>
    </div>
  );
}

/**
 * 검색 페이지 (Suspense wrapper)
 */
export default function SearchPage() {
  return (
    <React.Suspense
      fallback={
        <div className="flex min-h-screen items-center justify-center bg-surface-raised">
          <div className="text-text-muted">로딩 중...</div>
        </div>
      }
    >
      <SearchPageContent />
    </React.Suspense>
  );
}
