'use client';

import React, { useEffect, useMemo, useState } from 'react';

import MeetingStageBadge from '@/components/MeetingStageBadge';
import { useVodList } from '@/hooks/useVodList';
import { findClipMeetingsByMember } from '@/lib/api';
import type { MeetingType } from '@/types';
import { formatLen } from '@/utils/clipTime';
import { getClipIndexStatus } from '@/utils/meetingStage';

/**
 * ① 회의 목록 — 이 서비스의 meetings(KMS 자동 등록분) 에서 고른다.
 * 데스크톱 추출기는 KMS 목록을 직접 긁었지만, 웹판은 회의가 이미 등록·자막 처리된 것만 자른다.
 */
export interface ClipMeetingListProps {
  selectedId: string | null;
  onSelect: (meeting: MeetingType) => void;
  collapsed?: boolean;
  onToggleCollapsed?: () => void;
}

export function committeeOf(v: MeetingType): string | null {
  if (v.committee) return v.committee;
  const m = (v.title || '').match(/[가-힣]{2,}위원회|본회의/g);
  return m?.[m.length - 1] ?? null;
}

export default function ClipMeetingList({ selectedId, onSelect, collapsed, onToggleCollapsed }: ClipMeetingListProps) {
  const [q, setQ] = useState('');
  const { vods, isLoading, error } = useVodList({ perPage: 100, statuses: 'live,processing,ended', enabled: !collapsed });

  // 의원 이름 검색(2026-09-11 담당자 요청) — 한글 2~10자면 서버에 그 이름이 나온 회의를 묻는다(300ms 뒤, 입력이 멈추면).
  // 회의명 일치와 합친다: "보건복지" 는 제목으로, "박상현" 은 이름으로 걸린다.
  const [memberHits, setMemberHits] = useState<{ name: string; ids: Set<string> } | null>(null);
  const qTrim = q.trim();
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

  if (collapsed) {
    return (
      <div data-testid="clip-meeting-list-collapsed" className="flex flex-col items-center gap-2">
        <button
          type="button"
          onClick={onToggleCollapsed}
          className="rounded-md border border-border bg-white px-2 py-1 text-[12px] hover:bg-gray-50"
          title="회의 목록 펼치기"
        >
          ① 회의 목록 ▸
        </button>
      </div>
    );
  }

  return (
    <div data-testid="clip-meeting-list" className="flex flex-col gap-2 h-full min-h-0">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-[15px] font-bold text-text">① 회의 선택</h2>
        {onToggleCollapsed && (
          <button type="button" onClick={onToggleCollapsed} className="text-[12px] text-text-muted underline" title="목록 접기">
            접기 ◂
          </button>
        )}
      </div>
      <input
        data-testid="clip-meeting-search"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder="회의명·의원 이름 (예: 보건복지, 홍길동)"
        className="rounded-md border border-border px-2 py-1.5 text-[13px]"
      />
      {error && <div className="text-[12px] text-red-700">회의 목록을 불러오지 못했습니다: {error.message}</div>}
      {isLoading && !vods.length && <div className="text-[12px] text-text-muted">불러오는 중…</div>}
      <ul className="flex-1 min-h-0 overflow-y-auto flex flex-col gap-1 pr-0.5">
        {filtered.map((m) => {
          const active = m.id === selectedId;
          const noVod = !m.vod_url;
          // 「의원 구분」 배지 — 판정 정본은 meetingStage.getClipIndexStatus 이고
          // 설치형 프로그램의 회의 목록도 같은 규칙·같은 문구를 쓴다(2026-09-10).
          const ix = getClipIndexStatus(m);
          return (
            <li key={m.id}>
              <button
                type="button"
                data-testid="clip-meeting-row"
                onClick={() => !noVod && onSelect(m)}
                disabled={noVod}
                title={ix.ready ? m.title : ix.hint}
                className={`w-full text-left rounded-lg border px-2.5 py-2 transition-colors ${
                  active ? 'border-primary bg-primary/5 ring-1 ring-primary/40' : 'border-border bg-white hover:bg-gray-50'
                } ${noVod ? 'opacity-50 cursor-not-allowed' : ''}`}
              >
                <div className="text-[13px] font-semibold text-text leading-snug line-clamp-2">{m.title}</div>
                <div className="mt-0.5 flex items-center gap-1.5 text-[11px] text-text-muted tabular-nums flex-wrap">
                  <span>{m.meeting_date}</span>
                  {m.duration_seconds ? <span>· {formatLen(m.duration_seconds)}</span> : null}
                  {!noVod && <MeetingStageBadge meeting={m} />}
                  {memberIds?.has(m.id) && (
                    <span data-testid="clip-member-hit" className="rounded px-1 bg-primary/10 text-primary font-semibold">
                      {memberHits?.name} 의원
                    </span>
                  )}
                  <span
                    data-testid="clip-index-status"
                    title={ix.hint}
                    className={`rounded px-1 ${
                      ix.ready ? 'bg-green-50 text-green-800' : 'bg-gray-100 text-gray-600'
                    }`}
                  >
                    {ix.label}
                  </span>
                </div>
              </button>
            </li>
          );
        })}
        {!isLoading && !filtered.length && (
          <li className="text-[12px] text-text-muted p-2">검색 결과가 없습니다.</li>
        )}
      </ul>
    </div>
  );
}
