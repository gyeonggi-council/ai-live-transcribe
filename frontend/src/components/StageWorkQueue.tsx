'use client';

import Link from 'next/link';

import type { MeetingType } from '@/types';
import { groupByStage, type StageGroupKey } from '@/utils/stageBadge';

export interface StageWorkQueueProps {
  vods: MeetingType[];
  className?: string;
}

interface CardConfig {
  key: StageGroupKey;
  title: string;
  description: string;
  accent: string;
  iconBg: string;
  emoji: string;
}

const CARDS: CardConfig[] = [
  {
    key: 'draft',
    title: '초안 (라이브)',
    description: '실시간 STT로 수집 중',
    accent: 'border-gray-300 text-gray-700',
    iconBg: 'bg-gray-100 text-gray-600',
    emoji: '📝',
  },
  {
    key: 'ai_waiting',
    title: 'AI 자막 대기',
    description: 'VOD 등록 후 MP3 업로드 필요',
    accent: 'border-warning-bg/40 text-warning',
    iconBg: 'bg-warning-bg/20 text-warning',
    emoji: '⏳',
  },
  {
    key: 'reviewing',
    title: '속기사 교정중',
    description: 'AI 자막 검토·수정 중',
    accent: 'border-primary-30 text-primary-dark',
    iconBg: 'bg-primary-10 text-primary-dark',
    emoji: '✍️',
  },
  {
    key: 'final',
    title: '교정 완료',
    description: '최종 확정',
    accent: 'border-success/30 text-success',
    iconBg: 'bg-success/10 text-success',
    emoji: '✅',
  },
];

export default function StageWorkQueue({ vods, className = '' }: StageWorkQueueProps) {
  const groups = groupByStage(vods);

  return (
    <section className={`space-y-3 ${className}`.trim()}>
      <div className="flex items-baseline gap-2">
        <h2 className="text-sm font-semibold text-text-muted tracking-wide uppercase">
          WORKFLOW · 단계별 진행 상황
        </h2>
        <span className="text-xs text-text-muted">
          초안 → AI 자막 → 속기사 교정 → 확정
        </span>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3">
        {CARDS.map((c) => {
          const items = groups[c.key];
          return (
            <div
              key={c.key}
              className={`bg-white rounded-lg border ${c.accent} p-4 flex flex-col gap-2`}
            >
              <div className="flex items-center justify-between">
                <div className={`w-9 h-9 rounded-md flex items-center justify-center text-lg ${c.iconBg}`}>
                  {c.emoji}
                </div>
                <span className="text-2xl font-bold">{items.length}</span>
              </div>
              <div>
                <p className="text-sm font-semibold">{c.title}</p>
                <p className="text-xs text-text-muted">{c.description}</p>
              </div>
              {items.length > 0 && (
                <ul className="mt-1 space-y-1 pt-2 border-t border-gray-100">
                  {items.slice(0, 3).map((m) => (
                    <li key={m.id} className="text-xs">
                      <Link
                        href={`/vod/${m.id}`}
                        className="text-text-secondary hover:text-primary truncate block"
                        title={m.title}
                      >
                        · {m.title}
                      </Link>
                    </li>
                  ))}
                  {items.length > 3 && (
                    <li className="text-xs text-text-muted">
                      외 {items.length - 3}건
                    </li>
                  )}
                </ul>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}
