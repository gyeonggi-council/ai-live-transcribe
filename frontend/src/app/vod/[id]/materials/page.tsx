'use client';

/**
 * /vod/[id]/materials — 요구자료 감지 전체 화면 페이지
 *
 * VOD 뷰어의 요구자료 패널은 영상 아래 공간이 좁아 목록이 많으면 확인이 어렵다.
 * 이 페이지는 같은 목록을 새 창에서 높이 제한·인용문 줄임 없이 전부 보여준다.
 * (사무처가 KMS 등록 작업 중 창을 나란히 두고 쓰는 시나리오)
 */

import { useEffect, useState } from 'react';

import Link from 'next/link';

import MaterialRequestPanel from '@/components/MaterialRequestPanel';
import { useBreadcrumb } from '@/contexts/BreadcrumbContext';
import { useMaterialRequests } from '@/hooks/useMaterialRequests';
import { apiClient } from '@/lib/api';
import type { MeetingType } from '@/types';

interface MaterialsPageProps {
  params: { id: string };
}

export default function MaterialsPage({ params }: MaterialsPageProps) {
  const { id } = params;
  const { setTitle } = useBreadcrumb();
  const [meeting, setMeeting] = useState<MeetingType | null>(null);
  const materialRequests = useMaterialRequests(id);

  useEffect(() => {
    apiClient<MeetingType>(`/api/meetings/${id}`)
      .then((m) => {
        setMeeting(m);
        setTitle(m.title);
      })
      .catch(() => {
        // 회의 정보 조회 실패해도 목록 자체는 표시
      });
  }, [id, setTitle]);

  const counts = {
    detected: materialRequests.requests.filter((r) => r.status === 'detected').length,
    confirmed: materialRequests.requests.filter((r) => r.status === 'confirmed').length,
    registered: materialRequests.requests.filter((r) => r.status === 'registered').length,
    dismissed: materialRequests.requests.filter((r) => r.status === 'dismissed').length,
  };

  return (
    <div data-testid="materials-page" className="p-4 sm:p-6">
      <div className="max-w-4xl mx-auto">
        {/* 헤더: 회의 제목 + 상태 요약 + 뷰어로 돌아가기 */}
        <div className="flex flex-wrap items-start justify-between gap-2 mb-4">
          <div className="min-w-0">
            <h1 className="text-lg font-bold text-gray-900 break-keep">
              요구자료 목록
            </h1>
            <p className="text-sm text-gray-500 mt-0.5 break-keep">
              {meeting ? meeting.title : '회의 정보 불러오는 중...'}
            </p>
          </div>
          <Link
            href={`/vod/${id}`}
            className="px-3 py-1.5 rounded-md border border-border text-sm text-text-secondary hover:bg-surface-raised whitespace-nowrap shrink-0 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
            data-testid="back-to-viewer"
          >
            ← 영상 뷰어
          </Link>
        </div>

        {/* 상태 요약 칩 */}
        <div className="flex flex-wrap items-center gap-2 mb-3 text-xs">
          <span className="px-2 py-1 rounded-full bg-error/10 text-error font-medium">
            미확인 {counts.detected}
          </span>
          <span className="px-2 py-1 rounded-full bg-primary-5 text-primary-dark font-medium">
            확인됨 {counts.confirmed}
          </span>
          <span className="px-2 py-1 rounded-full bg-success/10 text-success font-medium">
            KMS 등록됨 {counts.registered}
          </span>
          {counts.dismissed > 0 && (
            <span className="px-2 py-1 rounded-full bg-gray-100 text-gray-500">
              무시됨 {counts.dismissed}
            </span>
          )}
        </div>

        {/* 전체 목록 — 높이 제한 없음, 인용문 전문 표시, 페이지 스크롤 */}
        <MaterialRequestPanel
          requests={materialRequests.requests}
          isLoading={materialRequests.isLoading}
          onUpdate={materialRequests.update}
          onScan={materialRequests.scan}
          onAddManual={materialRequests.addManual}
          fullHeight
        />
      </div>
    </div>
  );
}
