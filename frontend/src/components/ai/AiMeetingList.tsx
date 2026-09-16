'use client';

/**
 * AI 어시스턴트의 회의 선택 목록(2026-09-14).
 *
 * ClipMeetingList 를 그대로 쓰지 않은 이유(Codex 검토): 그쪽은 VOD 유무로 선택을 막고 「의원 구분」 배지·클립 인덱스 판정에
 * 묶여 있다. 여기서 고를 수 있는 조건은 "자막이 있는 회의"(실시간 자막 중이거나 AI 자막 이후) 다.
 * 재사용하는 것: useVodList(페이징)·MeetingStageBadge·committeeOf·의원 이름 검색 API(발언영상과 같은 API).
 */

import React, { useEffect, useMemo, useState } from 'react';

import { committeeOf } from '@/components/clips/ClipMeetingList';
import MeetingStageBadge from '@/components/MeetingStageBadge';
import { useVodList } from '@/hooks/useVodList';
import { findClipMeetingsByMember } from '@/lib/api';
import type { MeetingType } from '@/types';

const PAGE = 100;

export interface AiMeetingListProps {
  /** null = 아직 고르지 않음 */
  selectedId: string | null;
  onSelect: (meeting: MeetingType) => void;
}

/** 대화·요약을 할 수 있는 회의 — 자막이 있어야 한다 */
export function canAskAbout(m: Pick<MeetingType, 'status' | 'subtitle_stage'>): boolean {
  if (m.status === 'live') return true;
  const stage = m.subtitle_stage ?? 'none';
  return stage !== 'none';
}

export default function AiMeetingList({ selectedId, onSelect }: AiMeetingListProps) {
  const [q, setQ] = useState('');
  // 페이지를 올려 가며 누적한다 — useVodList 는 limit 100 상한이라 perPage 를 키워도 새 회의가 오지 않는다(Codex 검토)
  const [page, setPage] = useState(1);
  const [acc, setAcc] = useState<MeetingType[]>([]);
  const { vods: pageVods, isLoading, error, hasNext } = useVodList({ page, perPage: PAGE, statuses: 'live,processing,ended' });
  useEffect(() => {
    if (!pageVods.length) return;
    setAcc((prev) => {
      const byId = new Map(pageVods.map((m) => [m.id, m]));
      // 같은 회의라도 subtitle_stage 등이 바뀌면(재조회) 새 행으로 바꾼다 — 자막이 생겨도 비활성으로 남던 문제(Codex 2차)
      let changed = false;
      const merged = prev.map((m) => {
        const n = byId.get(m.id);
        if (n && (n.subtitle_stage !== m.subtitle_stage || n.status !== m.status || n.vod_url !== m.vod_url || n.title !== m.title)) {
          changed = true;
          return n;
        }
        return m;
      });
      const seen = new Set(prev.map((m) => m.id));
      const fresh = pageVods.filter((m) => !seen.has(m.id));
      if (!fresh.length && !changed) return prev; // 같은 목록이면 상태를 바꾸지 않는다(새 배열을 만들면 렌더 루프)
      if (page === 1) return [...pageVods, ...merged.filter((m) => !byId.has(m.id))];
      return [...merged, ...fresh];
    });
  }, [pageVods, page]);
  const vods = acc.length ? acc : pageVods;

  // 의원 이름 검색 — 발언영상 화면과 같은 규칙(한글 2~10자, 300ms 디바운스, 서버가 그 이름이 나온 회의를 준다)
  const qTrim = q.trim();
  const [memberHits, setMemberHits] = useState<{ name: string; ids: Set<string> } | null>(null);
  useEffect(() => {
    if (!/^[가-힣]{2,10}$/.test(qTrim)) {
      setMemberHits(null);
      return undefined;
    }
    let cancelled = false;
    const timer = setTimeout(() => {
      findClipMeetingsByMember(qTrim)
        .then((r) => {
          if (!cancelled) setMemberHits({ name: qTrim, ids: new Set(r.meeting_ids) });
        })
        .catch(() => {
          if (!cancelled) setMemberHits(null);
        });
    }, 300);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [qTrim]);
  const memberIds = memberHits && memberHits.name === qTrim ? memberHits.ids : null;

  const filtered = useMemo(() => {
    const needle = qTrim.toLowerCase();
    return vods.filter((v) => {
      if (!needle) return true;
      if (`${v.title ?? ''} ${committeeOf(v) ?? ''} ${v.meeting_date ?? ''}`.toLowerCase().includes(needle)) return true;
      return Boolean(memberIds?.has(v.id));
    });
  }, [vods, qTrim, memberIds]);

  const rowBase = 'w-full rounded-lg border px-2.5 py-2 text-left transition-colors';
  const rowOn = 'border-primary bg-primary/5 ring-1 ring-primary/40';
  const rowOff = 'border-border bg-white hover:bg-gray-50';

  return (
    <div data-testid="ai-meeting-list" className="flex h-full min-h-0 flex-col gap-2">
      <input
        data-testid="ai-meeting-search"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder="회의명·의원 이름 (예: 보건복지, 홍길동)"
        className="rounded-md border border-border px-2 py-1.5 text-[13px]"
        aria-label="회의 검색"
      />
      {error && <div className="text-[12px] text-red-700">회의 목록을 불러오지 못했습니다: {error.message}</div>}
      {isLoading && !vods.length && <div className="text-[12px] text-text-muted">불러오는 중…</div>}
      <ul className="flex min-h-0 flex-1 flex-col gap-1 overflow-y-auto pr-0.5">
        {filtered.map((m) => {
          const active = m.id === selectedId;
          const askable = canAskAbout(m);
          return (
            <li key={m.id}>
              <button
                type="button"
                data-testid="ai-meeting-row"
                onClick={() => askable && onSelect(m)}
                disabled={!askable}
                title={askable ? m.title : '아직 자막이 없는 회의입니다 — VOD 등록 뒤 AI 자막이 만들어지면 고를 수 있습니다'}
                className={`${rowBase} ${active ? rowOn : rowOff} ${askable ? '' : 'cursor-not-allowed opacity-50'}`}
              >
                <div className="line-clamp-2 text-[13px] font-semibold leading-snug text-text">{m.title}</div>
                <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-[11px] tabular-nums text-text-muted">
                  <span>{m.meeting_date}</span>
                  <MeetingStageBadge meeting={m} />
                  {memberIds?.has(m.id) && (
                    <span data-testid="ai-member-hit" className="rounded bg-primary/10 px-1 font-semibold text-primary">
                      {memberHits?.name} 의원
                    </span>
                  )}
                </div>
              </button>
            </li>
          );
        })}
        {!isLoading && !filtered.length && <li className="p-2 text-[12px] text-text-muted">검색 결과가 없습니다.</li>}
        {hasNext && (
          <li>
            <button
              type="button"
              onClick={() => setPage((n) => n + 1)}
              className="w-full rounded-md border border-dashed border-border px-2 py-1.5 text-[12px] text-text-muted hover:bg-gray-50"
            >
              {qTrim ? '이전 회의까지 더 불러와 찾기' : '이전 회의 더 보기'}
            </button>
          </li>
        )}
      </ul>
    </div>
  );
}
