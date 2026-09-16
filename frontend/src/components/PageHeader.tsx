/**
 * PageHeader — 공공기관 톤의 페이지 상단 제목 블록
 *
 * 2026-08-25 개선안(2d·2f·2h·2i) 반영:
 * - 제목 줄에 이어 붙이던 **날짜·설명을 두 줄로 분리**한다. 제목 옆에는 그 화면을
 *   특정하는 짧은 수치(`meta` — 회기·기간·건수)만 남기고, 문장은 아래 줄로 내린다.
 *   한 줄에 다 붙이면 화면 폭에 따라 접히는 자리가 매번 달라 제목이 흔들려 보였다.
 * - 전폭 금색 그라데이션 → **44px 짧은 규칙선**. 액센트는 '여기가 제목이다'를 말하는
 *   표식이지 화면을 가로지르는 장식이 아니다.
 * - 전역 컨트롤(알림/검색)은 PlatformLayout이 우측 상단에 띄우므로 우측 여백을 확보한다.
 */

import React from 'react';

export interface PageHeaderProps {
  /** 페이지 제목 (H1) */
  title: string;
  /** 제목 아래 부제/설명 (선택) — **문장은 여기** */
  description?: string;
  /** 제목 옆 짧은 수치 (선택) — 회기·기간·건수처럼 세는 값 */
  meta?: React.ReactNode;
  /** 영문/라벨 태그 (선택) — 제목 **위**에 작게 표시 */
  eyebrow?: string;
  /** 우측 액션 슬롯 (버튼/검색 등) */
  actions?: React.ReactNode;
  /** 하단 Gold 액센트 라인 숨김 (default: false) */
  hideAccent?: boolean;
  /** 바깥 여백 클래스 교체 (기본 mb-6) */
  className?: string;
}

export default function PageHeader({
  title,
  description,
  meta,
  eyebrow,
  actions,
  hideAccent = false,
  className = 'mb-6',
}: PageHeaderProps) {
  return (
    // 우측 여백(pr-*)은 PlatformLayout이 우측 상단에 띄우는 전역 컨트롤(알림/검색)과
    // 페이지 액션·제목이 겹치지 않도록 확보한다.
    <header className={`${className} pr-12 sm:pr-48`.trim()}>
      <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
        <div className="min-w-0">
          {eyebrow && (
            <div className="mb-1 text-[11px] font-bold uppercase tracking-[0.14em] text-text-dim">
              {eyebrow}
            </div>
          )}

          {/* 1줄: 제목 + 세는 값 */}
          <div className="flex min-w-0 flex-wrap items-baseline gap-x-2.5 gap-y-1">
            <h1 className="text-2xl font-bold tracking-heading text-text">{title}</h1>
            {meta && <span className="text-sm tabular-nums text-text-muted">{meta}</span>}
          </div>

          {/* 2줄: 설명 문장 */}
          {description && <p className="mt-1 text-sm text-text-muted">{description}</p>}

          {!hideAccent && <div className="mt-2.5 h-[2px] w-11 bg-accent" />}
        </div>

        {actions && <div className="flex flex-shrink-0 items-center gap-2">{actions}</div>}
      </div>
    </header>
  );
}
