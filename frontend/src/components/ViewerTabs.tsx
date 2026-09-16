'use client';

/**
 * ViewerTabs — 회의 시청 화면(라이브/VOD)의 보조 패널 전환 탭
 *
 * 영상 아래에 자막·검색결과·요구자료를 세로로 이어 붙이면 모바일에서
 * "지금 발언"이 화면 한참 아래로 밀린다. 셋을 동급의 탭으로 두어
 * 영상 바로 밑이 항상 자막이 되게 한다(기본 선택은 자막).
 */

export interface ViewerTabItem {
  key: string;
  label: string;
  /** 우측 개수 배지 (0이면 배지 숨김, undefined면 배지 없음) */
  count?: number;
  /** 미처리 항목이 있을 때 배지를 주의색으로 (요구자료 미확인 등) */
  alert?: boolean;
}

export interface ViewerTabsProps {
  tabs: ViewerTabItem[];
  active: string;
  onChange: (key: string) => void;
  /**
   * 탭 줄 오른쪽 끝에 붙는 컨트롤 (따라가기 · 글자 크기 · 확대 …).
   *
   * 2026-08-25 개선안 2a·2e: 자막 패널이 갖고 있던 헤더 한 줄을 없애고 그 컨트롤을
   * 여기로 올렸다. 모바일에서 줄 하나는 자막 3~4줄과 맞먹는다.
   */
  rightSlot?: React.ReactNode;
  className?: string;
}

export default function ViewerTabs({
  tabs,
  active,
  onChange,
  rightSlot,
  className = '',
}: ViewerTabsProps) {
  return (
    <div
      data-testid="viewer-tabs"
      className={`flex shrink-0 items-stretch bg-surface ${className}`.trim()}
    >
      <div role="tablist" aria-label="자막·검색·요구자료 전환" className="flex min-w-0 flex-1 items-stretch overflow-x-auto">
      {tabs.map((tab) => {
        const isActive = tab.key === active;
        return (
          <button
            key={tab.key}
            type="button"
            role="tab"
            aria-selected={isActive}
            onClick={() => onChange(tab.key)}
            data-testid={`viewer-tab-${tab.key}`}
            /* 모바일은 py-1.5 — 시청 화면에서 한 줄 두께는 곧 자막 줄 수다 */
            className={`flex flex-1 items-center justify-center gap-1.5 whitespace-nowrap px-3 py-1.5 text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary sm:py-2.5 ${
              isActive
                ? 'border-b-[3px] border-brand bg-primary-5 font-bold text-brand'
                : 'border-b-[3px] border-transparent font-medium text-text-secondary hover:bg-surface-raised'
            }`}
          >
            {tab.label}
            {tab.count != null && tab.count > 0 && (
              <span
                className={`inline-flex h-5 min-w-[1.25rem] items-center justify-center rounded-full px-1.5 text-xs font-semibold ${
                  tab.alert
                    ? 'bg-error/10 text-error'
                    : isActive
                      ? 'bg-brand/10 text-brand'
                      : 'bg-surface-raised text-text-muted'
                }`}
              >
                {tab.count}
              </span>
            )}
          </button>
        );
      })}
      </div>
      {rightSlot && (
        <div className="flex shrink-0 items-center gap-0.5 border-l border-border px-1.5">
          {rightSlot}
        </div>
      )}
    </div>
  );
}
