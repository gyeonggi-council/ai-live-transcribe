'use client';

import React, { useCallback, useEffect, useMemo, useState } from 'react';

import ClipEditor from '@/components/clips/ClipEditor';
import ClipMeetingList, { committeeOf } from '@/components/clips/ClipMeetingList';
import SpeakerPicker from '@/components/clips/SpeakerPicker';
import { useAutoClips } from '@/hooks/useAutoClips';
import { useClipIndex } from '@/hooks/useClipIndex';
import { apiClient } from '@/lib/api';
import type { ClipSpeakerType, MeetingType } from '@/types';

/**
 * 클립 워크벤치 접근 역할 — 백엔드 clips.CLIP_ROLES + 의회망 손님(council_guest, 2026-09-11).
 * 손님은 서버가 요청마다 IP 로 다시 판정한다(require_role_or_council).
 */
export const CLIP_ROLES = ['staff', 'committee_staff', 'meeting_manager', 'stenographer', 'admin', 'council_guest'];

export interface ClipWorkbenchProps {
  meetingId: string | null;
  /** 회의 화면(/vod/[id]/clips)처럼 회의가 정해져 있으면 목록을 접고 시작 */
  listCollapsed?: boolean;
  onSelectMeeting?: (meetingId: string) => void;
}

/**
 * 3열 워크벤치: ① 회의 목록 → ② 의원/화자 → ③ 영상·마킹·추출
 * (데스크톱 추출기 v1.9 의 한 화면 3단 구성을 그대로 잇는다)
 */
export default function ClipWorkbench({ meetingId, listCollapsed = false, onSelectMeeting }: ClipWorkbenchProps) {
  const [collapsed, setCollapsed] = useState(listCollapsed);
  const [meeting, setMeeting] = useState<MeetingType | null>(null);
  const [meetingError, setMeetingError] = useState<string | null>(null);
  const [speaker, setSpeaker] = useState<ClipSpeakerType | null>(null);

  // offset/shift 는 source=live 폴백을 없앤 뒤(2026-09-08) 항상 0 — 플럼빙 정리 대상
  const { index, isLoading, error, offset, shift } = useClipIndex(meetingId);
  // 서버가 미리 잘라 둔 의원 영상(2026-09-10) — 의원 카드에 「영상 준비됨」. 편집기의 목록과 같은 SWR 키다
  const { jobs: autoJobs } = useAutoClips({ meetingId, enabled: Boolean(meetingId) });
  const readyNames = useMemo(
    () => new Set(autoJobs.filter((j) => j.status === 'done').map((j) => j.speaker_name || j.label || '')),
    [autoJobs]
  );

  useEffect(() => {
    setSpeaker(null);
    setMeeting(null);
    setMeetingError(null);
    if (!meetingId) return undefined;
    let cancelled = false;
    apiClient<MeetingType>(`/api/meetings/${meetingId}`)
      .then((m) => {
        if (!cancelled) setMeeting(m);
      })
      .catch((e: unknown) => {
        if (!cancelled) setMeetingError(e instanceof Error ? e.message : '회의 정보를 불러오지 못했습니다.');
      });
    return () => {
      cancelled = true;
    };
  }, [meetingId]);

  // 인덱스가 다시 오면(오프셋·새로고침) 선택 의원을 같은 key 로 갱신
  useEffect(() => {
    if (!index) return;
    setSpeaker((prev) => (prev ? index.speakers.find((s) => s.key === prev.key) ?? null : null));
  }, [index]);

  const handleSelectMeeting = useCallback(
    (m: MeetingType) => {
      if (onSelectMeeting) onSelectMeeting(m.id);
      else setMeeting(m);
    },
    [onSelectMeeting]
  );

  return (
    <div data-testid="clip-workbench" className="flex gap-3 p-3 h-full min-h-0 items-stretch">
      <aside
        className={`flex-none ${collapsed ? 'w-auto' : 'w-[300px] min-w-[240px]'} rounded-lg border border-border bg-white p-2 min-h-0`}
      >
        <ClipMeetingList
          selectedId={meetingId}
          onSelect={handleSelectMeeting}
          collapsed={collapsed}
          onToggleCollapsed={() => setCollapsed((c) => !c)}
        />
      </aside>

      <aside className="flex-none w-[300px] min-w-[240px] rounded-lg border border-border bg-white p-2 min-h-0">
        {meetingId ? (
          <SpeakerPicker
            index={index}
            isLoading={isLoading}
            error={error}
            selectedKey={speaker?.key ?? null}
            onSelect={setSpeaker}
            shift={shift}
            readyNames={readyNames}
            meetingCommittee={meeting ? committeeOf(meeting) : null}
          />
        ) : (
          <div className="text-sm text-text-muted p-3 leading-relaxed">
            왼쪽에서 회의를 고르면 발언한 의원이 여기에 나타납니다.
          </div>
        )}
      </aside>

      <section className="flex-1 min-w-0 rounded-lg border border-border bg-white p-3 overflow-y-auto">
        {!meetingId && (
          <div className="h-full flex items-center justify-center text-center text-sm text-text-muted leading-relaxed">
            <div>
              <div className="text-4xl mb-2">🎬</div>
              왼쪽 회의 목록을 클릭하면 <b>다운로드 없이 바로</b> 재생됩니다.
              <br />
              의원을 고르고 구간을 확인한 뒤 추출하세요. 인덱스가 없어도 시작·종료를 직접 지정해 자를 수 있습니다.
            </div>
          </div>
        )}
        {meetingId && meetingError && <div className="text-sm text-red-700">{meetingError}</div>}
        {meetingId && !meeting && !meetingError && <div className="text-sm text-text-muted">회의 정보를 불러오는 중…</div>}
        {meeting && (
          <ClipEditor
            meeting={meeting}
            index={index}
            speaker={speaker}
            shift={shift}
            offset={offset}
          />
        )}
      </section>
    </div>
  );
}
