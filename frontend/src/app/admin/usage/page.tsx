'use client';

import { useCallback, useEffect, useState } from 'react';

import PageHeader from '@/components/PageHeader';
import RoleGuard from '@/components/RoleGuard';
import Callout from '@/components/ui/Callout';
import Card from '@/components/ui/Card';
import { getUsageCosts } from '@/lib/api';
import type { UsageCostsResponse } from '@/lib/api';

/**
 * /admin/usage — API 사용량·비용 추정 대시보드 (관리자 전용)
 *
 * 실측 과금이 아니라 '오디오 시간 × 단가' 추정치를 위원회별로 보여준다.
 *   생중계: $0.6/시간 (실시간 윈도우 전사 + AI 교정)
 *   AI 자막: $0.4/시간 (VOD 배치 재전사)
 */

const PERIODS = [7, 14, 30, 60] as const;

function won(n: number): string {
  return `₩${n.toLocaleString('ko-KR')}`;
}

function hours(minutes: number): string {
  if (minutes < 60) return `${Math.round(minutes)}분`;
  return `${(minutes / 60).toFixed(1)}시간`;
}

function UsageDashboard() {
  const [days, setDays] = useState<number>(30);
  const [data, setData] = useState<UsageCostsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (d: number) => {
    setLoading(true);
    setError(null);
    try {
      setData(await getUsageCosts(d));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load(days);
  }, [days, load]);

  const t = data?.totals;

  return (
    <div className="p-6">
      <div className="max-w-5xl mx-auto">
        <PageHeader
          eyebrow="ADMIN"
          title="API 사용량 · 비용 (추정)"
          description="실시간 방송과 AI 자막 생성에 사용된 음성인식(STT) 비용을 위원회별로 추정합니다. 오디오 시간 × 단가 기준의 근사치이며, 정확한 청구액은 OpenAI 대시보드에서 확인하세요."
        />

        {/* 기간 선택 */}
        <div className="mb-4 flex items-center gap-2">
          <span className="text-sm text-text-muted">기간:</span>
          {PERIODS.map((p) => (
            <button
              key={p}
              onClick={() => setDays(p)}
              className={`px-3 py-1 rounded-full text-sm border transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary ${
                days === p
                  ? 'bg-primary text-white border-primary'
                  : 'bg-surface text-text-secondary border-border hover:bg-surface-raised'
              }`}
            >
              최근 {p}일
            </button>
          ))}
          {data && (
            <span className="ml-auto text-xs text-text-muted">
              {data.since} 이후 · 환율 1$ = {data.usd_krw.toLocaleString()}원 적용
            </span>
          )}
        </div>

        {loading && (
          <div className="py-16 text-center text-text-muted">
            <div className="w-8 h-8 border-2 border-primary border-t-transparent rounded-full animate-spin mx-auto mb-3" />
            사용량 집계 중...
          </div>
        )}

        {error && <Callout variant="danger">불러오기 실패: {error}</Callout>}

        {!loading && data && t && (
          <>
            {/* 합계 카드 */}
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-6">
              <Card>
                <p className="text-xs text-text-muted mb-1">총 추정 비용</p>
                <p className="text-2xl font-bold text-text">{won(t.total_cost_krw)}</p>
                <p className="text-xs text-text-muted mt-1">
                  ≈ ${(t.live_cost_usd + t.vod_cost_usd).toFixed(2)}
                </p>
              </Card>
              <Card>
                <p className="text-xs text-text-muted mb-1">실시간 방송 (생중계 자막)</p>
                <p className="text-xl font-bold text-error">{won(t.live_cost_krw)}</p>
                <p className="text-xs text-text-muted mt-1">{hours(t.live_minutes)} 분량</p>
              </Card>
              <Card>
                <p className="text-xs text-text-muted mb-1">AI 자막 생성 (VOD)</p>
                <p className="text-xl font-bold text-success">{won(t.vod_cost_krw)}</p>
                <p className="text-xs text-text-muted mt-1">{hours(t.vod_minutes)} 분량</p>
              </Card>
              <Card>
                <p className="text-xs text-text-muted mb-1">API 호출 수 (추정)</p>
                <p className="text-xl font-bold text-text">
                  {(t.live_api_calls_est + t.vod_api_calls_est).toLocaleString()}회
                </p>
                <p className="text-xs text-text-muted mt-1">
                  생중계 {t.live_api_calls_est.toLocaleString()} · AI 자막 {t.vod_api_calls_est.toLocaleString()}
                </p>
              </Card>
            </div>

            {/* 위원회별 테이블 */}
            <Card padding="none" className="overflow-x-auto">
              <table className="w-full text-sm" data-testid="usage-table">
                <thead>
                  <tr className="border-b border-border bg-surface-raised text-text-muted">
                    <th className="px-4 py-2.5 text-left font-medium">위원회</th>
                    <th className="px-3 py-2.5 text-right font-medium">회의 수</th>
                    <th className="px-3 py-2.5 text-right font-medium">생중계 시간</th>
                    <th className="px-3 py-2.5 text-right font-medium">생중계 비용</th>
                    <th className="px-3 py-2.5 text-right font-medium">AI 자막 시간</th>
                    <th className="px-3 py-2.5 text-right font-medium">AI 자막 비용</th>
                    <th className="px-4 py-2.5 text-right font-medium">합계</th>
                  </tr>
                </thead>
                <tbody>
                  {data.committees.map((r) => (
                    <tr key={r.committee} className="border-b border-border last:border-0 hover:bg-surface-raised/50">
                      <td className="px-4 py-2.5 font-medium text-text">{r.committee}</td>
                      <td className="px-3 py-2.5 text-right tabular-nums">{r.meetings}</td>
                      <td className="px-3 py-2.5 text-right tabular-nums text-text-secondary">
                        {r.live_minutes > 0 ? hours(r.live_minutes) : '—'}
                      </td>
                      <td className="px-3 py-2.5 text-right tabular-nums">
                        {r.live_cost_krw > 0 ? won(r.live_cost_krw) : '—'}
                      </td>
                      <td className="px-3 py-2.5 text-right tabular-nums text-text-secondary">
                        {r.vod_minutes > 0 ? hours(r.vod_minutes) : '—'}
                      </td>
                      <td className="px-3 py-2.5 text-right tabular-nums">
                        {r.vod_cost_krw > 0 ? won(r.vod_cost_krw) : '—'}
                      </td>
                      <td className="px-4 py-2.5 text-right tabular-nums font-semibold text-text">
                        {won(r.total_cost_krw)}
                      </td>
                    </tr>
                  ))}
                  {data.committees.length === 0 && (
                    <tr>
                      <td colSpan={7} className="px-4 py-8 text-center text-text-muted">
                        해당 기간에 집계할 사용량이 없습니다.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </Card>

            <p className="mt-3 text-xs text-text-muted">
              단가: 생중계 ${data.rates.live_per_hour_usd}/시간 (실시간 전사 + AI 교정), AI 자막 $
              {data.rates.vod_per_hour_usd}/시간 (VOD 배치 재전사). {data.note}
            </p>
          </>
        )}
      </div>
    </div>
  );
}

export default function AdminUsagePage() {
  return (
    <RoleGuard roles={['admin']}>
      <UsageDashboard />
    </RoleGuard>
  );
}
