'use client';

/**
 * 사무처 운영자 실시간 자막 편집 콘솔
 *
 * 디자인 번들 2026-04-20 (Operator.jsx)의 UX를 Next.js/TS로 포팅.
 *
 * 3분할 레이아웃:
 * - 좌 300px: 발언 순서 큐 (현재 발언자 + 대기 3명)
 * - 중앙 flex: 실시간 자막 편집 피드 (신뢰도·편집·송출 상태)
 * - 우 340px: 송출 채널 ON/OFF + 긴급 제어 + 최근 로그
 *
 * 상단: 운영자 뱃지(붉은 그라디언트) + STT 엔진/지연/신뢰도 + 5초 되돌리기 + 송출 일시중지
 *
 * 현재는 스탭 데이터 기반. 백엔드 연동은 /api/channels/{id}/stt/* +
 * WebSocket 구독으로 후속 작업.
 */

import { useEffect, useState } from 'react';

import { OpIcon } from '@/components/operator/OperatorIcon';

// ─────────────────────────────────────────────────────────
// 스탭 데이터 (디자인 시안 그대로)
// ─────────────────────────────────────────────────────────

interface FeedItem {
  t: string;
  sp: string;
  party: string;
  conf: number;
  text: string;
  lowConf?: string;
  tail?: string;
  status: 'sent' | 'live' | 'incoming';
}

// 정당색 (party-dem/pp/speaker) — KRDS 전환 대상 아님, 유지.
const PARTY_DEM = 'var(--party-dem)';
const PARTY_PP = 'var(--party-pp)';
const PARTY_SPEAKER = 'var(--party-speaker)'; // party.speaker (의장단)

const FEED: FeedItem[] = [
  { t: '10:24:08', sp: '염종현 의장', party: PARTY_SPEAKER, conf: 98, text: '다음 순서로 경제노동위원회 김정현 위원장님의 제안 설명이 있겠습니다.', status: 'sent' },
  { t: '10:24:21', sp: '김정현 위원장', party: PARTY_DEM, conf: 97, text: '존경하는 염종현 의장님과 선배·동료 의원 여러분.', status: 'sent' },
  { t: '10:24:44', sp: '김정현 위원장', party: PARTY_DEM, conf: 86, text: '이번 추경안에는 도내 소상공인 경영안정 지원, 청년 일자리 창출, 그리고', lowConf: '반도체·바이오 신성장 산업', tail: ' 육성 예산이 포함되어 있습니다.', status: 'sent' },
  { t: '10:25:02', sp: '김정현 위원장', party: PARTY_DEM, conf: 72, text: '특히 경기침체로 어려움을 겪고 있는 소상공인을 위해 저리 융자 규모를 기존', lowConf: '2천억 원에서 3천 5백억 원', tail: '으로 확대하였습니다.', status: 'live' },
  { t: '10:25:19', sp: '김정현 위원장', party: PARTY_DEM, conf: 58, text: '아울러 청년 구직자를 위한', lowConf: '직업훈련 바우처', tail: '를', status: 'incoming' },
];

interface ChannelItem {
  k: string;
  icon: 'globe' | 'building' | 'youtube' | 'monitor';
  title: string;
  sub: string;
  viewers: string;
  color: string;
}

const CHANNELS: ChannelItem[] = [
  { k: 'site', icon: 'globe', title: '경기도의회 홈페이지', sub: 'www.ggc.go.kr · 자막 임베드', viewers: '1,284명', color: 'var(--ggc-primary)' },
  { k: 'hall', icon: 'building', title: '본회의장 디스플레이', sub: '상·하단 자막 바 (2개 LED)', viewers: '현장 82명', color: 'var(--gac-gold)' },
  { k: 'youtube', icon: 'youtube', title: 'YouTube 라이브', sub: '@GyeonggiAssembly · 4K', viewers: '3,412명', color: 'var(--krds-danger)' },
  { k: 'portal', icon: 'monitor', title: '의정포털 (내부망)', sub: 'portal.ggc.go.kr · 의원·보좌진', viewers: '68명', color: 'var(--ink-500)' },
];

const QUEUE = [
  { n: '박순애', pc: PARTY_PP, r: '대표질의', a: '10:00', c: '기획재정위' },
  { n: '이도현', pc: PARTY_DEM, r: '보충질의', a: '05:00', c: '보건복지위' },
  { n: '최영수', pc: PARTY_PP, r: '보충질의', a: '05:00', c: '교육행정위' },
];

const RECENT_LOG: Array<[string, string, string]> = [
  ['10:25:02', '자막 송출', '홈페이지·본회의장·YouTube'],
  ['10:24:44', '용어 확정', '반도체·바이오'],
  ['10:24:21', '발언자 전환', '염종현 → 김정현'],
  ['10:24:08', '세션 시작', '제388회 제4차'],
];

const STT_STATS: Array<{ icon: 'cpu' | 'signal' | 'check'; label: string; value: string; dot: string }> = [
  { icon: 'cpu', label: 'STT 엔진', value: 'Clova v3', dot: 'var(--krds-success)' },
  { icon: 'signal', label: '평균 지연', value: '1.2s', dot: 'var(--krds-success)' },
  { icon: 'check', label: '신뢰도', value: '91%', dot: 'var(--krds-success)' },
];

// ─────────────────────────────────────────────────────────

export default function OperatorPage() {
  const [useSwitches, setUseSwitches] = useState(true);
  const [channels, setChannels] = useState<Record<string, boolean>>({
    site: true,
    hall: true,
    youtube: true,
    portal: false,
  });
  const [draft, setDraft] = useState('');
  const [now, setNow] = useState('—:—:—');

  useEffect(() => {
    const update = () => {
      const d = new Date();
      setNow(
        `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}:${String(d.getSeconds()).padStart(2, '0')}`,
      );
    };
    update();
    const id = setInterval(update, 1000);
    return () => clearInterval(id);
  }, []);

  const toggle = (k: string) => setChannels((c) => ({ ...c, [k]: !c[k] }));
  const activeCount = Object.values(channels).filter(Boolean).length;

  return (
    <div className="flex flex-col h-full bg-ink-50 font-sans">
      {/* ============================================================
          Top bar — Dark + Operator badge
          ============================================================ */}
      <header className="flex items-center gap-5 px-5 py-2.5 text-white border-b-2 bg-gray-950 border-error">
        <div className="flex items-center gap-2.5 px-3.5 py-1.5 rounded bg-error ring-1 ring-white/30">
          <span className="w-[7px] h-[7px] rounded-full bg-white animate-live-pulse-fast" />
          <span className="text-xs font-extrabold tracking-[0.12em]">
            운영자 모드 · OPERATOR
          </span>
        </div>
        <div className="w-px h-[26px] bg-white/15" />
        <div className="leading-[1.2]">
          <div className="text-[10px] text-white/55 tracking-widest font-semibold">SESSION</div>
          <div className="text-sm font-bold">제388회 제4차 본회의 · 제안설명</div>
        </div>
        <div className="flex-1" />
        {STT_STATS.map((s, i) => (
          <div
            key={i}
            className="flex items-center gap-2.5 px-3 py-1.5 rounded bg-white/5 border border-white/10"
          >
            <OpIcon name={s.icon} size={14} color="rgba(255,255,255,0.55)" />
            <div className="leading-tight">
              <div className="text-[9px] text-white/50 tracking-widest font-semibold">
                {s.label}
              </div>
              <div className="text-[13px] font-bold tabular-nums">{s.value}</div>
            </div>
            <span className="w-[7px] h-[7px] rounded-full" style={{ background: s.dot }} />
          </div>
        ))}
        <div className="w-px h-[26px] bg-white/15" />
        <button className="flex items-center gap-1.5 px-3.5 py-2 rounded text-[13px] font-semibold border border-white/15 bg-white/10 hover:bg-white/15 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary">
          <OpIcon name="rewind" size={15} />5초 되돌리기
        </button>
        <button className="flex items-center gap-1.5 px-4 py-2 rounded text-[13px] font-bold bg-warning-bg text-gray-900 hover:brightness-105 transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary">
          <OpIcon name="pause" size={15} />
          송출 일시중지
        </button>
        <div className="text-xs text-white/70 ml-2">
          운영자 <strong className="text-white">김사무</strong> ·{' '}
          <span className="tabular-nums">{now}</span>
        </div>
      </header>

      {/* ============================================================
          3-column main
          ============================================================ */}
      <div className="flex-1 flex min-h-0">
        {/* ─────────── Left: Queue ─────────── */}
        <div className="w-[300px] flex-shrink-0 flex flex-col bg-white border-r border-ink-200">
          <div className="px-4 pt-3.5 pb-3 border-b border-ink-200">
            <div className="text-[10px] text-ink-500 font-bold tracking-widest">
              SPEAKER QUEUE
            </div>
            <div className="text-[15px] font-bold text-ink-900 mt-px">
              발언 순서 큐
              <span className="text-xs font-medium text-ink-500 ml-1.5">(4)</span>
            </div>
          </div>

          {/* Current speaker */}
          <div className="mx-3 mt-[18px] mb-3.5 px-3.5 pt-3.5 pb-3 rounded-md relative border-2 border-live-red bg-gradient-to-b from-white to-error/5">
            <div className="absolute -top-2.5 left-3 flex items-center gap-1.5 px-2 py-0.5 bg-live-red text-white text-[10px] font-extrabold tracking-widest rounded-sm">
              <span className="w-1.5 h-1.5 rounded-full bg-white animate-live-pulse-fast" />
              LIVE · 발언 중
            </div>
            <div className="flex items-center gap-1.5 mt-1.5 mb-1">
              <span className="w-[9px] h-[9px] rounded-full bg-party-dem" />
              <span className="text-[11px] font-bold text-party-dem">더불어민주당</span>
              <span className="text-[11px] text-ink-500">· 수원8</span>
            </div>
            <div className="text-xl font-extrabold text-ink-900">
              김정현 <span className="text-xs font-medium text-ink-600">의원</span>
            </div>
            <div className="text-xs text-ink-600 mb-2.5">경제노동위원회 위원장</div>
            <div className="flex gap-2 items-center text-[11px]">
              <span className="px-2 py-0.5 bg-primary-10 text-primary-dark rounded-sm font-bold">
                제안 설명
              </span>
              <span className="tabular-nums font-semibold text-ink-700">01:03 / 05:00</span>
            </div>
            <div className="mt-2 h-1 rounded bg-ink-200 overflow-hidden">
              <div className="h-full bg-primary" style={{ width: '21%' }} />
            </div>
          </div>

          <div className="px-3 pb-1.5 text-[10px] tracking-widest text-ink-500 font-bold">
            대기 중 · {QUEUE.length}명
          </div>
          <div className="flex-1 overflow-y-auto px-3 pb-3">
            {QUEUE.map((q, i) => (
              <div
                key={i}
                className={`flex items-center gap-2.5 py-2.5 px-2.5 rounded transition-colors mb-1.5 border ${
                  i === 0
                    ? 'bg-ink-50 border-ink-200'
                    : 'bg-transparent border-transparent hover:bg-ink-50'
                }`}
              >
                <div
                  className={`w-[26px] h-[26px] rounded-full grid place-items-center text-xs font-bold ${
                    i === 0 ? 'bg-primary text-white' : 'bg-ink-200 text-ink-700'
                  }`}
                >
                  {i + 2}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-1.5">
                    <span
                      className="w-[7px] h-[7px] rounded-full"
                      style={{ background: q.pc }}
                    />
                    <span className="text-sm font-bold text-ink-900">{q.n}</span>
                    <span className="text-[10px] text-ink-500">{q.c}</span>
                  </div>
                  <div className="text-[11px] text-ink-600 mt-px">
                    {q.r} · 배정 {q.a}
                  </div>
                </div>
                <button className="p-1 text-ink-400 hover:text-ink-600">
                  <OpIcon name="edit" size={14} />
                </button>
              </div>
            ))}
            <button className="w-full py-2.5 border border-dashed border-ink-300 rounded text-ink-600 text-xs flex items-center justify-center gap-1.5 mt-1.5 hover:bg-ink-50 transition-colors">
              <OpIcon name="plus" size={14} />
              발언자 추가
            </button>
          </div>
        </div>

        {/* ─────────── Center: Caption editor feed ─────────── */}
        <div className="flex-1 flex flex-col min-w-0 bg-ink-50">
          <div className="px-4 pt-3.5 pb-3 border-b border-ink-200 flex items-center gap-2.5 bg-white">
            <div className="flex-1">
              <div className="text-[10px] text-ink-500 font-bold tracking-widest">
                LIVE CAPTION EDITOR
              </div>
              <div className="text-[15px] font-bold text-ink-900 mt-px">실시간 자막 편집</div>
            </div>
            <div className="flex gap-2.5 text-[11px] text-ink-600">
              {[
                ['var(--krds-danger)', '신뢰도 낮음'],
                ['var(--krds-warning-bg)', '편집 필요'],
                ['var(--krds-success)', '송출 완료'],
              ].map(([color, label], i) => (
                <span key={i} className="inline-flex items-center gap-1">
                  <span className="w-2 h-0.5" style={{ background: color }} />
                  {label}
                </span>
              ))}
            </div>
          </div>

          <div className="flex-1 overflow-y-auto px-[18px] py-3.5">
            {FEED.map((row, i) => {
              const tone =
                row.status === 'live'
                  ? {
                      box: 'bg-warning-bg/10 border-warning-bg/40 ring-[3px] ring-warning-bg/10',
                      text: 'text-warning',
                      dot: 'bg-warning-bg',
                    }
                  : row.status === 'incoming'
                    ? { box: 'bg-info/10 border-info/30', text: 'text-info', dot: 'bg-info' }
                    : { box: 'bg-white border-ink-200', text: 'text-success', dot: 'bg-success' };
              const statusLabel =
                row.status === 'live' ? '편집 중' : row.status === 'incoming' ? '수신 중…' : '송출됨';
              const confClass =
                row.conf < 70 ? 'text-error' : row.conf < 90 ? 'text-warning' : 'text-success';
              return (
                <div key={i} className={`flex gap-3 p-3.5 rounded border mb-2 ${tone.box}`}>
                  <div className="w-[130px] flex-shrink-0">
                    <div className="text-[11px] font-bold text-ink-500 tabular-nums mb-1">
                      {row.t}
                    </div>
                    <div className="flex items-center gap-1.5">
                      <span
                        className="w-[7px] h-[7px] rounded-full"
                        style={{ background: row.party }}
                      />
                      <span className="text-xs font-bold text-ink-800">{row.sp}</span>
                    </div>
                    <div
                      className={`inline-flex items-center gap-1 mt-1.5 text-[10px] px-1.5 py-0.5 rounded-sm font-bold bg-gray-900/5 ${confClass}`}
                    >
                      <OpIcon name="signal" size={10} color="currentColor" />
                      {row.conf}%
                    </div>
                  </div>
                  <div className="flex-1 min-w-0">
                    <div
                      className="text-[14.5px] text-ink-900"
                      style={{ lineHeight: 1.6 }}
                    >
                      {row.text}
                      {row.lowConf && (
                        <span
                          className="px-0.5 bg-error/10"
                          style={{
                            textDecoration: 'underline wavy var(--krds-danger)',
                            textUnderlineOffset: 3,
                          }}
                        >
                          {' '}
                          {row.lowConf}
                        </span>
                      )}
                      {row.tail}
                      {row.status === 'incoming' && (
                        <span
                          className="inline-block w-0.5 ml-1 align-middle animate-blink bg-info"
                          style={{ height: '1em' }}
                        />
                      )}
                    </div>
                    <div className="flex gap-1.5 mt-2 text-[11px]">
                      <button className="inline-flex items-center gap-1 px-2 py-1 rounded-sm border border-ink-200 text-ink-700 font-medium hover:bg-ink-50">
                        <OpIcon name="edit" size={11} />
                        수정
                      </button>
                      {row.lowConf && (
                        <button className="inline-flex items-center gap-1 px-2 py-1 rounded-sm bg-primary-5 border border-primary-20 text-primary-dark font-bold hover:bg-primary-10">
                          <OpIcon name="check" size={11} />
                          용어 확정
                        </button>
                      )}
                      <button className="inline-flex items-center gap-1 px-2 py-1 rounded-sm border border-ink-200 text-ink-700 font-medium hover:bg-ink-50">
                        <OpIcon name="refresh" size={11} />
                        재분석
                      </button>
                      <button className="inline-flex items-center gap-1 px-2 py-1 rounded-sm border border-ink-200 text-ink-700 font-medium hover:bg-ink-50">
                        <OpIcon name="x" size={11} />
                        숨김
                      </button>
                      <div className="flex-1" />
                      <span
                        className={`inline-flex items-center gap-1 font-bold px-2 py-1 rounded-sm bg-gray-900/5 ${tone.text}`}
                      >
                        <span className={`w-1.5 h-1.5 rounded-full ${tone.dot}`} />
                        {statusLabel}
                      </span>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>

          {/* Manual input */}
          <div className="border-t border-ink-200 bg-white px-[18px] py-3.5">
            <div className="flex gap-2 items-center mb-2.5 text-[11px] text-ink-600">
              <span className="px-2 py-0.5 rounded-sm bg-ink-100 text-ink-800 font-bold">
                수동 자막 입력
              </span>
              <span>· 현재 발언자</span>
              <span className="inline-flex items-center gap-1 px-2 py-0.5 bg-primary-5 text-primary-dark rounded-sm font-bold">
                <span className="w-1.5 h-1.5 rounded-full bg-party-dem" />
                김정현 위원장
              </span>
              <div className="flex-1" />
              <span>
                단축키{' '}
                <kbd className="text-[10px] px-1.5 py-0.5 rounded-sm bg-ink-100 font-mono">
                  ⌘+Enter
                </kbd>{' '}
                송출
              </span>
            </div>
            <div className="flex gap-2.5">
              <textarea
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                placeholder="자막을 직접 입력하거나, 위 STT 결과를 수정하세요. 오탈자 감지 시 붉은 밑줄이 표시됩니다."
                className="flex-1 min-h-[64px] px-3 py-2.5 text-sm rounded font-sans border-[1.5px] border-ink-300 outline-none focus:border-primary focus-visible:ring-2 focus-visible:ring-primary text-ink-900"
                style={{ lineHeight: 1.55 }}
              />
              <div className="flex flex-col gap-1.5 w-[140px]">
                <button className="flex items-center justify-center gap-1.5 py-3 rounded text-[13px] font-bold text-white bg-primary hover:bg-primary-dark transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary">
                  <OpIcon name="send" size={15} />
                  송출
                </button>
                <button className="py-2 px-2.5 rounded bg-white border border-ink-300 text-xs font-semibold text-ink-700 hover:bg-ink-50">
                  초안 저장
                </button>
                <button className="py-2 px-2.5 rounded bg-white border border-ink-300 text-xs font-semibold text-ink-700 hover:bg-ink-50">
                  용어사전 확인
                </button>
              </div>
            </div>
          </div>
        </div>

        {/* ─────────── Right: Broadcast channels ─────────── */}
        <div className="w-[340px] flex-shrink-0 bg-white border-l border-ink-200 flex flex-col">
          <div className="px-4 pt-3.5 pb-3 border-b border-ink-200 flex items-center gap-2.5">
            <div className="flex-1">
              <div className="text-[10px] text-ink-500 font-bold tracking-widest">
                BROADCAST CHANNELS
              </div>
              <div className="text-[15px] font-bold text-ink-900 mt-px">송출 채널</div>
            </div>
            <div className="px-2 py-0.5 rounded-sm bg-ok-green text-white text-[11px] font-bold">
              {activeCount}/4 ON
            </div>
            <button
              onClick={() => setUseSwitches((v) => !v)}
              className="text-[10px] text-ink-500 hover:text-ink-700"
              title="토글 스위치 / ON·OFF 버튼 전환"
            >
              ⇌
            </button>
          </div>

          <div className="px-3.5 py-3 flex-1 overflow-y-auto">
            {CHANNELS.map((c) => {
              const on = channels[c.k];
              return (
                <div
                  key={c.k}
                  className={`p-3 border border-ink-200 rounded-[5px] mb-2 flex gap-3 items-center ${
                    on ? 'bg-white' : 'bg-ink-50 opacity-70'
                  }`}
                >
                  <div
                    className="w-[34px] h-[34px] rounded grid place-items-center flex-shrink-0"
                    style={{ background: on ? c.color : 'var(--ink-200)' }}
                  >
                    <OpIcon name={c.icon} size={18} color="#fff" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="text-[13px] font-bold text-ink-900">{c.title}</div>
                    <div className="text-[11px] text-ink-600 mt-px">{c.sub}</div>
                    <div className="flex gap-2.5 mt-1.5 text-[10px]">
                      <span className="text-ink-700">👁 {c.viewers}</span>
                      <span
                        className={`inline-flex items-center gap-1 font-bold ${
                          on ? 'text-ok-green' : 'text-ink-500'
                        }`}
                      >
                        <span
                          className={`w-[5px] h-[5px] rounded-full ${
                            on ? 'bg-ok-green' : 'bg-ink-400'
                          }`}
                        />
                        {on ? '정상' : '송출 중단'}
                      </span>
                    </div>
                  </div>
                  {useSwitches ? (
                    <button
                      onClick={() => toggle(c.k)}
                      className={`relative w-[52px] h-7 rounded-[14px] flex-shrink-0 transition-colors ${
                        on ? 'bg-ok-green ring-[3px] ring-success/15' : 'bg-ink-300'
                      }`}
                    >
                      <span
                        className="absolute top-[3px] w-[22px] h-[22px] rounded-full bg-white grid place-items-center transition-all"
                        style={{
                          left: on ? 27 : 3,
                          boxShadow: '0 1px 3px rgba(0,0,0,0.3)',
                        }}
                      >
                        {on && <OpIcon name="check" size={10} color="var(--krds-success)" stroke={3} />}
                      </span>
                      <span
                        className="absolute top-[7px] text-[9px] font-extrabold text-white"
                        style={{ right: on ? 32 : undefined, left: on ? undefined : 8 }}
                      >
                        {on ? 'ON' : 'OFF'}
                      </span>
                    </button>
                  ) : (
                    <button
                      onClick={() => toggle(c.k)}
                      className={`px-3 py-1.5 rounded-sm text-[11px] font-extrabold tracking-wider ${
                        on ? 'bg-ok-green text-white' : 'bg-ink-200 text-ink-700'
                      }`}
                    >
                      {on ? 'ON' : 'OFF'}
                    </button>
                  )}
                </div>
              );
            })}

            <div className="mt-3.5 p-3.5 border rounded bg-error/5 border-error/30">
              <div className="flex items-center gap-1.5 text-xs font-bold text-live-red mb-1.5">
                <OpIcon name="warn" size={14} />
                긴급 제어
              </div>
              <div className="text-[11px] text-ink-700 leading-[1.5] mb-2.5">
                비공개 발언이나 오탐지 시 아래 버튼으로 전 채널 송출을 즉시 중단합니다.
              </div>
              <button className="w-full py-2.5 bg-live-red text-white text-[13px] font-extrabold rounded flex items-center justify-center gap-1.5 hover:brightness-110 transition-all">
                <OpIcon name="pause" size={14} />
                전체 송출 일시중지
              </button>
            </div>

            <div className="mt-3.5">
              <div className="text-[10px] tracking-widest text-ink-500 font-bold mb-1.5">
                최근 송출 로그
              </div>
              {RECENT_LOG.map(([t, title, detail], i) => (
                <div
                  key={i}
                  className={`flex gap-2 py-1.5 text-[11px] text-ink-700 ${
                    i < RECENT_LOG.length - 1 ? 'border-b border-ink-100' : ''
                  }`}
                >
                  <span className="text-ink-500 font-semibold tabular-nums">{t}</span>
                  <span className="font-bold text-ink-800">{title}</span>
                  <span className="text-ink-600 flex-1 text-right">{detail}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
