'use client';

import React from 'react';

import { useRouter } from 'next/navigation';

import { KMS_EXPORT_ENABLED } from '@/config/features';
import { downloadKmsScript } from '@/lib/api';
import type { MeetingType } from '@/types';
import { LIST_STAGE_LEGEND } from '@/utils/meetingStage';

import MeetingCard from './MeetingCard';
import { Button } from './ui';

export interface VodTableProps {
  vods: MeetingType[];
  className?: string;
  /** AI 자막 생성 대상 선택 모드 (관리자) — 선택 가능 카드에 체크박스 표시 */
  selectable?: boolean;
  /** 선택된 회의 ID 집합 */
  selectedIds?: Set<string>;
  /** 체크박스 토글 콜백 */
  onToggleSelect?: (id: string) => void;
}

/** AI 자막 생성을 걸 수 있는 회의: VOD 등록됨 + 아직 AI 자막 전 + 진행 중 아님 */
export function isAiGenerationCandidate(vod: MeetingType): boolean {
  const stage = vod.subtitle_stage ?? 'none';
  return (
    !!vod.vod_url &&
    (stage === 'none' || stage === 'draft') &&
    vod.status !== 'live' &&
    vod.status !== 'processing'
  );
}

/** AI 자막이 완료된 회의: subtitle_stage가 ai/reviewing/final */
export function isAiSubtitleComplete(vod: MeetingType): boolean {
  const stage = vod.subtitle_stage ?? 'none';
  return stage === 'ai' || stage === 'reviewing' || stage === 'final';
}

/** KMS 영상회의록 편집기 콘솔 자동입력 JS 스크립트 다운로드 버튼 (AI 자막 완료 시에만) */
function KmsScriptButton({ vod }: { vod: MeetingType }) {
  const [busy, setBusy] = React.useState(false);

  const handle = async (e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      setBusy(true);
      await downloadKmsScript(vod.id);
    } catch (err) {
      alert(err instanceof Error ? err.message : 'KMS 스크립트 다운로드에 실패했습니다.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Button
      variant="secondary"
      size="sm"
      onClick={handle}
      loading={busy}
      title="KMS 영상회의록 편집기 콘솔에 붙여넣어 안건시간을 자동입력하는 JS 스크립트를 다운로드합니다. (편집기에서 해당 영상 열기 → F12 콘솔에 붙여넣기 → 저장)"
      className="whitespace-nowrap text-xs"
      data-testid={`kms-script-${vod.id}`}
    >
      {busy ? '생성 중…' : 'KMS JS'}
    </Button>
  );
}

/**
 * 회의 목록 — 1열 행 목록.
 *
 * 2026-08-22 에 표 → 카드로 바꿔 PC·모바일의 어휘를 통일했고, 2026-08-25 개선안 2f 에서
 * **2열 카드 격자 → 1열 목록**으로 한 번 더 폈다. 격자는 회의명이 두 줄로 잘리고
 * 날짜·길이가 카드마다 다른 높이에 놓여 위아래로 훑을 수가 없었다.
 *
 * 이 컴포넌트가 하는 일 중 하나가 **범례**다. 단계 이름(실시간 · AI 완료)은 목록 머리에
 * 한 번만 적고, 행에는 이름 없는 2칸 막대만 둔다 — 행마다 이름을 반복하면 10px 글자가
 * 화면을 덮는다. 이름 옆 ⓘ 에 각 단계가 무엇인지 붙여 두었다.
 */
export default function VodTable({
  vods,
  className = '',
  selectable = false,
  selectedIds,
  onToggleSelect,
}: VodTableProps) {
  const router = useRouter();

  const handleOpen = (id: string) => {
    router.push(`/vod/${id}`);
  };

  if (vods.length === 0) {
    return (
      <div className={`py-12 text-center ${className}`.trim()}>
        <p className="text-text-muted">등록된 VOD가 없습니다</p>
      </div>
    );
  }

  return (
    <div
      className={`overflow-hidden rounded-lg border border-border bg-white ${className}`.trim()}
      data-testid="meeting-card-list"
    >
      {/* 범례 겸 열 머리 — 단계 이름은 목록 전체에서 여기 한 번만 나온다 */}
      <div
        className="hidden items-center gap-3.5 border-b border-border bg-gray-50 px-4 py-2 lg:flex"
        data-testid="meeting-stage-legend"
      >
        {selectable && <span className="w-4 shrink-0" aria-hidden="true" />}
        <span className="w-28 shrink-0 text-[11px] font-bold tracking-[0.06em] text-text-dim">회의</span>
        <span className="min-w-0 flex-1" aria-hidden="true" />
        <span className="w-[132px] shrink-0 text-[11px] font-bold tracking-[0.06em] text-text-dim">
          현재 단계
        </span>
        <span className="flex w-[132px] shrink-0 gap-1.5">
          {LIST_STAGE_LEGEND.map((stage) => (
            <abbr
              key={stage.key}
              title={stage.tip}
              className="flex flex-1 cursor-help items-center justify-center gap-0.5 text-[10px] font-semibold leading-tight text-text-dim no-underline"
            >
              <span className="border-b border-dotted border-border-strong">{stage.name}</span>
              {/* ⓘ — HTML 엔티티(&#9432;)로 쓰면 디자인 드리프트 검사기가 `#9432` 를
                  색상 리터럴로 오인해 팔레트 위반으로 잡는다. 문자를 그대로 쓴다. */}
              <span aria-hidden="true" className="text-[9px] text-border-accent">
                ⓘ
              </span>
            </abbr>
          ))}
        </span>
        <span className="w-8 shrink-0" aria-hidden="true" />
      </div>

      {vods.map((vod) => {
        const candidate = isAiGenerationCandidate(vod);
        return (
          <MeetingCard
            key={vod.id}
            meeting={vod}
            onOpen={handleOpen}
            selectable={selectable}
            selected={selectedIds?.has(vod.id) ?? false}
            selectableReason={{
              ok: candidate,
              reason: vod.vod_url
                ? '이미 AI 자막이 있거나 진행 중입니다'
                : 'VOD가 등록되어야 AI 자막을 생성할 수 있습니다',
            }}
            onToggleSelect={onToggleSelect}
            footer={
              KMS_EXPORT_ENABLED && isAiSubtitleComplete(vod) ? (
                <KmsScriptButton vod={vod} />
              ) : undefined
            }
          />
        );
      })}
    </div>
  );
}
