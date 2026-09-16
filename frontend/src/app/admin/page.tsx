"use client";

import { useCallback, useEffect, useMemo, useState } from 'react';

import Link from 'next/link';

import { Button, Callout, Input } from '@/components/ui';
import {
  API_BASE_URL,
  getApiStatus,
  getStatsMeetings,
  getStatsOverview,
  getStatsReport,
  getStatsSpeakers,
} from '@/lib/api';
import type {
  ApiStatusItem,
  ChannelType,
  StatsMeetingByMonth,
  StatsOverviewType,
  StatsSpeakerItem,
} from '@/types';

type HealthStatus = {
  status: 'healthy' | 'unhealthy' | 'unknown';
  label: string;
};

type ImprovementStatus = 'done' | 'in-progress' | 'planned';

type ImprovementItem = {
  domain: string;
  feature: string;
  status: ImprovementStatus;
  phase: string;
  note: string;
};

type EnvironmentPair = {
  scope: 'frontend' | 'backend';
  key: string;
  value?: string;
  note: string;
  required: string;
};

type HowToRunStep = {
  title: string;
  command: string;
  description: string;
};

const improvementLog: ImprovementItem[] = [
  {
    domain: '실시간',
    feature: '18개 채널 HLS + WebSocket 자막',
    status: 'done',
    phase: 'Phase 2',
    note: '방송 상태 표시, 실시간 자막 스트림, 자막 패널 연동',
  },
  {
    domain: 'VOD',
    feature: 'VOD 등록/재생/시점 동기화',
    status: 'done',
    phase: 'Phase 3~5',
    note: 'KMS URL 자동 변환, MP4 재생, 재생속도 조절까지 지원',
  },
  {
    domain: '교정',
    feature: '용어 사전·문법 검사 및 일괄 교정',
    status: 'done',
    phase: 'Phase 6B',
    note: '용어 일괄 교체와 문법 수정 이력 반영',
  },
  {
    domain: '검증',
    feature: '대조관리 큐/상태 관리',
    status: 'done',
    phase: 'Phase 7',
    note: '신뢰도 기반 대조 대기열, 검토 통계, 일괄 처리 API',
  },
  {
    domain: '요약',
    feature: 'AI 회의 요약',
    status: 'done',
    phase: 'Phase 7',
    note: '회의 요약 생성, 조회, 삭제 및 화면 표시',
  },
  {
    domain: '안정성',
    feature: 'Railway 대응 운영 개선',
    status: 'done',
    phase: 'Phase 8',
    note: 'self-ping, AutoStt 전체 정리, 배치 교정 생명주기',
  },
  {
    domain: '플랫폼',
    feature: '통합 셸 UI',
    status: 'done',
    phase: 'Phase 9',
    note: '사이드바/헤더/브레드크럼/워크플로우 내비게이션',
  },
  {
    domain: '화자',
    feature: '발언 클립 다운로드',
    status: 'done',
    phase: 'Phase 11',
    note: '화자별 발언 구간을 MP4로 다운로드',
  },
  {
    domain: '통계',
    feature: '통계 대시보드 및 리포트',
    status: 'done',
    phase: 'Phase 11',
    note: '회의/화자 통계 시각화, Markdown 리포트 내보내기',
  },
  {
    domain: '운영',
    feature: '알림/모니터링 대시보드 고도화',
    status: 'in-progress',
    phase: 'Phase 11',
    note: 'STT 완료, 검증 필요 등 시스템 알림',
  },
];

const technologySummary = [
  {
    title: 'Frontend',
    items: ['Next.js 14 (App Router)', 'TypeScript strict', 'TailwindCSS', 'SWR', 'HLS.js'],
  },
  {
    title: 'Backend',
    items: ['FastAPI', 'WebSocket', 'httpx', 'Supabase REST', 'pytest'],
  },
  {
    title: 'Infra',
    items: ['Vercel Frontend', 'Railway Backend', 'Supabase DB', 'PostgreSQL'],
  },
];

const envChecklist: EnvironmentPair[] = [
  {
    scope: 'frontend',
    key: 'NEXT_PUBLIC_API_URL',
    value: process.env.NEXT_PUBLIC_API_URL,
    note: '백엔드 API 기본 URL',
    required: '필수',
  },
  {
    scope: 'frontend',
    key: 'NEXT_PUBLIC_WS_URL',
    value: process.env.NEXT_PUBLIC_WS_URL,
    note: '실시간 자막 WebSocket 기본 URL',
    required: '필수',
  },
  {
    scope: 'frontend',
    key: 'NEXT_PUBLIC_SUPABASE_URL',
    value: process.env.NEXT_PUBLIC_SUPABASE_URL,
    note: 'Supabase 연동 URL(있을 경우)',
    required: '조건',
  },
  {
    scope: 'frontend',
    key: 'NEXT_PUBLIC_SUPABASE_ANON_KEY',
    value: process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY,
    note: 'Supabase 공개 키',
    required: '조건',
  },
  {
    scope: 'backend',
    key: 'SUPABASE_URL',
    note: '백엔드 환경 변수(클라이언트 미표시)',
    required: '필수',
  },
  {
    scope: 'backend',
    key: 'SUPABASE_KEY',
    note: '백엔드 환경 변수(클라이언트 미표시)',
    required: '필수',
  },
  {
    scope: 'backend',
    key: 'OPENAI_API_KEY',
    note: 'STT(전사·화자구분) + AI 교정/요약 공용 서버 키(서버 전용)',
    required: '필수',
  },
];

const runGuide: HowToRunStep[] = [
  {
    title: '백엔드 기동',
    command: 'cd backend\npython -m venv .venv\n.\\.venv\\Scripts\\activate\npip install -r requirements.txt\nuvicorn app.main:app --reload --port 8000',
    description: '백엔드 API 서버를 개발 모드로 띄웁니다.',
  },
  {
    title: '프론트엔드 기동',
    command: 'cd frontend\nnpm install\nnpm run dev',
    description: '프론트엔드를 개발 모드로 띄워 브라우저로 확인합니다.',
  },
  {
    title: '테스트',
    command: 'cd frontend\nnpx jest\ncd ../backend\npython -m pytest -v',
    description: 'UI/서비스 테스트를 한 번에 점검합니다.',
  },
  {
    title: '배포 빌드 검증',
    command: 'cd frontend\nnpm run build\ncd ../backend\npython -m pytest -q',
    description: '빌드 가능 여부 및 핵심 테스트를 빠르게 확인합니다.',
  },
];

const statusChipClass: Record<ImprovementStatus, string> = {
  done: 'border-success/30 bg-success/5 text-success',
  'in-progress': 'border-warning-bg/40 bg-warning-bg/10 text-warning',
  planned: 'border-info/30 bg-info/5 text-info',
};

const statusLabel: Record<ImprovementStatus, string> = {
  done: '완료',
  'in-progress': '진행 중',
  planned: '예정',
};

const hiddenMask = (value?: string): string => {
  if (!value) {
    return '미설정';
  }

  if (value.length <= 10) {
    return '****';
  }

  return `${value.slice(0, 6)}...${value.slice(-4)}`;
};

function formatDuration(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  return `${h}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
}

export default function AdminPage() {
  const [health, setHealth] = useState<HealthStatus>({ status: 'unknown', label: '확인 대기' });
  const [channels, setChannels] = useState<ChannelType[]>([]);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [lastCheckedAt, setLastCheckedAt] = useState<string | null>(null);

  // API Status
  const [apiStatusList, setApiStatusList] = useState<ApiStatusItem[]>([]);
  const [isApiStatusLoading, setIsApiStatusLoading] = useState(false);

  // Statistics
  const [statsOverview, setStatsOverview] = useState<StatsOverviewType | null>(null);
  const [statsSpeakers, setStatsSpeakers] = useState<StatsSpeakerItem[]>([]);
  const [statsMeetings, setStatsMeetings] = useState<StatsMeetingByMonth[]>([]);
  const [isStatsLoading, setIsStatsLoading] = useState(false);

  // Report export
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  const [isExporting, setIsExporting] = useState(false);

  /**
   * 3탭 (2026-08-25 개선안 2i).
   * 한 페이지가 8개 섹션으로 운영 점검·외부 API·통계·리포트·개선 이력·기술 스택·
   * 환경변수·실행 방법을 모두 하고 있었다. **매일 보는 것과 한 번 읽는 것**이
   * 섞여 있어 매번 스크롤로 찾아야 했다.
   */
  const [adminTab, setAdminTab] = useState<'ops' | 'stats' | 'env'>('ops');

  const channelStats = useMemo(() => {
    const total = channels.length;
    const onAir = channels.filter((channel) => channel.livestatus === 1).length;
    const sttRunning = channels.filter((channel) => channel.stt_running).length;
    // ★개수가 아니라 **목록**이다 — 경고에 채널 이름과 이동 버튼을 붙이려면
    //   "몇 개인가"만으로는 부족하다. 지금은 개수만 알려주고 어디로 가야 하는지
    //   말하지 않는 것이 문제였다 (2026-08-25 개선안 2i).
    const staleLiveChannels = channels.filter(
      (channel) => channel.livestatus === 1 && !channel.stt_running,
    );

    return {
      total,
      onAir,
      sttRunning,
      staleLive: staleLiveChannels.length,
      staleLiveChannels,
    };
  }, [channels]);

  const improvementSummary = useMemo(() => {
    return {
      done: improvementLog.filter((item) => item.status === 'done').length,
      inProgress: improvementLog.filter((item) => item.status === 'in-progress').length,
      planned: improvementLog.filter((item) => item.status === 'planned').length,
    };
  }, []);

  const runDiagnostics = useCallback(async () => {
    setIsRefreshing(true);
    setErrorMessage(null);

    if (typeof fetch !== 'function') {
      setHealth({ status: 'unknown', label: '브라우저 fetch 미지원' });
      setChannels([]);
      setIsRefreshing(false);
      return;
    }

    try {
      const [healthRes, channelRes] = await Promise.all([
        fetch(`${API_BASE_URL}/health`, { cache: 'no-store' }),
        fetch(`${API_BASE_URL}/api/channels/status`, { cache: 'no-store' }),
      ]);

      if (!healthRes.ok || !channelRes.ok) {
        setHealth({
          status: 'unhealthy',
          label: `HTTP 오류: ${healthRes.status}/${channelRes.status}`,
        });
        setChannels([]);
      } else {
        const healthData = await healthRes.json();
        const channelData = await channelRes.json();

        setHealth({
          status: healthData?.status === 'healthy' ? 'healthy' : 'unhealthy',
          label: healthData?.status || 'health 응답 없음',
        });

        setChannels(Array.isArray(channelData) ? (channelData as ChannelType[]) : []);
      }
    } catch (error) {
      setHealth({ status: 'unhealthy', label: 'API 요청 실패' });
      setChannels([]);
      setErrorMessage(error instanceof Error ? error.message : '네트워크 오류');
    } finally {
      setLastCheckedAt(new Date().toLocaleTimeString());
      setIsRefreshing(false);
    }
  }, []);

  const loadApiStatus = useCallback(async () => {
    setIsApiStatusLoading(true);
    try {
      const data = await getApiStatus();
      setApiStatusList(data);
    } catch (error) {
      console.error('API 상태 조회 실패:', error);
    } finally {
      setIsApiStatusLoading(false);
    }
  }, []);

  const loadStatistics = useCallback(async () => {
    setIsStatsLoading(true);
    try {
      const [overview, speakers, meetings] = await Promise.all([
        getStatsOverview(),
        getStatsSpeakers(),
        getStatsMeetings(),
      ]);
      setStatsOverview(overview);
      setStatsSpeakers(speakers);
      setStatsMeetings(meetings);
    } catch (error) {
      console.error('통계 로드 실패:', error);
    } finally {
      setIsStatsLoading(false);
    }
  }, []);

  useEffect(() => {
    void runDiagnostics();
    void loadStatistics();
    void loadApiStatus();
  }, [runDiagnostics, loadStatistics, loadApiStatus]);

  // Auto-refresh API status every 30 seconds
  useEffect(() => {
    const interval = setInterval(() => {
      void loadApiStatus();
    }, 30000);
    return () => clearInterval(interval);
  }, [loadApiStatus]);

  const handleExportReport = async () => {
    if (!dateFrom || !dateTo) {
      alert('날짜 범위를 선택해주세요.');
      return;
    }

    try {
      setIsExporting(true);
      await getStatsReport(dateFrom, dateTo, 'markdown');
    } catch (error) {
      alert(error instanceof Error ? error.message : '리포트 내보내기 실패');
    } finally {
      setIsExporting(false);
    }
  };

  const maxMeetingCount = Math.max(...statsMeetings.map((m) => m.count), 1);

  return (
    <div className="min-h-[60vh] p-6">
      <div className="mx-auto flex max-w-6xl flex-col gap-6">
        {/* ── 머리 + 3탭 ───────────────────────────────────────────────
            2026-08-25 개선안 2i: 성격이 다른 셋을 탭으로 갈랐다.
            운영 현황(매일) / 통계·리포트(주기적) / 환경·문서(한 번 읽는 것). */}
        <header className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <div className="flex flex-wrap items-baseline gap-2.5">
              <h1 className="text-2xl font-bold tracking-heading text-text">시스템관리</h1>
              <span className="text-sm text-text-muted">운영 점검과 핵심 지표를 한곳에서 확인합니다.</span>
            </div>
            <div className="mt-2.5 h-[2px] w-11 bg-accent" />
          </div>
          <div className="flex flex-wrap items-center gap-2.5">
            {lastCheckedAt && (
              <span className="text-[12.5px] tabular-nums text-text-dim">
                마지막 점검: {lastCheckedAt} · 30초 자동 갱신
              </span>
            )}
            <Button variant="secondary" onClick={runDiagnostics} loading={isRefreshing}>
              {isRefreshing ? '점검 중...' : '시스템 점검'}
            </Button>
          </div>
        </header>

        <div role="tablist" aria-label="시스템관리 영역" className="flex items-stretch gap-0.5 border-b border-border">
          {([
            ['ops', '운영 현황'],
            ['stats', '통계 · 리포트'],
            ['env', '환경 · 문서'],
          ] as const).map(([key, label]) => (
            <button
              key={key}
              type="button"
              role="tab"
              aria-selected={adminTab === key}
              onClick={() => setAdminTab(key)}
              data-testid={`admin-tab-${key}`}
              className={`inline-flex h-10 items-center px-4 text-[14.5px] transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary ${
                adminTab === key
                  ? 'font-bold text-primary shadow-[inset_0_-3px_0_0_var(--ggc-primary)]'
                  : 'font-medium text-text-secondary hover:bg-surface-raised'
              }`}
            >
              {label}
            </button>
          ))}
        </div>

        {/* ── 운영 현황 ─────────────────────────────────────────────── */}
        {adminTab === 'ops' && (
        <>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {([
            {
              key: 'api',
              label: 'API 상태',
              value: health.label,
              unit: '',
              dot: health.status === 'healthy' ? 'bg-success' : health.status === 'unhealthy' ? 'bg-danger' : 'bg-gray-300',
              fg: health.status === 'healthy' ? 'text-success' : health.status === 'unhealthy' ? 'text-danger' : 'text-text-secondary',
              border: health.status === 'healthy' ? 'border-success/35' : health.status === 'unhealthy' ? 'border-danger/35' : 'border-border',
              big: false,
            },
            { key: 'channels', label: '채널 수', value: String(channelStats.total), unit: '개', dot: 'bg-primary', fg: 'text-text', border: 'border-border', big: true },
            { key: 'onair', label: '방송중 채널', value: String(channelStats.onAir), unit: '개', dot: 'bg-live', fg: 'text-text', border: 'border-border', big: true },
            {
              key: 'stt',
              label: 'STT 실행',
              value: String(channelStats.sttRunning),
              unit: '개',
              dot: 'bg-warning-bg',
              fg: 'text-text',
              border: channelStats.staleLive > 0 ? 'border-warning-bg/45' : 'border-border',
              big: true,
            },
          ]).map((kpi) => (
            <div
              key={kpi.key}
              data-testid={`admin-kpi-${kpi.key}`}
              className={`rounded-[10px] border ${kpi.border} bg-surface px-4 py-3.5`}
            >
              <div className="flex items-center gap-2">
                <span className={`h-[7px] w-[7px] shrink-0 rounded-full ${kpi.dot}`} aria-hidden="true" />
                <span className="text-xs font-semibold text-text-muted">{kpi.label}</span>
              </div>
              <div className="mt-1.5 flex items-baseline gap-1">
                <span className={`${kpi.big ? 'text-[26px]' : 'text-lg'} font-bold tracking-heading tabular-nums ${kpi.fg}`}>
                  {kpi.value}
                </span>
                {kpi.unit && <span className="text-[13px] text-text-dim">{kpi.unit}</span>}
              </div>
            </div>
          ))}
        </div>

        {/* 방송중·STT 비활성 경고 — 채널 이름과 갈 곳을 함께 준다 */}
        {channelStats.staleLive > 0 && (
          <div className="flex flex-wrap items-center gap-2.5 rounded-lg border border-warning-bg/40 bg-warning-bg/[0.12] px-3.5 py-2.5">
            <svg className="h-[17px] w-[17px] shrink-0 text-warning-dark" fill="none" stroke="currentColor" strokeWidth={1.75} viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
            </svg>
            <span className="min-w-0 flex-1 text-[13.5px] text-warning-dark">
              방송중이지만 STT가 비활성인 채널이 <b>{channelStats.staleLive}개</b> 있습니다.
              {channelStats.staleLiveChannels.length > 0 && (
                <span> — {channelStats.staleLiveChannels.map((c) => c.name).join(', ')}</span>
              )}
            </span>
            {channelStats.staleLiveChannels[0] && (
              <Link
                href={`/live?channel=${channelStats.staleLiveChannels[0].id}`}
                className="inline-flex h-7 shrink-0 items-center rounded-md border border-warning-bg/50 bg-surface px-2.5 text-[12.5px] font-semibold text-warning-dark transition-colors hover:bg-warning-bg/10"
              >
                채널 열기
              </Link>
            )}
          </div>
        )}

        {errorMessage && <Callout variant="danger">오류: {errorMessage}</Callout>}

        {/* 외부 API 현황 — 카드 6개 → 표 한 장.
            서비스 간 비교가 목적인 화면이라 같은 값이 같은 세로선에 와야 한다. */}
        <section className="flex flex-col gap-2.5">
          <div className="flex flex-wrap items-baseline justify-between gap-3">
            <div className="flex flex-wrap items-baseline gap-2.5">
              <h2 className="text-[15px] font-bold tracking-heading text-text">외부 API 현황</h2>
              <span className="text-[12.5px] text-text-dim">연동 서비스 상태와 오늘 호출 통계 · 30초 자동 갱신</span>
            </div>
            <Button variant="outline" size="sm" onClick={loadApiStatus} loading={isApiStatusLoading}>
              {isApiStatusLoading ? '조회 중...' : '새로고침'}
            </Button>
          </div>

          {isApiStatusLoading && apiStatusList.length === 0 ? (
            <div className="flex items-center justify-center py-8">
              <div className="h-8 w-8 animate-spin rounded-full border-2 border-gray-100 border-t-primary" />
            </div>
          ) : (
            <div className="overflow-x-auto rounded-[10px] border border-border bg-surface">
              <div className="min-w-[760px]">
                <div className="flex items-center gap-3.5 border-b border-border bg-gray-50 px-4 py-2 text-[11px] font-bold tracking-[0.06em] text-text-dim">
                  <span className="w-[170px] shrink-0">서비스</span>
                  <span className="w-24 shrink-0">상태</span>
                  <span className="min-w-0 flex-1">세부</span>
                  <span className="w-[78px] shrink-0 text-right">호출(오늘)</span>
                  <span className="w-[78px] shrink-0 text-right">평균 지연</span>
                  <span className="w-[70px] shrink-0 text-right">오류율</span>
                </div>
                {apiStatusList.map((api) => {
                  const tone =
                    api.status === 'connected'
                      ? { label: '정상', cls: 'bg-success/10 text-success', dot: 'bg-success' }
                      : api.status === 'disconnected'
                        ? { label: '끊김', cls: 'bg-danger/10 text-danger', dot: 'bg-danger' }
                        : api.status === 'not_configured'
                          ? { label: '미설정', cls: 'bg-gray-100 text-text-muted', dot: 'bg-gray-400' }
                          : { label: '지연', cls: 'bg-warning-bg/20 text-warning-dark', dot: 'bg-warning-bg' };
                  const detail = Object.entries(api.details)
                    .map(([k, v]) => `${k}=${v === null ? '-' : String(v)}`)
                    .join(' · ');
                  return (
                    <div
                      key={api.name}
                      className="flex items-center gap-3.5 border-b border-border-subtle px-4 py-2.5 last:border-b-0"
                      data-testid={`api-row-${api.name}`}
                    >
                      <span className="flex w-[170px] shrink-0 items-center gap-2">
                        <span className={`h-2 w-2 shrink-0 rounded-full ${tone.dot}`} aria-hidden="true" />
                        <span className="min-w-0 truncate text-sm font-semibold text-text" title={api.description}>
                          {api.name}
                        </span>
                      </span>
                      <span className="w-24 shrink-0">
                        <span className={`inline-flex h-[22px] items-center rounded-full px-2.5 text-[11.5px] font-semibold ${tone.cls}`}>
                          {tone.label}
                        </span>
                      </span>
                      <span className="min-w-0 flex-1 truncate font-mono text-xs text-text-muted" title={detail}>
                        {detail || '-'}
                      </span>
                      <span className="w-[78px] shrink-0 text-right text-sm font-semibold tabular-nums text-text">
                        {api.stats.calls_today}
                      </span>
                      <span className="w-[78px] shrink-0 text-right text-sm tabular-nums text-text-secondary">
                        {api.stats.avg_latency_ms > 0 ? `${api.stats.avg_latency_ms}ms` : '-'}
                      </span>
                      <span
                        className={`w-[70px] shrink-0 text-right text-sm font-semibold tabular-nums ${
                          api.stats.error_rate > 0 ? 'text-danger' : 'text-text-dim'
                        }`}
                      >
                        {api.stats.error_rate > 0 ? `${api.stats.error_rate}%` : '-'}
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </section>
        </>
        )}

        {/* ── 통계 · 리포트 ─────────────────────────────────────────── */}
        {adminTab === 'stats' && (
        <>
        {/* 통계 대시보드 */}
        <section className="rounded-lg border border-border bg-surface p-6">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-lg font-semibold text-text">통계 대시보드</h2>
              <p className="mt-1 text-sm text-text-muted">회의록 자막 통계를 시각화합니다.</p>
            </div>
          </div>

          {isStatsLoading ? (
            <div className="flex items-center justify-center py-8">
              <div className="w-8 h-8 border-2 border-border border-t-primary rounded-full animate-spin" />
            </div>
          ) : (
            <>
              {/* 개요 카드 4개 */}
              <div data-testid="stats-overview" className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4 mb-6">
                <div className="rounded-lg border border-border bg-surface p-6">
                  <p className="text-sm text-text-muted mb-1">총 회의 수</p>
                  <p className="text-3xl font-bold text-text">{statsOverview?.total_meetings ?? 0}</p>
                </div>
                <div className="rounded-lg border border-border bg-surface p-6">
                  <p className="text-sm text-text-muted mb-1">총 자막 수</p>
                  <p className="text-3xl font-bold text-text">{statsOverview?.total_subtitles ?? 0}</p>
                </div>
                <div className="rounded-lg border border-border bg-surface p-6">
                  <p className="text-sm text-text-muted mb-1">총 재생시간</p>
                  <p className="text-3xl font-bold text-text">
                    {statsOverview ? formatDuration(statsOverview.total_duration) : '0:00:00'}
                  </p>
                </div>
                <div className="rounded-lg border border-border bg-surface p-6">
                  <p className="text-sm text-text-muted mb-1">평균 신뢰도</p>
                  <p className="text-3xl font-bold text-text">
                    {statsOverview ? `${(statsOverview.average_confidence * 100).toFixed(1)}%` : '0%'}
                  </p>
                </div>
              </div>

              {/* 월별 회의 추이 */}
              <div data-testid="stats-chart" className="mb-6">
                <h3 className="text-base font-semibold text-text mb-3">월별 회의 추이</h3>
                <div className="space-y-2">
                  {statsMeetings.length === 0 ? (
                    <p className="text-sm text-text-muted text-center py-4">데이터가 없습니다.</p>
                  ) : (
                    statsMeetings.map((item) => {
                      const barWidth = (item.count / maxMeetingCount) * 100;
                      return (
                        <div key={item.month} className="flex items-center gap-3">
                          <span className="text-sm text-text-secondary w-20">{item.month}</span>
                          <div className="flex-1 bg-surface-raised rounded-full h-6 relative">
                            <div
                              className="bg-primary h-6 rounded-full flex items-center justify-end pr-2"
                              style={{ width: `${barWidth}%` }}
                            >
                              <span className="text-xs font-medium text-white">{item.count}</span>
                            </div>
                          </div>
                        </div>
                      );
                    })
                  )}
                </div>
              </div>

              {/* 화자별 발언 랭킹 */}
              <div data-testid="stats-speakers">
                <h3 className="text-base font-semibold text-text mb-3">화자별 발언 랭킹 (상위 10명)</h3>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead className="bg-surface-raised border-b border-border">
                      <tr>
                        <th className="px-4 py-2 text-left text-xs font-medium text-text-muted">화자명</th>
                        <th className="px-4 py-2 text-right text-xs font-medium text-text-muted">발언 횟수</th>
                        <th className="px-4 py-2 text-right text-xs font-medium text-text-muted">총 시간</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border">
                      {statsSpeakers.length === 0 ? (
                        <tr>
                          <td colSpan={3} className="px-4 py-8 text-center text-text-muted">데이터가 없습니다.</td>
                        </tr>
                      ) : (
                        statsSpeakers.slice(0, 10).map((speaker, index) => (
                          <tr key={speaker.speaker} className="hover:bg-surface-raised">
                            <td className="px-4 py-2 text-text font-medium">
                              {index + 1}. {speaker.speaker}
                            </td>
                            <td className="px-4 py-2 text-right text-text-secondary">{speaker.total_count}회</td>
                            <td className="px-4 py-2 text-right text-text-secondary">{formatDuration(speaker.total_duration)}</td>
                          </tr>
                        ))
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            </>
          )}
        </section>

        {/* 리포트 내보내기 */}
        <section className="rounded-lg border border-border bg-surface p-6">
          <h2 className="text-lg font-semibold text-text mb-3">리포트 내보내기</h2>
          <p className="text-sm text-text-muted mb-4">기간별 통계를 Markdown 파일로 다운로드합니다.</p>
          <div className="flex items-end gap-3 flex-wrap">
            <div className="flex-1 min-w-[200px]">
              <Input
                type="date"
                label="시작일"
                value={dateFrom}
                onChange={(e) => setDateFrom(e.target.value)}
              />
            </div>
            <div className="flex-1 min-w-[200px]">
              <Input
                type="date"
                label="종료일"
                value={dateTo}
                onChange={(e) => setDateTo(e.target.value)}
              />
            </div>
            <Button
              variant="primary"
              onClick={handleExportReport}
              disabled={isExporting || !dateFrom || !dateTo}
              loading={isExporting}
            >
              {isExporting ? '내보내는 중...' : 'Markdown 내보내기'}
            </Button>
          </div>
        </section>
        </>
        )}

        {/* ── 환경 · 문서 ───────────────────────────────────────────── */}
        {adminTab === 'env' && (
        <>
        {/* 기능 개선 이력 */}
        <section className="rounded-lg border border-border bg-surface p-6">
          <div className="mb-3 flex items-end justify-between gap-3">
            <div>
              <h2 className="text-lg font-semibold text-text">기능 개선 이력(일목요연)</h2>
              <p className="mt-1 text-sm text-text-muted">요청/개발 이력과 현재 상태를 한눈에 확인합니다.</p>
            </div>
            <div className="text-xs text-text-muted">
              완료 {improvementSummary.done}건 · 진행 중 {improvementSummary.inProgress}건 · 예정 {improvementSummary.planned}건
            </div>
          </div>

          <div className="grid gap-3 md:grid-cols-2">
            {improvementLog.map((item) => (
              <article key={`${item.domain}-${item.feature}`} className="rounded-md border border-border bg-surface-raised p-4">
                <div className="mb-2 flex items-start justify-between gap-2">
                  <p className="text-sm font-semibold text-text">{item.domain}</p>
                  <span className={`rounded-full border px-2 py-0.5 text-xs font-medium ${statusChipClass[item.status]}`}>{statusLabel[item.status]}</span>
                </div>
                <p className="text-sm text-text">{item.feature}</p>
                <p className="mt-2 text-xs text-text-muted">근거: {item.phase}</p>
                <p className="mt-1 text-xs text-text-muted">{item.note}</p>
              </article>
            ))}
          </div>
        </section>

        {/* 기술 스택 + 환경변수 */}
        <section className="grid gap-6 lg:grid-cols-3">
          <div className="rounded-lg border border-border bg-surface p-6">
            <h2 className="text-lg font-semibold text-text">기술 스택</h2>
            <div className="mt-3 space-y-3">
              {technologySummary.map((group) => (
                <div key={group.title} className="rounded-md border border-border bg-surface-raised p-3">
                  <p className="text-sm font-medium text-text">{group.title}</p>
                  <ul className="mt-2 space-y-1 text-xs text-text-secondary">
                    {group.items.map((item) => (
                      <li key={item}>- {item}</li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          </div>

          <div className="rounded-lg border border-border bg-surface p-6 lg:col-span-2">
            <h2 className="text-lg font-semibold text-text">환경변수 · API 키 점검</h2>
            <p className="mt-1 text-sm text-text-muted">클라이언트 노출 대상과 백엔드 전용 키를 분리해 관리합니다.</p>

            <div className="mt-4 space-y-2">
              {envChecklist.map((entry) => (
                <div key={entry.key} className="rounded-md border border-border bg-surface-raised p-3">
                  <div className="flex items-start justify-between gap-2">
                    <p className="text-sm font-medium text-text">{entry.key}</p>
                    <span className="text-xs text-text-muted">{entry.scope}</span>
                  </div>
                  <p className="mt-1 text-xs text-text-muted">필수: {entry.required}</p>
                  <p className="mt-1 font-mono text-xs text-text-secondary">
                    값: {entry.value ? hiddenMask(entry.value) : '서버/브라우저 미설정'}
                  </p>
                  <p className="mt-1 text-xs text-text-muted">{entry.note}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* 실행 방법 */}
        <section className="rounded-lg border border-border bg-surface p-6">
          <h2 className="text-lg font-semibold text-text">실행 방법</h2>
          <div className="mt-3 grid gap-3 md:grid-cols-2">
            {runGuide.map((step) => (
              <div key={step.title} className="rounded-md border border-border bg-surface-raised p-4">
                <p className="text-sm font-medium text-text">{step.title}</p>
                <p className="mt-1 text-xs text-text-muted">{step.description}</p>
                <pre className="mt-2 whitespace-pre-wrap rounded border border-border bg-surface p-2 text-xs text-text-secondary">
                  {step.command}
                </pre>
              </div>
            ))}
          </div>
        </section>
        </>
        )}
      </div>
    </div>
  );
}
