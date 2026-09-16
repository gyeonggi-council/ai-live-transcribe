'use client';

import { useCallback, useEffect, useState } from 'react';

import Link from 'next/link';

import PageHeader from '@/components/PageHeader';
import Callout from '@/components/ui/Callout';
import Card from '@/components/ui/Card';
import { usePageAccessLog } from '@/hooks/useAccessLog';
import { getAccessStats } from '@/lib/api';
import type { AccessStatsType } from '@/types';

/**
 * /visits — 접속 통계 (2026-09-16 담당자 요청)
 *
 * 사이드바의 「오늘 N · 누적 N」을 누르면 여기로 온다. 누구나 볼 수 있다(담당자 결정).
 *
 * 개인정보: **IP 주소를 저장하지 않는다.** 서버가 받는 즉시 접속처 '이름'으로 바꾼다.
 * 그래서 이 화면에는 IP·계정·기기 식별자가 한 줄도 없고, 같은 사람이 날짜를 넘겨
 * 다시 왔는지도 알 수 없다(브라우저 표식이 하루마다 새로 생긴다).
 */

const PERIODS = [7, 30, 90] as const;
const WEEKDAYS = ['월', '화', '수', '목', '금', '토', '일'];

function hoursText(seconds: number): string {
  if (!seconds) return '0분';
  if (seconds < 3600) return `${Math.round(seconds / 60)}분`;
  return `${(seconds / 3600).toFixed(1)}시간`;
}

function dayLabel(iso: string): string {
  const [, m, d] = iso.split('-');
  return `${Number(m)}.${Number(d)}`;
}

function Bar({ value, max, tone = 'primary' }: { value: number; max: number; tone?: 'primary' | 'accent' }) {
  const pct = max > 0 ? Math.max(value > 0 ? 3 : 0, (value / max) * 100) : 0;
  return (
    <div className="flex-1 bg-surface-raised rounded-full h-5 relative overflow-hidden">
      <div
        className={`h-5 rounded-full ${tone === 'primary' ? 'bg-primary' : 'bg-accent'}`}
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}

function StatCard({
  label,
  value,
  hint,
  testId,
}: {
  label: string;
  value: string;
  hint?: string;
  testId?: string;
}) {
  return (
    <Card padding="sm" data-testid={testId}>
      <div className="text-xs text-text-muted">{label}</div>
      <div className="mt-1 text-2xl font-semibold text-text tabular-nums">{value}</div>
      {hint && <div className="mt-0.5 text-xs text-text-dim">{hint}</div>}
    </Card>
  );
}

/** 접속처·회의·기능 공통 — 이름 + 막대 + 숫자 한 줄 */
function RankRow({
  name,
  value,
  max,
  right,
  onClick,
  expanded,
  testId,
}: {
  name: string;
  value: number;
  max: number;
  right: string;
  onClick?: () => void;
  expanded?: boolean;
  testId?: string;
}) {
  const body = (
    <div className="flex items-center gap-3 w-full">
      <span className="w-40 shrink-0 truncate text-sm text-text-secondary text-left">{name}</span>
      <Bar value={value} max={max} />
      <span className="w-28 shrink-0 text-right text-sm text-text tabular-nums">{right}</span>
      {onClick && (
        <svg
          className={`w-4 h-4 shrink-0 text-text-dim transition-transform ${expanded ? 'rotate-180' : ''}`}
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
          strokeWidth={2}
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
        </svg>
      )}
    </div>
  );
  if (!onClick) return <div className="px-4 py-2">{body}</div>;
  return (
    <button
      type="button"
      onClick={onClick}
      aria-expanded={expanded}
      data-testid={testId}
      className="w-full px-4 py-2 hover:bg-surface-raised focus-visible:ring-2 focus-visible:ring-primary rounded"
    >
      {body}
    </button>
  );
}

function SectionTitle({ title, help }: { title: string; help: string }) {
  return (
    <div className="mb-3">
      <h2 className="text-base font-semibold text-text">{title}</h2>
      <p className="text-xs text-text-muted mt-0.5">{help}</p>
    </div>
  );
}

/** 접속처를 눌렀을 때 그 자리에서 펼쳐지는 상세 */
function SiteDetail({ label, days }: { label: string; days: number }) {
  const [data, setData] = useState<AccessStatsType | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let alive = true;
    setData(null);
    setFailed(false);
    getAccessStats(days, label)
      .then((d) => alive && setData(d))
      .catch(() => alive && setFailed(true));
    return () => {
      alive = false;
    };
  }, [label, days]);

  if (failed) return <div className="px-4 py-3 text-sm text-text-muted">상세를 불러오지 못했습니다.</div>;
  if (!data) return <div className="px-4 py-3 text-sm text-text-muted">불러오는 중...</div>;

  const maxHour = Math.max(...data.hourly.map((h) => h.visitors), 1);
  const maxMeeting = Math.max(...data.meetings.map((m) => m.watch_seconds), 1);

  return (
    <div className="px-4 py-3 bg-surface-inset border-t border-border" data-testid="site-detail">
      <div className="grid gap-4 lg:grid-cols-2">
        <div>
          <div className="text-xs font-medium text-text-secondary mb-2">시간대 (0~23시)</div>
          <div className="flex items-end gap-0.5 h-20">
            {data.hourly.map((h) => (
              <div key={h.hour} className="flex-1 flex flex-col items-center justify-end h-full" title={`${h.hour}시 ${h.visitors}명`}>
                <div className="w-full bg-primary rounded-sm" style={{ height: `${(h.visitors / maxHour) * 100}%` }} />
              </div>
            ))}
          </div>
          <div className="flex justify-between text-[10px] text-text-dim mt-1">
            <span>0시</span>
            <span>12시</span>
            <span>23시</span>
          </div>
          <div className="mt-3 text-xs text-text-muted">
            이 기간 접속 {data.totals.visitors.toLocaleString()}회 · 시청 {hoursText(data.totals.watch_seconds)} ·
            화면 열람 {data.totals.page_views.toLocaleString()}회
          </div>
        </div>
        <div>
          <div className="text-xs font-medium text-text-secondary mb-2">많이 본 회의</div>
          {data.meetings.length === 0 ? (
            <div className="text-xs text-text-muted">아직 기록이 없습니다.</div>
          ) : (
            <ul className="space-y-1">
              {data.meetings.slice(0, 5).map((m) => (
                <li key={m.meeting_id} className="flex items-center gap-2">
                  <Link href={`/vod/${m.meeting_id}`} className="flex-1 truncate text-xs text-primary hover:underline">
                    {m.title}
                  </Link>
                  <Bar value={m.watch_seconds} max={maxMeeting} />
                  <span className="w-16 text-right text-xs text-text tabular-nums">{hoursText(m.watch_seconds)}</span>
                </li>
              ))}
            </ul>
          )}
          <div className="mt-3 text-xs font-medium text-text-secondary mb-1">무엇을 했나</div>
          <div className="flex flex-wrap gap-1.5">
            {data.features.length === 0 && <span className="text-xs text-text-muted">아직 기록이 없습니다.</span>}
            {data.features.map((f) => (
              <span key={f.kind} className="px-2 py-0.5 rounded-full bg-surface border border-border text-xs text-text-secondary">
                {f.label} {f.events.toLocaleString()}
              </span>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

export default function VisitsPage() {
  const [days, setDays] = useState<number>(30);
  const [data, setData] = useState<AccessStatsType | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [openSite, setOpenSite] = useState<string | null>(null);

  usePageAccessLog('/visits');

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await getAccessStats(days));
    } catch (e) {
      setError(e instanceof Error ? e.message : '불러오기 실패');
    } finally {
      setLoading(false);
    }
  }, [days]);

  useEffect(() => {
    void load();
  }, [load]);

  const maxDaily = Math.max(...(data?.daily.map((d) => d.visitors) ?? [0]), 1);
  const maxSite = Math.max(...(data?.sites.map((s) => s.visitors) ?? [0]), 1);
  const maxMeeting = Math.max(...(data?.meetings.map((m) => m.watch_seconds) ?? [0]), 1);
  const maxFeature = Math.max(...(data?.features.map((f) => f.events) ?? [0]), 1);
  const maxHeat = Math.max(...(data?.weekday_hour.flat() ?? [0]), 1);
  const deviceTotal = (data?.devices ?? []).reduce((sum, d) => sum + d.visitors, 0);

  return (
    <div className="ggc-page" data-testid="visits-page">
      <PageHeader
        title="접속 통계"
        description="누가 · 언제 · 무엇을 보는지. 서비스를 어떻게 운영할지 정할 때 보는 화면입니다."
      />

      <div className="flex flex-wrap items-center gap-2 mb-4">
        {PERIODS.map((p) => (
          <button
            key={p}
            type="button"
            data-testid={`period-${p}`}
            onClick={() => setDays(p)}
            className={`px-3 py-1.5 rounded-full text-sm border transition-colors ${
              days === p
                ? 'bg-primary text-white border-primary'
                : 'bg-surface text-text-secondary border-border hover:bg-surface-raised'
            }`}
          >
            최근 {p}일
          </button>
        ))}
      </div>

      {loading && (
        <div className="py-16 text-center text-text-muted">
          <div className="w-8 h-8 border-2 border-primary border-t-transparent rounded-full animate-spin mx-auto mb-3" />
          접속 기록 집계 중...
        </div>
      )}
      {error && <Callout variant="danger">불러오기 실패: {error}</Callout>}

      {!loading && !error && data && (
        <div className="space-y-6">
          <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
            <StatCard testId="stat-today" label="오늘 접속" value={`${data.today.visitors.toLocaleString()}명`} />
            <StatCard
              testId="stat-now-watching"
              label="지금 보는 중"
              value={`${data.now_watching.toLocaleString()}명`}
              hint="최근 5분"
            />
            <StatCard testId="stat-watch" label="오늘 시청 시간" value={hoursText(data.today.watch_seconds)} />
            <StatCard label="하루 평균 접속" value={`${data.totals.avg_daily_visitors.toLocaleString()}명`} hint={`최근 ${days}일`} />
            <StatCard
              testId="stat-login-prompt"
              label="앱 로그인 안내"
              value={`${data.totals.login_prompts.toLocaleString()}회`}
              hint="로그인이 필요해 안내를 본 횟수"
            />
          </div>

          {data.insights.length > 0 && (
            <Callout variant="info">
              <ul className="space-y-1 text-sm" data-testid="insights">
                {data.insights.map((line) => (
                  <li key={line}>· {line}</li>
                ))}
              </ul>
            </Callout>
          )}

          <Card>
            <SectionTitle title="날짜별 접속" help="회의가 있는 날만 쓰는지, 평소에도 쓰는지 봅니다." />
            <div className="space-y-1">
              {data.daily.map((d) => (
                <div key={d.date} className="flex items-center gap-3">
                  <span className="w-14 shrink-0 text-xs text-text-muted tabular-nums">{dayLabel(d.date)}</span>
                  <Bar value={d.visitors} max={maxDaily} />
                  <span className="w-24 shrink-0 text-right text-xs text-text tabular-nums">
                    {d.visitors.toLocaleString()}명
                  </span>
                  <span className="w-20 shrink-0 text-right text-xs text-text-muted tabular-nums hidden sm:block">
                    {hoursText(d.watch_seconds)}
                  </span>
                </div>
              ))}
            </div>
          </Card>

          <Card>
            <SectionTitle
              title="요일·시간대"
              help="진한 칸일수록 사람이 많습니다. 배포·정비는 옅은 칸에 하면 됩니다."
            />
            <div className="overflow-x-auto">
              <table className="text-[10px] text-text-muted">
                <tbody>
                  {data.weekday_hour.map((row, wd) => (
                    <tr key={WEEKDAYS[wd]}>
                      <th className="pr-2 font-normal text-right w-6">{WEEKDAYS[wd]}</th>
                      {row.map((v, hour) => (
                        <td key={hour} className="p-0">
                          <div
                            title={`${WEEKDAYS[wd]} ${hour}시 · ${v}명`}
                            className="w-4 h-4 m-[1px] rounded-sm"
                            style={{
                              backgroundColor:
                                v === 0 ? 'var(--ggc-surface-inset, #f6f8fb)' : 'var(--ggc-primary, #3c5d93)',
                              opacity: v === 0 ? 1 : 0.25 + (v / maxHeat) * 0.75,
                            }}
                          />
                        </td>
                      ))}
                    </tr>
                  ))}
                  <tr>
                    <th />
                    {Array.from({ length: 24 }, (_, h) => (
                      <td key={h} className="text-center align-top">
                        {h % 6 === 0 ? h : ''}
                      </td>
                    ))}
                  </tr>
                </tbody>
              </table>
            </div>
          </Card>

          <Card padding="none">
            <div className="px-4 pt-4">
              <SectionTitle
                title="접속처"
                help="IP 로 어디에서 왔는지 판단합니다. 줄을 누르면 그 접속처만 자세히 볼 수 있습니다."
              />
            </div>
            {data.sites.length === 0 ? (
              <div className="px-4 py-8 text-center text-text-muted text-sm">아직 쌓인 기록이 없습니다.</div>
            ) : (
              <div className="pb-2">
                {data.sites.map((s) => (
                  <div key={s.label} className="border-t border-hairline first:border-t-0">
                    <RankRow
                      testId={`site-${s.label}`}
                      name={s.label}
                      value={s.visitors}
                      max={maxSite}
                      right={`${s.visitors.toLocaleString()}명 · ${s.share}%`}
                      expanded={openSite === s.label}
                      onClick={() => setOpenSite(openSite === s.label ? null : s.label)}
                    />
                    {openSite === s.label && <SiteDetail label={s.label} days={days} />}
                  </div>
                ))}
              </div>
            )}
          </Card>

          <div className="grid gap-6 lg:grid-cols-2">
            <Card>
              <SectionTitle title="많이 본 회의" help="자막을 실제로 쓰는 회의가 어느 것인지 봅니다." />
              {data.meetings.length === 0 ? (
                <div className="py-6 text-center text-text-muted text-sm">아직 쌓인 기록이 없습니다.</div>
              ) : (
                <ul className="space-y-2">
                  {data.meetings.map((m) => (
                    <li key={m.meeting_id} className="flex items-center gap-3" data-testid="meeting-row">
                      <Link href={`/vod/${m.meeting_id}`} className="w-48 shrink-0 truncate text-sm text-primary hover:underline">
                        {m.title}
                      </Link>
                      <Bar value={m.watch_seconds} max={maxMeeting} />
                      <span className="w-24 shrink-0 text-right text-xs text-text tabular-nums">
                        {hoursText(m.watch_seconds)} · {m.viewers}명
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </Card>

            <Card>
              <SectionTitle title="무엇을 하나" help="살아 있는 기능과 아무도 안 쓰는 기능을 가릅니다." />
              {data.features.length === 0 ? (
                <div className="py-6 text-center text-text-muted text-sm">아직 쌓인 기록이 없습니다.</div>
              ) : (
                <ul className="space-y-2">
                  {data.features.map((f) => (
                    <li key={f.kind} className="flex items-center gap-3" data-testid="feature-row">
                      <span className="w-32 shrink-0 truncate text-sm text-text-secondary">{f.label}</span>
                      <Bar value={f.events} max={maxFeature} tone="accent" />
                      <span className="w-20 shrink-0 text-right text-xs text-text tabular-nums">
                        {f.events.toLocaleString()}회
                      </span>
                    </li>
                  ))}
                </ul>
              )}
              {deviceTotal > 0 && (
                <div className="mt-4 pt-3 border-t border-hairline text-sm text-text-secondary">
                  기기 —{' '}
                  {data.devices
                    .map((d) => {
                      const name = d.device === 'mobile' ? '휴대폰' : d.device === 'tablet' ? '태블릿' : 'PC';
                      return `${name} ${Math.round((d.visitors / deviceTotal) * 100)}%`;
                    })
                    .join(' · ')}
                </div>
              )}
            </Card>
          </div>

          <p className="text-xs text-text-muted leading-relaxed" data-testid="privacy-note">
            접속처는 IP 로 판단하지만 <strong>IP 주소는 저장하지 않습니다</strong> — 서버가 받는 즉시 위 이름으로 바꿉니다.
            계정·이름도 남기지 않으며, 브라우저 표식은 하루마다 새로 만들어 같은 사람이 다음 날 다시 왔는지 알 수 없습니다.
            기록은 180일 뒤 지워집니다.
            {data.detail_since
              ? ` 이 화면의 상세 항목은 ${data.detail_since}부터 쌓인 것입니다.`
              : ' 상세 항목은 이번 배포 이후부터 쌓입니다.'}{' '}
            사이드바의 「오늘 · 누적」 숫자는 2026-08-18부터의 기록입니다.
          </p>
        </div>
      )}
    </div>
  );
}
