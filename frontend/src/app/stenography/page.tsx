'use client';

/**
 * 속기사 대시보드 페이지
 *
 * @TASK P11C-T8 - 속기사 대시보드
 * @SPEC docs/planning/02-trd.md#속기록
 *
 * 3개 탭: 대기 (draft) | 진행중 (submitted) | 완료 (approved)
 * 각 탭: 회의 제목, 속기사명, 등록일, 상태 배지
 */

import React, { useCallback, useEffect, useState } from 'react';

import Link from 'next/link';

import PageHeader from '../../components/PageHeader';
import { useBreadcrumb } from '../../contexts/BreadcrumbContext';
import { getAllStenographyRecords } from '../../lib/api';

import type { StenographyDashboardItem } from '../../types';

type TabStatus = 'draft' | 'submitted' | 'approved';

const TAB_CONFIG: { key: TabStatus; label: string; apiFilter: string }[] = [
  { key: 'draft', label: '대기', apiFilter: 'draft' },
  { key: 'submitted', label: '진행중', apiFilter: 'submitted' },
  { key: 'approved', label: '완료', apiFilter: 'approved' },
];

function StatusBadge({ status }: { status: TabStatus }) {
  const config = {
    draft: { label: '대기', color: 'bg-warning-bg/20 text-warning border-warning-bg/40' },
    submitted: { label: '진행중', color: 'bg-primary-10 text-primary-dark border-primary-20' },
    approved: { label: '완료', color: 'bg-success/10 text-success border-success/30' },
  };
  const { label, color } = config[status];
  return (
    <span className={`px-2 py-0.5 text-xs font-medium rounded border ${color}`}>
      {label}
    </span>
  );
}

export default function StenographyDashboardPage() {
  const { setTitle } = useBreadcrumb();
  const [activeTab, setActiveTab] = useState<TabStatus>('draft');
  const [records, setRecords] = useState<StenographyDashboardItem[]>([]);
  const [_total, setTotal] = useState(0);
  const [isLoading, setIsLoading] = useState(true);

  // Tab counts
  const [counts, setCounts] = useState({ draft: 0, submitted: 0, approved: 0 });

  useEffect(() => {
    setTitle('속기록 대시보드');
  }, [setTitle]);

  const loadRecords = useCallback(async (status: TabStatus) => {
    setIsLoading(true);
    try {
      const result = await getAllStenographyRecords(status, 50, 0);
      setRecords(result.items);
      setTotal(result.total);
      setCounts((prev) => ({ ...prev, [status]: result.total }));
    } catch {
      setRecords([]);
      setTotal(0);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadRecords(activeTab);
  }, [activeTab, loadRecords]);

  // Load counts for all tabs on mount
  useEffect(() => {
    async function loadCounts() {
      for (const tab of TAB_CONFIG) {
        try {
          const result = await getAllStenographyRecords(tab.apiFilter, 1, 0);
          setCounts((prev) => ({ ...prev, [tab.key]: result.total }));
        } catch {
          // ignore
        }
      }
    }
    loadCounts();
  }, []);

  const handleTabChange = (tab: TabStatus) => {
    setActiveTab(tab);
  };

  return (
    <div className="flex flex-col h-full" data-testid="stenography-dashboard">
      {/* Header */}
      <div className="px-6 pt-6">
        <PageHeader
          eyebrow="STENOGRAPHY · 속기록"
          title="속기록 대시보드"
          description="속기록 작업 현황을 대기·진행중·완료로 관리합니다."
        />
      </div>

      {/* Stats cards */}
      <div className="px-6 py-4 grid grid-cols-3 gap-4">
        {TAB_CONFIG.map((tab) => (
          <button
            key={tab.key}
            onClick={() => handleTabChange(tab.key)}
            className={`p-4 rounded-lg border text-left transition-colors ${
              activeTab === tab.key
                ? 'border-primary bg-primary-5'
                : 'border-border bg-surface hover:border-gray-400'
            }`}
          >
            <p className="text-sm text-text-muted">{tab.label}</p>
            <p className="text-2xl font-bold text-text mt-1">{counts[tab.key]}</p>
          </button>
        ))}
      </div>

      {/* Tab buttons */}
      <div className="px-6 border-b border-border flex gap-1">
        {TAB_CONFIG.map((tab) => (
          <button
            key={tab.key}
            role="button"
            onClick={() => handleTabChange(tab.key)}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              activeTab === tab.key
                ? 'border-primary text-primary'
                : 'border-transparent text-text-muted hover:text-text-secondary'
            }`}
          >
            {tab.label} ({counts[tab.key]})
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-6 py-4">
        {isLoading ? (
          <div className="flex items-center justify-center py-12">
            <div className="w-8 h-8 border-4 border-border border-t-primary rounded-full animate-spin" />
          </div>
        ) : records.length === 0 ? (
          <div className="text-center py-12 text-text-muted">
            등록된 속기록이 없습니다.
          </div>
        ) : (
          <div className="bg-surface border border-border rounded-lg divide-y divide-border">
            {records.map((record) => (
              <div key={record.id} className="p-4 hover:bg-surface-raised transition-colors">
                <div className="flex items-start justify-between">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      <span className="text-sm font-medium text-text truncate">
                        {record.meetings?.title || `회의 ${record.meeting_id.slice(0, 8)}`}
                      </span>
                      <StatusBadge status={record.status} />
                    </div>
                    <div className="flex gap-3 text-xs text-text-muted">
                      <span>속기사: {record.stenographer_name}</span>
                      <span>등록: {new Date(record.created_at).toLocaleDateString()}</span>
                      {record.meetings?.committee && (
                        <span>위원회: {record.meetings.committee}</span>
                      )}
                    </div>
                  </div>
                  {record.status === 'draft' && (
                    <Link
                      href={`/vod/${record.meeting_id}/stenography`}
                      className="px-3 py-1.5 text-xs font-medium bg-primary text-white rounded hover:bg-primary-dark transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
                    >
                      편집
                    </Link>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
