'use client';

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import AutoClipsPanel from '@/components/clips/AutoClipsPanel';
import ClipControlRail from '@/components/clips/ClipControlRail';
import ClipExtractForm, { DEFAULT_EXTRACT_FORM } from '@/components/clips/ClipExtractForm';
import type { ClipExtractFormValue } from '@/components/clips/ClipExtractForm';
import ClipJobsPanel from '@/components/clips/ClipJobsPanel';
import ClipSegmentPicker from '@/components/clips/ClipSegmentPicker';
import ClipTimeline from '@/components/clips/ClipTimeline';
import { SourceBadge } from '@/components/clips/SpeakerPicker';
import Mp4Player from '@/components/Mp4Player';
import SubtitlePanel from '@/components/SubtitlePanel';
import { useClipJobs } from '@/hooks/useClipJobs';
import { useClipKeyboard } from '@/hooks/useClipKeyboard';
import { useMeetingSubtitles } from '@/hooks/useMeetingSubtitles';
import { createClipJobV2 } from '@/lib/api';
import type { ClipIndexType, ClipJobCreateRequestType, ClipSpeakerType, MeetingType } from '@/types';
import { formatHMS, formatLen, withEnd, withStart } from '@/utils/clipTime';
import type { ClipSelection } from '@/utils/clipTime';

/**
 * ③ 워크벤치 — 4:3 영상 + 타임라인 + 오른쪽 컨트롤 레일 + 구간 선택 + 추출 옵션 + 이 회의의 추출 기록
 *
 * 화면 규칙(담당자 요청 2026-09-03):
 *  - 영상은 4:3 로 그려 좌우 검은 띠를 없애고, 남는 오른쪽에 이동·마킹 레일을 세로로 둔다.
 *  - 단축키는 버튼 라벨에. 안내 줄은 없다.
 *  - 시작 [ · 종료 ] 마킹이 핵심 — 키보드·버튼·타임라인 핸들 셋 다로 된다.
 * 2026-09-11 담당자 요청: 레일 옆에 **자막**을 띄운다. 영상은 절반 높이(56vh → 28vh)로 줄이고
 *  [영상 | 레일 | 자막] 한 줄 + 그 아래 타임라인 전체 폭. 자막은 재생 위치를 따라가고, 줄을 누르면 그 시각으로 간다.
 */
export interface ClipEditorProps {
  meeting: MeetingType;
  index: ClipIndexType | null;
  speaker: ClipSpeakerType | null;
  /** 표시·재생 보정(초). source=live 폴백을 없앤 뒤(2026-09-08) 항상 0 — 오프셋 플럼빙 정리 대상 */
  shift: number;
  offset: number;
  /** 워크벤치가 "지금 재생 위치" 를 알 수 있게 */
  onTimeUpdate?: (t: number) => void;
  onJobCreated?: (jobId: string) => void;
}

export default function ClipEditor({ meeting, index, speaker, shift, offset, onTimeUpdate, onJobCreated }: ClipEditorProps) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const [currentTime, setCurrentTime] = useState(0);
  const [videoDuration, setVideoDuration] = useState(0);
  const [isPaused, setIsPaused] = useState(true);
  const [sel, setSel] = useState<ClipSelection>({ start: 0, end: 0 });
  const [checked, setChecked] = useState<Set<number>>(new Set());
  const [form, setForm] = useState<ClipExtractFormValue>(DEFAULT_EXTRACT_FORM);
  const [submitting, setSubmitting] = useState(false);
  const [notice, setNotice] = useState<{ kind: 'ok' | 'err'; text: string } | null>(null);

  const duration = videoDuration || meeting.duration_seconds || index?.duration || 0;
  const source = index?.source ?? 'none';

  // 자막 패널 — 재생 위치의 자막 줄을 가운데로 따라간다(끄면 사용자가 스크롤한 자리에 둔다)
  const { subtitles, isLoading: subtitlesLoading } = useMeetingSubtitles(meeting.vod_url ? meeting.id : null);
  const [followSubs, setFollowSubs] = useState(true);
  const currentSubId = useMemo(() => {
    if (!followSubs || !subtitles.length) return undefined;
    const t = currentTime;
    const hit = subtitles.find((s) => t >= s.start_time && t < s.end_time);
    if (hit) return hit.id;
    // 자막 사이 틈(말 없는 구간)에서는 직전 자막에 머문다
    let prev: (typeof subtitles)[number] | undefined;
    for (const s of subtitles) {
      if (s.start_time > t) break;
      prev = s;
    }
    return prev?.id;
  }, [followSubs, subtitles, currentTime]);
  const subsRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    // SubtitlePanel 의 scrollToSubtitleId 는 scrollIntoView 라 **페이지까지** 끌어올린다 —
    // 아래 추출 카드를 보는 중에도 자막이 바뀔 때마다 화면이 튄다. 자막 목록 상자만 움직인다.
    const root = subsRef.current;
    if (!root || !currentSubId) return;
    const esc = typeof CSS !== 'undefined' && CSS.escape ? CSS.escape(currentSubId) : currentSubId;
    const el =
      root.querySelector<HTMLElement>(`[data-subtitle-id="${esc}"]`) ??
      root.querySelector<HTMLElement>(`[data-subtitle-id^="${esc}_chunk_"]`);
    if (!el) return;
    let box: HTMLElement | null = el.parentElement;
    while (box && box !== root && !(box.scrollHeight > box.clientHeight && /(auto|scroll)/.test(getComputedStyle(box).overflowY))) {
      box = box.parentElement;
    }
    if (!box || box === root) return;
    const delta = el.getBoundingClientRect().top - box.getBoundingClientRect().top - box.clientHeight / 2 + el.offsetHeight / 2;
    if (Math.abs(delta) > 4) box.scrollTo?.({ top: box.scrollTop + delta, behavior: 'smooth' });
  }, [currentSubId, subtitles.length]);

  // 아래 기록 패널(ClipJobsPanel compact)과 같은 SWR 키 — 요청은 한 번, 캐시를 공유한다.
  // 잡을 만들면 여기서 refresh 해 기록이 즉시 갱신되고(새로고침 불필요), 진행 중이면 추출 버튼을 잠근다.
  const { jobs, refresh: refreshJobs } = useClipJobs({ meetingId: meeting.id });
  const activeJob = jobs.find((j) => j.status === 'queued' || j.status === 'running') ?? null;
  const busyLabel = activeJob ? '추출 중… (아래 기록에서 진행률 확인)' : null;

  // 의원이 바뀌면 이름 있는 발언 구간을 기본 선택, 라벨(=파일명 앞부분, 이름만)을 채운다
  useEffect(() => {
    if (!speaker) {
      setChecked(new Set());
      return;
    }
    setChecked(new Set(speaker.segments.filter((s) => s.named).map((s) => s.idx)));
    setForm((f) => ({ ...f, label: speaker.name }));
    const first = speaker.segments[0];
    if (first) {
      setSel({ start: first.start + shift, end: first.end + shift });
      const v = videoRef.current;
      if (v) v.currentTime = Math.max(0, first.start + shift);
    }
    // shift 변경은 다른 effect 가 다룬다 — 의원 변경에만 반응
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [speaker?.key]);

  useEffect(() => {
    const v = videoRef.current;
    if (!v) return undefined;
    const sync = () => setIsPaused(v.paused);
    const meta = () => setVideoDuration(Number.isFinite(v.duration) ? v.duration : 0);
    v.addEventListener('play', sync);
    v.addEventListener('pause', sync);
    v.addEventListener('loadedmetadata', meta);
    sync();
    meta();
    return () => {
      v.removeEventListener('play', sync);
      v.removeEventListener('pause', sync);
      v.removeEventListener('loadedmetadata', meta);
    };
    // videoRef.current 는 Mp4Player 마운트 뒤에 채워진다 — meeting 이 바뀔 때 다시 건다
  }, [meeting.id]);

  const handleTimeUpdate = useCallback(
    (t: number) => {
      setCurrentTime(t);
      onTimeUpdate?.(t);
    },
    [onTimeUpdate]
  );

  const markStart = useCallback(() => {
    const v = videoRef.current;
    if (!v) return;
    setSel((s) => withStart(s, v.currentTime, duration));
    setNotice({ kind: 'ok', text: `🟢 구간 시작 ${formatHMS(v.currentTime)}` });
  }, [duration]);
  const markEnd = useCallback(() => {
    const v = videoRef.current;
    if (!v) return;
    setSel((s) => {
      const next = withEnd(s, v.currentTime, duration);
      setNotice({ kind: 'ok', text: `🔴 구간 종료 ${formatHMS(v.currentTime)} (길이 ${formatLen(next.end - next.start)})` });
      return next;
    });
  }, [duration]);

  const kb = useClipKeyboard({
    videoRef,
    enabled: Boolean(meeting.vod_url),
    duration,
    onMarkStart: markStart,
    onMarkEnd: markEnd,
  });

  const playSelection = () => {
    const v = videoRef.current;
    if (!v) return;
    v.currentTime = sel.start;
    void v.play()?.catch?.(() => {});
    const stopAt = () => {
      if (v.currentTime >= sel.end) {
        v.pause();
        v.removeEventListener('timeupdate', stopAt);
      }
    };
    v.addEventListener('timeupdate', stopAt);
  };

  const preview = (start: number) => {
    const v = videoRef.current;
    if (!v) return;
    v.currentTime = Math.max(0, start);
    void v.play()?.catch?.(() => {});
  };

  const toggle = (idx: number) =>
    setChecked((prev) => {
      const next = new Set(prev);
      if (next.has(idx)) next.delete(idx);
      else next.add(idx);
      return next;
    });
  const selectAll = (namedOnly: boolean) => {
    if (!speaker) return;
    setChecked(new Set(speaker.segments.filter((s) => !namedOnly || s.named).map((s) => s.idx)));
  };

  const checkedSegs = useMemo(
    () => (speaker ? speaker.segments.filter((s) => checked.has(s.idx)) : []),
    [speaker, checked]
  );
  const checkedTotal = checkedSegs.reduce((a, s) => a + (s.end - s.start), 0);
  const marks = useMemo(
    () => (speaker ? speaker.segments.map((s) => ({ start: s.start + shift, end: s.end + shift, active: checked.has(s.idx) })) : []),
    [speaker, shift, checked]
  );

  const submit = async (body: ClipJobCreateRequestType) => {
    setSubmitting(true);
    setNotice(null);
    try {
      const r = await createClipJobV2(meeting.id, body);
      setNotice({
        kind: 'ok',
        text: r.queue_position > 0
          ? `추출 요청을 받았습니다 (대기 ${r.queue_position}번째). 아래 기록에 방금 추가된 항목에서 진행률을 볼 수 있습니다.`
          : '추출을 시작했습니다. 아래 기록 맨 위에 방금 추가된 항목이 돌고 있고, 완료되면 내려받기 버튼이 생깁니다.',
      });
      refreshJobs();
      onJobCreated?.(r.job_id);
    } catch (e) {
      setNotice({ kind: 'err', text: e instanceof Error ? e.message : '추출 요청에 실패했습니다.' });
    } finally {
      setSubmitting(false);
    }
  };

  const extractChecked = () => {
    if (!speaker || !checkedSegs.length) return;
    void submit({
      // no = 목록 순번 → 파일 이름 끝 번호(설치형과 같은 값). 고른 순서가 아니다
      segments: checkedSegs.map((s) => ({ start: s.start + shift, end: s.end + shift, no: s.idx + 1 })),
      merge: form.merge,
      pad_before: form.padBefore,
      pad_after: form.padAfter,
      label: form.label || speaker.name,
      speaker_name: speaker.name,
      source_kind: source === 'none' ? 'manual' : source,
      with_srt: form.withSrt,
      time_offset: offset,
    });
  };

  const extractSelection = () => {
    if (sel.end - sel.start < 0.3) return;
    void submit({
      segments: [{ start: sel.start, end: sel.end }],
      merge: false,
      pad_before: 0,
      pad_after: 0,
      label: form.label || speaker?.name || '수동추출',
      speaker_name: speaker?.name ?? null,
      source_kind: 'manual',
      with_srt: form.withSrt,
      time_offset: offset,
    });
  };

  return (
    <div data-testid="clip-editor" className="flex flex-col gap-3 min-w-0">
      <div className="flex items-center gap-2 flex-wrap">
        <h2 className="text-[15px] font-bold text-text truncate">③ {meeting.title}</h2>
        {index && <SourceBadge source={source} />}
      </div>

      {!meeting.vod_url ? (
        <div className="rounded-lg border border-dashed border-border p-6 text-center text-sm text-text-muted">
          이 회의는 아직 VOD 가 등록되지 않았습니다.
        </div>
      ) : (
        <div className="flex flex-col gap-2">
        {/* 영상 폭 = 4:3 × 28vh ≈ 37.5vh. 좁은 화면(lg 미만)에서는 한 줄씩 쌓인다 */}
        <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,37.5vh)_248px_minmax(0,1fr)] gap-3 items-stretch">
          <div className="min-w-0">
            <Mp4Player
              vodUrl={meeting.vod_url}
              videoRef={videoRef}
              onTimeUpdate={handleTimeUpdate}
              aspectClassName="aspect-[4/3] w-full max-h-[28vh] lg:max-h-none"
            />
          </div>
          <ClipControlRail
            currentTime={currentTime}
            duration={duration}
            isPaused={isPaused}
            selStart={sel.start}
            selEnd={sel.end}
            onSeekRel={kb.seekRel}
            onSeekTo={kb.seekTo}
            onFrameStep={kb.frameStep}
            onTogglePlay={kb.togglePlay}
            onMarkStart={markStart}
            onMarkEnd={markEnd}
            onEditStart={(t) => setSel((s) => withStart(s, t, duration))}
            onEditEnd={(t) => setSel((s) => withEnd(s, t, duration))}
            onPlaySelection={playSelection}
            onExtractSelection={extractSelection}
            extractDisabled={submitting || !!activeJob}
          />
          {/* 자막 — 행 높이는 레일이 정하고 자막은 그 안에서 스크롤한다(absolute 로 행 높이에 끼지 않게) */}
          <div ref={subsRef} data-testid="clip-subtitles" className="relative min-w-0 min-h-[320px]">
            <div className="absolute inset-0">
              <SubtitlePanel
                subtitles={subtitles}
                currentTime={currentTime}
                autoScroll={false}
                isLoading={subtitlesLoading}
                emptyMessage="이 회의에는 아직 자막이 없습니다."
                onSubtitleClick={(t) => kb.seekTo(t)}
                headerLeft={
                  <div className="flex min-w-0 items-center gap-2">
                    <h3 className="font-semibold text-text text-[14px]">자막</h3>
                    <label className="inline-flex items-center gap-1 text-[12px] text-text-muted cursor-pointer">
                      <input
                        type="checkbox"
                        data-testid="clip-subtitles-follow"
                        checked={followSubs}
                        onChange={(e) => setFollowSubs(e.target.checked)}
                      />
                      재생 위치 따라가기
                    </label>
                  </div>
                }
              />
            </div>
          </div>
        </div>
        <ClipTimeline
          duration={duration}
          currentTime={currentTime}
          selStart={sel.start}
          selEnd={sel.end}
          marks={marks}
          onSeek={kb.seekTo}
          onChangeSelection={setSel}
        />
        </div>
      )}

      {notice && (
        <div
          data-testid="clip-notice"
          role="status"
          className={`rounded-md px-3 py-2 text-[13px] ${notice.kind === 'ok' ? 'bg-green-50 text-green-800' : 'bg-red-50 text-red-800'}`}
        >
          {notice.text}
        </div>
      )}

      {/* 서버가 AI 자막 뒤 미리 잘라 둔 이 의원 영상(2026-09-10) — 있으면 받기만 하면 된다. 없는 회의는 자리를 안 차지한다 */}
      {speaker && <AutoClipsPanel meetingId={meeting.id} speakerName={speaker.name} onPreview={preview} />}

      {/* 구간 선택 → 요약 → 옵션 → 추출 버튼을 한 카드로 (2026-09-10).
          예전에는 구간 목록과 옵션 상자가 따로 떠 있어 무엇이 몇 개 잘리는지 읽히지 않았다.
          설치형 프로그램의 「③ 확인 후 추출」 카드와 같은 순서다. */}
      <section
        data-testid="clip-extract-card"
        className="rounded-lg border border-border bg-white p-3 flex flex-col gap-2"
      >
        <h3 className="text-[14px] font-bold text-text">✂ 확인 후 추출</h3>
        <ClipSegmentPicker speaker={speaker} checked={checked} onToggle={toggle} onPreview={preview} shift={shift} onSelectAll={selectAll} />
        {meeting.vod_url && (
          <ClipExtractForm
            value={form}
            onChange={setForm}
            totalSeconds={checkedTotal}
            segmentCount={checkedSegs.length}
            speakerLabel={speaker ? `${speaker.name} ${speaker.role || '의원'}` : null}
            onSubmit={extractChecked}
            submitting={submitting}
            disabled={!speaker}
            busyLabel={busyLabel}
          />
        )}
      </section>

      <ClipJobsPanel meetingId={meeting.id} compact />
    </div>
  );
}
