'use client';

import React from 'react';

import Image from 'next/image';
import Link from 'next/link';
import { usePathname, useSearchParams } from 'next/navigation';

/**
 * 모바일 상단 의회 마크 (2026-08-25 사용자 요청)
 *
 * 휴대폰에서는 사이드바가 서랍으로 숨어 있어 **어느 기관의 화면인지 알 수 없었다.**
 * 플랫폼 공통 상단바를 걷어낸 뒤로는 그 자리가 빈 흰 띠로 남기도 했다.
 * 마크와 기관명만 한 줄로 두고, 누르면 대시보드로 간다.
 *
 * ★ **회의를 '보는' 화면에는 붙이지 않는다** — 서비스 CLAUDE.md 의 "모바일에서
 *   자막 영역은 남은 전부다" 규칙. 띠 하나가 자막 3~4줄이고, 3시간짜리 회의에서
 *   자막이 150px 만 남아 "보기가 어렵다"는 신고를 받은 적이 있다. 그 화면들은
 *   자체 머리줄에 회의 제목이 있어 소속도 드러난다.
 *
 *   판단 기준은 **경로가 아니라 그 화면이 지금 무엇을 하고 있는가**다.
 *   `/live` 는 한 경로가 두 화면이다 — `?channel=` 이 없으면 채널을 고르는 **목록**,
 *   있으면 방송을 보는 **시청 화면**. 경로만 보고 `/live` 를 통째로 뺐더니 목록
 *   화면에서도 마크가 사라졌다(2026-08-25 사용자 지적).
 */
const VIEWING_PATH_PREFIXES = ['/vod/'];

export default function MobileBrandBar() {
  const pathname = usePathname() ?? '';
  const searchParams = useSearchParams();

  const isViewing =
    VIEWING_PATH_PREFIXES.some((p) => pathname.startsWith(p)) ||
    (pathname.startsWith('/live') && !!searchParams.get('channel'));

  if (isViewing) return null;

  return (
    <div className="flex h-12 shrink-0 items-center border-b border-border bg-surface px-4 lg:hidden">
      <Link href="/" className="flex items-center gap-2" aria-label="경기도의회 영상회의록 통합플랫폼 홈">
        <Image
          src="https://www.ggc.go.kr/design/theme/asa/images/assembly_mark.png"
          alt="경기도의회"
          width={28}
          height={28}
          className="h-7 w-7 shrink-0 object-contain"
          unoptimized
        />
        <span className="flex flex-col leading-tight">
          <span className="text-[13px] font-semibold text-text">경기도의회</span>
          <span className="text-[10.5px] text-text-muted">영상회의록 통합플랫폼</span>
        </span>
      </Link>
    </div>
  );
}
