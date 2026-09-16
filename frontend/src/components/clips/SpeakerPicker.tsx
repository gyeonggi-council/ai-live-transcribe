'use client';

import React from 'react';

import { Callout } from '@/components/ui';
import type { ClipIndexType, ClipSpeakerType } from '@/types';
import { formatHMS, formatLen } from '@/utils/clipTime';

/**
 * 구간 출처 배지 — 연동 계약 §6 (공식 인덱스 / AI 자막(잠정)).
 * 'live' 는 2026-09-08 에 인덱스 출처에서 뺐다(VOD 와 시간축이 달라 엉뚱한 의원이 잘림) — 옛 추출 기록 표시용으로만 남긴다.
 */
export const SOURCE_LABEL: Record<string, string> = {
  official: '공식 인덱스',
  ai: 'AI 자막(잠정)',
  live: '실시간 자막(초안)',
  none: '인덱스 없음 · 수동 자르기',
  manual: '수동',
};

const SOURCE_TONE: Record<string, string> = {
  official: 'bg-green-100 text-green-800 border-green-200',
  ai: 'bg-amber-100 text-amber-800 border-amber-200',
  live: 'bg-orange-100 text-orange-800 border-orange-200',
  none: 'bg-gray-100 text-gray-700 border-gray-200',
  manual: 'bg-gray-100 text-gray-700 border-gray-200',
};

export function SourceBadge({ source }: { source: string }) {
  return (
    <span
      data-testid="source-badge"
      className={`inline-flex items-center rounded-md border px-2 py-0.5 text-[12px] font-semibold ${
        SOURCE_TONE[source] ?? SOURCE_TONE.none
      }`}
    >
      {SOURCE_LABEL[source] ?? source}
    </span>
  );
}

export interface SpeakerPickerProps {
  /** 이 회의의 위원회 — 카드의 위원회 칩에서 「겸임」 을 가른다(2026-09-11). 본회의·모름이면 null */
  meetingCommittee?: string | null;
  index: ClipIndexType | null;
  isLoading: boolean;
  error: Error | null;
  selectedKey: string | null;
  onSelect: (speaker: ClipSpeakerType) => void;
  /** 표시용 시간 보정(초). source=live 폴백을 없앤 뒤(2026-09-08) 항상 0 — 오프셋 플럼빙 정리 대상 */
  shift: number;
  /** 서버가 자동으로 잘라 둔 영상이 준비된 의원 이름(2026-09-10) — 카드에 「영상 준비됨」 */
  readyNames?: ReadonlySet<string>;
}

const normCommittee = (v: string) => v.replace(/\s+/g, '');

/**
 * 카드의 위원회 칩 — 이 회의 위원회는 회색, 그 밖(겸임)은 「○○ 겸임」 (2026-09-11 담당자 요청).
 * '위원회' 를 떼서 짧게 쓰고, 위원장·부위원장이면 붙인다. 본회의(위원회 모름)면 겸임 표시 없이 전부 회색.
 */
export function committeeChips(
  committees: { name: string; role: string }[] | undefined,
  meetingCommittee: string | null | undefined
): { label: string; concurrent: boolean }[] {
  // 본회의·모름이면 겸임을 가르지 않는다(committeeOf 는 본회의에 '본회의' 를 돌려준다)
  const home = meetingCommittee && /위원회$/.test(meetingCommittee.trim()) ? normCommittee(meetingCommittee) : null;
  return (committees ?? [])
    .filter((c) => c.name)
    .map((c) => {
      const short = c.name.replace(/위원회$/, '');
      const role = c.role && c.role !== '위원' ? ` ${c.role}` : '';
      const concurrent = Boolean(home) && normCommittee(c.name) !== home;
      return { label: `${short}${role}${concurrent ? ' 겸임' : ''}`, concurrent };
    })
    .sort((a, b) => Number(a.concurrent) - Number(b.concurrent));
}

export default function SpeakerPicker(p: SpeakerPickerProps) {
  const { index } = p;
  const source = index?.source ?? 'none';
  const provisional = source === 'ai';

  return (
    <div data-testid="speaker-picker" className="flex flex-col gap-2 h-full min-h-0">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-[15px] font-bold text-text">② 의원 선택</h2>
        {index && <SourceBadge source={source} />}
      </div>

      {p.isLoading && <div className="text-sm text-text-muted py-6 text-center">발언 구간을 찾는 중…</div>}
      {p.error && (
        <Callout variant="danger" className="!p-2 !text-xs">
          구간 정보를 불러오지 못했습니다: {p.error.message}
        </Callout>
      )}

      {index && provisional && (
        <div data-testid="provisional-warning">
          <Callout variant="warning" className="!p-2 !text-xs">
            AI 자막으로 추정한 구간입니다 — 의원의 질의부터 집행부 답변까지 한 구간으로 묶었습니다. 시작·끝을 영상에서 확인하세요.
          </Callout>
        </div>
      )}
      {index && !index.speakers.length && !p.isLoading && (
        <div data-testid="speaker-empty" className="text-xs text-text-muted leading-relaxed rounded-lg border border-dashed border-border p-3">
          {index.warnings.length ? index.warnings.join(' ') : '발언 구간 정보가 없습니다.'}
          <br />
          오른쪽 영상에서 <b>시작 [ · 종료 ]</b> 로 직접 구간을 지정해 추출할 수 있습니다.
        </div>
      )}

      <ul className="flex-1 min-h-0 overflow-y-auto flex flex-col gap-1.5 pr-0.5" data-testid="speaker-list">
        {index?.speakers.map((sp) => {
          const active = sp.key === p.selectedKey;
          const first = sp.segments[0];
          return (
            <li key={sp.key}>
              <button
                type="button"
                data-testid="speaker-card"
                onClick={() => p.onSelect(sp)}
                className={`w-full text-left rounded-lg border p-2 flex items-center gap-2 transition-colors ${
                  active ? 'border-primary bg-primary/5 ring-1 ring-primary/40' : 'border-border bg-white hover:bg-gray-50'
                }`}
              >
                <div className="w-11 h-14 rounded-md bg-gray-100 overflow-hidden flex-none flex items-center justify-center text-gray-400 text-lg">
                  {sp.photo_url ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img
                      src={sp.photo_url}
                      alt=""
                      className="w-full h-full object-cover"
                      onError={(e) => {
                        (e.currentTarget as HTMLImageElement).style.display = 'none';
                      }}
                    />
                  ) : (
                    '👤'
                  )}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-baseline gap-1 flex-wrap">
                    <span className="font-bold text-[15px] text-text truncate">{sp.name}</span>
                    <span className="text-[12px] text-text-muted">{sp.role || '의원'}</span>
                    {committeeChips(sp.committees, p.meetingCommittee).map((c) => (
                      <span
                        key={c.label}
                        data-testid="speaker-committee"
                        className={`flex-none rounded px-1 py-px text-[11px] leading-4 ${
                          c.concurrent ? 'bg-primary/10 text-primary font-semibold' : 'bg-gray-100 text-gray-700'
                        }`}
                      >
                        {c.label}
                      </span>
                    ))}
                    {p.readyNames?.has(sp.name) && (
                      <span
                        data-testid="auto-clip-ready"
                        className="ml-auto flex-none rounded bg-green-100 px-1.5 py-0.5 text-[10px] font-semibold text-green-800"
                      >
                        영상 준비됨
                      </span>
                    )}
                  </div>
                  <div className="text-[12px] text-text-muted truncate">
                    {[sp.party, sp.district].filter(Boolean).join(' · ') || '—'}
                  </div>
                  <div className="text-[12px] text-primary font-semibold tabular-nums">
                    {sp.segments.length}개 구간 · {formatLen(sp.total_seconds)}
                    {first && (
                      <span className="text-text-muted font-normal"> · 첫 발언 {formatHMS(first.start + p.shift)}</span>
                    )}
                  </div>
                </div>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
