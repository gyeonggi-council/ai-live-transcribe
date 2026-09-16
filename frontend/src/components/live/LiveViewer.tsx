'use client';

/**
 * LiveViewer — 경기도의회 시민용 실시간 자막 뷰어
 *
 * 디자인 번들 2026-04-20 (Viewer.jsx)의 UX를 Next.js/TypeScript로 포팅한 컴포넌트.
 *
 * 레이아웃:
 * - KRDS Primary 다크 헤더 + LIVE 뱃지 + 시각 표시
 * - 브레드크럼 + 접근성 뱃지
 * - 좌 60%: 16:9 영상(HlsPlayer 슬롯) + 다크 자막존(글자크기/번역 토글)
 * - 우 40%: 현재 발언자 카드 / 의안 카드 / 대기큐
 * - 풋터: 검색 + 북마크/하이라이트/회의록/내보내기
 *
 * 실시간 자막은 부모에서 WebSocket으로 수신된 subtitles를 props로 전달.
 * 영상 영역은 children 슬롯으로 받아 HlsPlayer 등을 그대로 재사용.
 */

import { useEffect, useMemo, useState } from 'react';

import { LiveIcon } from './LiveViewerIcon';

import type { SubtitleType } from '../../types';

// ---------------------------------------------------------------------------
// 타입
// ---------------------------------------------------------------------------

type FontSize = 's' | 'm' | 'l' | 'xl';
type Language = 'ko' | 'en' | 'zh';

interface NextUpItem {
  name: string;
  party: string;
  partyColor: string;
  role: string;
  eta: string;
  committee?: string;
}

interface AgendaInfo {
  number?: string;
  title: string;
  attachments?: string[];
  phase?: 'proposal' | 'qa' | 'vote';
}

export interface LiveViewerProps {
  /** 영상 플레이어 슬롯 (HlsPlayer 등) */
  videoSlot: React.ReactNode;
  /** 회의 제목 (상단 헤더) */
  meetingTitle: string;
  /** 채널/세션 부제 (예: "제11대") */
  sessionLabel?: string;
  /** 수신된 자막 목록 (시간순) */
  subtitles: SubtitleType[];
  /** 인터림(부분) 자막 텍스트 */
  interimText?: string;
  /** LIVE 여부 */
  isLive: boolean;
  /** 지연 초 */
  latencySeconds?: number;
  /** 상단 검색 동작 */
  onSearch?: (query: string) => void;
  /** 풋터 버튼 콜백 */
  onBookmark?: () => void;
  onHighlight?: () => void;
  onViewTranscript?: () => void;
  onExport?: () => void;
  /** 대기 발언자 (선택) — 없으면 빈 슬롯 */
  nextUp?: NextUpItem[];
  /** 의안 정보 (선택) */
  agenda?: AgendaInfo;
  /** 현재 발언자 (선택) — 자막에서 파생되지만 명시 가능 */
  currentSpeaker?: {
    name: string;
    title?: string;
    party?: string;
    partyColor?: string;
    district?: string;
  };
  /** 브레드크럼 좌측 파트 (기본: 인터넷방송) */
  breadcrumb?: string;
  /** 헤더/풋터 숨김 (임베드 용) */
  embedded?: boolean;
}

// ---------------------------------------------------------------------------
// 상수
// ---------------------------------------------------------------------------

const FONT_SIZE_MAP: Record<FontSize, number> = { s: 18, m: 22, l: 28, xl: 34 };
const FONT_SIZE_BUTTONS: Array<[FontSize, string, number]> = [
  ['s', '작게', 13],
  ['m', '보통', 14],
  ['l', '크게', 15],
  ['xl', '아주 크게', 16],
];
const LANGUAGE_BUTTONS: Array<[Language, string]> = [
  ['ko', '한국어'],
  ['en', 'English'],
  ['zh', '中文'],
];

// ---------------------------------------------------------------------------
// 유틸
// ---------------------------------------------------------------------------

function formatClock(d: Date): string {
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}:${String(d.getSeconds()).padStart(2, '0')}`;
}

function formatKoreanDate(d: Date): string {
  const days = ['일', '월', '화', '수', '목', '금', '토'];
  return `${d.getFullYear()}.${String(d.getMonth() + 1).padStart(2, '0')}.${String(d.getDate()).padStart(2, '0')} (${days[d.getDay()]})`;
}

function formatTime(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

// ---------------------------------------------------------------------------
// 컴포넌트
// ---------------------------------------------------------------------------

export default function LiveViewer({
  videoSlot,
  meetingTitle,
  sessionLabel,
  subtitles,
  interimText,
  isLive,
  latencySeconds,
  onSearch,
  onBookmark,
  onHighlight,
  onViewTranscript,
  onExport,
  nextUp = [],
  agenda,
  currentSpeaker,
  breadcrumb = '인터넷방송',
  embedded = false,
}: LiveViewerProps) {
  const [fontSize, setFontSize] = useState<FontSize>('m');
  const [lang, setLang] = useState<Language>('ko');
  const [now, setNow] = useState<string>('—:—:—');
  const [today, setToday] = useState<string>('');
  const [searchQuery, setSearchQuery] = useState('');

  // 실시간 시각 갱신
  useEffect(() => {
    const update = () => {
      const d = new Date();
      setNow(formatClock(d));
      setToday(formatKoreanDate(d));
    };
    update();
    const id = setInterval(update, 1000);
    return () => clearInterval(id);
  }, []);

  // 최근 자막 3개 + interim
  const recentSubtitles = useMemo(() => subtitles.slice(-3), [subtitles]);
  const liveSubtitle = recentSubtitles[recentSubtitles.length - 1];

  const subFs = FONT_SIZE_MAP[fontSize];
  const nameFs = Math.max(14, subFs - 4);
  const timeFs = Math.max(12, subFs - 8);
  const lineHeight = fontSize === 'xl' ? 1.7 : 1.55;

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onSearch?.(searchQuery);
  };

  return (
    <div className="flex flex-col h-full bg-white font-sans" data-testid="live-viewer">
      {/* ============================================================
          Top bar — GAC Dark Blue 헤더
          ============================================================ */}
      {!embedded && (
        <header className="flex items-center justify-between px-7 py-3.5 bg-primary-70 text-white border-b-[3px] border-gac-gold">
          <div className="flex items-center gap-4">
            <div className="grid place-items-center w-9 h-9 rounded-full bg-white/10 border-[1.5px] border-white/40 font-serif text-[13px] font-bold">
              의회
            </div>
            <div>
              <div className="text-[11px] opacity-75 tracking-[0.1em] font-medium">
                GYEONGGIDO ASSEMBLY · LIVE CAPTION
              </div>
              <div className="text-[17px] font-bold mt-0.5">
                {meetingTitle}
                {sessionLabel && (
                  <span className="opacity-70 font-normal ml-1.5">· {sessionLabel}</span>
                )}
              </div>
            </div>
          </div>
          <div className="flex items-center gap-5">
            {isLive && (
              <div className="flex items-center gap-2 px-3 py-1.5 rounded bg-live ring-2 ring-live/30">
                <span className="w-2 h-2 rounded-full bg-white animate-live-pulse" />
                <span className="text-[13px] font-bold tracking-[0.15em]">LIVE</span>
              </div>
            )}
            <div className="w-px h-6 bg-white/20" />
            <div className="flex items-center gap-2 tabular-nums">
              <LiveIcon name="clock" size={16} color="rgba(255,255,255,0.7)" />
              <span className="text-sm opacity-85">{today}</span>
              <span className="text-lg font-semibold ml-2">{now}</span>
            </div>
          </div>
        </header>
      )}

      {/* ============================================================
          Breadcrumb
          ============================================================ */}
      {!embedded && (
        <div className="flex items-center gap-2 px-7 py-2.5 bg-white border-b border-ink-200 text-xs text-ink-500">
          <span>🏠</span>
          <LiveIcon name="chevron-right" size={12} />
          <span>{breadcrumb}</span>
          <LiveIcon name="chevron-right" size={12} />
          <span className="text-primary font-semibold">실시간 자막 뷰어</span>
          <div className="flex-1" />
          <span className="px-2 py-0.5 rounded-sm bg-primary-10 text-primary text-[11px] font-semibold">
            ♿ 청각장애인·고령자 친화 모드
          </span>
        </div>
      )}

      {/* ============================================================
          Main — 60/40 split
          ============================================================ */}
      <div className="flex-1 flex flex-col lg:flex-row gap-4 p-4 bg-ink-50 min-h-0 overflow-auto lg:overflow-hidden">
        {/* Left: Video + Subtitle zone */}
        <div className="w-full lg:w-[60%] flex flex-col min-h-0">
          {/* Video slot */}
          <div className="relative aspect-video bg-gray-950 rounded-t-[6px] overflow-hidden group">
            {videoSlot}
          </div>

          {/* Subtitle zone (dark) */}
          <div className="flex flex-col gap-3.5 px-7 pt-5 pb-6 rounded-b-[6px] text-white min-h-[280px] bg-gray-950">
            {/* Controls */}
            <div className="flex flex-wrap gap-4 items-center pb-3 border-b border-white/10">
              {/* Font size */}
              <div className="flex items-center gap-2">
                <LiveIcon name="type" size={15} color="rgba(255,255,255,0.6)" />
                <span className="text-xs text-white/60 mr-1">글자 크기</span>
                <div className="flex bg-white/10 rounded p-0.5">
                  {FONT_SIZE_BUTTONS.map(([key, label, fz]) => (
                    <button
                      key={key}
                      onClick={() => setFontSize(key)}
                      style={{ fontSize: fz }}
                      className={`px-3 py-1 rounded-sm transition-colors ${
                        fontSize === key
                          ? 'bg-white text-ink-900 font-bold'
                          : 'bg-transparent text-white/70 font-medium hover:text-white'
                      }`}
                    >
                      {label}
                    </button>
                  ))}
                </div>
              </div>
              {/* Translation */}
              <div className="flex items-center gap-2">
                <LiveIcon name="globe" size={15} color="rgba(255,255,255,0.6)" />
                <span className="text-xs text-white/60 mr-1">번역</span>
                <div className="flex bg-white/10 rounded p-0.5">
                  {LANGUAGE_BUTTONS.map(([key, label]) => (
                    <button
                      key={key}
                      onClick={() => setLang(key)}
                      className={`px-3 py-1 rounded-sm text-[13px] transition-colors ${
                        lang === key
                          ? 'bg-white text-ink-900 font-bold'
                          : 'bg-transparent text-white/70 font-medium hover:text-white'
                      }`}
                    >
                      {label}
                    </button>
                  ))}
                </div>
              </div>
              <div className="flex-1" />
              <div className="flex items-center gap-1.5 text-xs text-white/55">
                <span className="w-1.5 h-1.5 rounded-full bg-success" />
                자막 동기화
                {latencySeconds != null && <span>· 지연 {latencySeconds.toFixed(1)}초</span>}
              </div>
            </div>

            {/* Transcript */}
            <div
              className="flex flex-col gap-3.5 max-h-[200px] overflow-y-auto pr-2"
              style={{ fontSize: subFs, lineHeight }}
            >
              {recentSubtitles.length === 0 && !interimText && (
                <div className="text-white/50 text-sm">자막을 기다리는 중입니다...</div>
              )}
              {recentSubtitles.map((entry) => {
                const isLatest = entry.id === liveSubtitle?.id;
                return (
                  <div
                    key={entry.id}
                    className="flex gap-3.5 items-baseline"
                    style={{ opacity: isLatest ? 1 : 0.6 }}
                  >
                    <span
                      className="text-white/45 tabular-nums flex-shrink-0 pt-0.5"
                      style={{ fontSize: timeFs, minWidth: 64 }}
                    >
                      {formatTime(entry.start_time)}
                    </span>
                    <div className="flex-1 min-w-0">
                      {entry.speaker && (
                        <span
                          style={{ fontSize: nameFs }}
                          className={`font-bold mr-2.5 ${isLatest ? 'text-highlight' : 'text-highlight/60'}`}
                        >
                          [{entry.speaker}]
                        </span>
                      )}
                      <span
                        className={
                          isLatest
                            ? 'bg-highlight/20 px-1.5 py-0.5 border-l-[3px] border-highlight pl-3 -ml-[15px] rounded-sm'
                            : ''
                        }
                      >
                        {entry.text}
                      </span>
                    </div>
                  </div>
                );
              })}
              {/* Interim (typing effect) */}
              {interimText && (
                <div className="flex gap-3.5 items-baseline" style={{ fontSize: subFs }}>
                  <span
                    className="text-white/45 tabular-nums flex-shrink-0 pt-0.5"
                    style={{ fontSize: timeFs, minWidth: 64 }}
                  >
                    {now}
                  </span>
                  <div className="flex-1">
                    <span className="text-white/85 border-b-2 border-dotted border-white/40">
                      {interimText}
                    </span>
                    <span
                      className="inline-block w-0.5 bg-highlight ml-1 align-middle animate-blink"
                      style={{ height: '1em' }}
                    />
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Right: Sidebar — Current speaker / Agenda / Queue */}
        <aside className="w-full lg:w-[40%] lg:min-w-[360px] flex flex-col gap-4 min-h-0">
          {/* Current speaker card */}
          <div className="bg-white border border-ink-200 border-t-[4px] border-t-primary rounded-[2px_2px_6px_6px] px-5 py-4">
            <div className="flex items-center justify-between text-[11px] text-ink-500 tracking-[0.1em] font-semibold mb-3.5">
              <span>CURRENT SPEAKER · 현재 발언자</span>
              {isLive && currentSpeaker && (
                <span className="inline-flex items-center gap-1 text-live font-bold">
                  <LiveIcon name="mic" size={12} stroke={2} color="currentColor" />
                  발언 중
                </span>
              )}
            </div>
            {currentSpeaker ? (
              <>
                <div className="flex gap-3.5 items-center">
                  <div className="relative w-14 h-14 flex-shrink-0 rounded bg-gradient-to-br from-primary-5 to-ink-100 border border-ink-200 overflow-hidden">
                    <svg viewBox="0 0 56 56" width="100%" height="100%">
                      <circle cx="28" cy="22" r="10" className="fill-gray-300" />
                      <path d="M8 56 C 8 40 18 34 28 34 C 38 34 48 40 48 56 Z" className="fill-gray-300" />
                    </svg>
                    {currentSpeaker.partyColor && (
                      <div
                        className="absolute -bottom-px -right-px w-[19px] h-[19px] grid place-items-center text-[9px] font-bold text-white border-2 border-white rounded"
                        style={{ background: currentSpeaker.partyColor }}
                      >
                        {currentSpeaker.name.charAt(0)}
                      </div>
                    )}
                  </div>
                  <div className="flex-1">
                    {currentSpeaker.party && (
                      <div className="flex items-center gap-2 mb-0.5">
                        <span
                          className="w-2.5 h-2.5 rounded-full"
                          style={{
                            background: currentSpeaker.partyColor,
                            boxShadow: '0 0 0 2px rgba(0,0,0,0.05)',
                          }}
                        />
                        <span
                          className="text-[11px] font-bold"
                          style={{ color: currentSpeaker.partyColor }}
                        >
                          {currentSpeaker.party}
                        </span>
                        {currentSpeaker.district && (
                          <span className="text-[11px] text-ink-500">
                            · {currentSpeaker.district}
                          </span>
                        )}
                      </div>
                    )}
                    <div className="text-[20px] font-extrabold text-ink-900 -tracking-[0.5px]">
                      {currentSpeaker.name}
                      <span className="text-xs font-medium text-ink-600 ml-1"> 의원</span>
                    </div>
                    {currentSpeaker.title && (
                      <div className="text-[13px] text-ink-600 mt-1">{currentSpeaker.title}</div>
                    )}
                  </div>
                </div>
                <div className="mt-3.5 pt-3.5 border-t border-dashed border-ink-200 grid grid-cols-2 gap-2.5 text-xs">
                  <div>
                    <div className="text-ink-500 mb-0.5">발언 시작</div>
                    <div className="font-semibold text-ink-800 tabular-nums">
                      {liveSubtitle ? formatTime(liveSubtitle.start_time) : '—'}
                    </div>
                  </div>
                  <div>
                    <div className="text-ink-500 mb-0.5">자막 수</div>
                    <div className="font-semibold text-ink-800 tabular-nums">
                      {subtitles.length}건
                    </div>
                  </div>
                </div>
              </>
            ) : (
              <div className="text-ink-400 text-sm py-4 text-center">
                발언자 정보를 기다리는 중입니다.
              </div>
            )}
          </div>

          {/* Agenda card */}
          {agenda && (
            <div className="bg-white border border-ink-200 rounded-md px-5 py-4">
              <div className="text-[11px] text-ink-500 tracking-[0.1em] font-semibold mb-3">
                AGENDA · 의안 정보
              </div>
              {agenda.number && (
                <div className="inline-block px-2.5 py-0.5 rounded-sm bg-primary-10 text-primary text-[11px] font-bold mb-2.5">
                  {agenda.number}
                </div>
              )}
              <div className="text-[17px] font-bold text-ink-900 leading-[1.4] mb-3">
                {agenda.title}
              </div>
              {agenda.attachments && agenda.attachments.length > 0 && (
                <div className="flex gap-2 flex-wrap text-xs">
                  {agenda.attachments.map((label, i) => (
                    <div key={i} className="px-2.5 py-1 bg-ink-50 rounded-sm text-ink-700">
                      📎 {label}
                    </div>
                  ))}
                </div>
              )}
              {agenda.phase && (
                <div className="mt-3.5 pt-3.5 border-t border-ink-100 text-[13px] text-ink-700">
                  <span className="text-ink-500">진행 </span>
                  <span className={agenda.phase === 'proposal' ? 'font-semibold' : 'text-ink-400'}>
                    제안 설명
                  </span>
                  <span className="text-ink-400 mx-2">›</span>
                  <span className={agenda.phase === 'qa' ? 'font-semibold' : 'text-ink-400'}>
                    질의·답변
                  </span>
                  <span className="text-ink-400 mx-2">›</span>
                  <span className={agenda.phase === 'vote' ? 'font-semibold' : 'text-ink-400'}>
                    표결
                  </span>
                </div>
              )}
            </div>
          )}

          {/* Next up queue */}
          {nextUp.length > 0 && (
            <div className="bg-white border border-ink-200 rounded-md px-5 py-4 flex-1 min-h-0 flex flex-col">
              <div className="flex justify-between text-[11px] text-ink-500 tracking-[0.1em] font-semibold mb-3">
                <span>NEXT UP · 발언 대기</span>
                <span className="text-ink-400">{nextUp.length}명</span>
              </div>
              {nextUp.map((q, i) => (
                <div
                  key={i}
                  className={`flex items-center gap-3 py-3 ${
                    i < nextUp.length - 1 ? 'border-b border-ink-100' : ''
                  }`}
                >
                  <div className="w-6 h-6 rounded-full bg-ink-100 grid place-items-center text-xs font-bold text-ink-600">
                    {i + 2}
                  </div>
                  <div className="flex-1">
                    <div className="flex items-center gap-1.5">
                      <span
                        className="w-2 h-2 rounded-full"
                        style={{ background: q.partyColor }}
                      />
                      <span className="text-[15px] font-bold text-ink-900">{q.name}</span>
                      <span className="text-[11px] text-ink-500">{q.party}</span>
                    </div>
                    <div className="text-xs text-ink-600 mt-px">{q.role}</div>
                  </div>
                  <div className="text-[11px] text-ink-500">{q.eta}</div>
                </div>
              ))}
            </div>
          )}
        </aside>
      </div>

      {/* ============================================================
          Footer — Search + actions
          ============================================================ */}
      {!embedded && (
        <footer className="flex items-center gap-2 px-5 py-3 border-t border-ink-200 bg-ink-50">
          <form
            onSubmit={handleSearchSubmit}
            className="flex items-center gap-2 flex-1 px-3.5 py-2 rounded bg-white border border-ink-200"
          >
            <LiveIcon name="search" size={16} color="var(--ink-500)" />
            <input
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="발언 내용 검색 · 예) 소상공인 융자"
              className="flex-1 border-none outline-none text-sm text-ink-800 bg-transparent placeholder:text-ink-500"
            />
            <kbd className="text-[10px] text-ink-500 px-1.5 py-0.5 bg-ink-100 rounded-sm font-mono">
              ⌘K
            </kbd>
          </form>
          {[
            { icon: 'bookmark' as const, label: '북마크', onClick: onBookmark },
            { icon: 'star' as const, label: '하이라이트', onClick: onHighlight },
            { icon: 'file' as const, label: '회의록', onClick: onViewTranscript },
            { icon: 'download' as const, label: '내보내기', onClick: onExport },
          ].map(({ icon, label, onClick }) => (
            <button
              key={icon}
              onClick={onClick}
              disabled={!onClick}
              className="flex items-center gap-1.5 px-3.5 py-2 rounded bg-white border border-ink-200 text-[13px] font-medium text-ink-700 hover:bg-ink-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              <LiveIcon name={icon} size={15} />
              {label}
            </button>
          ))}
        </footer>
      )}
    </div>
  );
}
