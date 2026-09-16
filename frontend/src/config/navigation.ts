import { AI_ROLES } from '@/lib/aiAccess';

export const SIDEBAR_WIDTH = 256;
export const SIDEBAR_COLLAPSED_WIDTH = 64;
export const HEADER_HEIGHT = 48;

export interface NavSubItem {
  id: string;
  label: string;
  href?: string;
  /** 회의 컨텍스트 필요 여부 (true면 /vod/[id]가 있어야 활성) */
  requiresMeeting?: boolean;
  /** 회의 ID 기반 동적 경로 생성 함수 */
  getHref?: (meetingId: string) => string;
}

export interface NavModule {
  id: string;
  label: string;
  icon: string; // SVG path or icon identifier
  items: NavSubItem[];
  /** 회의 컨텍스트 필요 여부 */
  requiresMeeting?: boolean;
  /** 메뉴 구분선 위에 표시 */
  dividerBefore?: boolean;
  /** 접근 허용 역할 목록 (없으면 모두 접근 가능) */
  roles?: string[];
}

export const NAV_MODULES: NavModule[] = [
  {
    id: 'meeting-mgmt',
    label: '회의관리',
    icon: 'calendar',
    // roles 없음 → 모두 접근 가능
    items: [
      { id: 'dashboard', label: '대시보드', href: '/' },
      { id: 'live', label: '실시간 방송', href: '/live' },
      { id: 'vod-list', label: '회의 목록', href: '/vod' },
    ],
  },
  {
    id: 'transcript',
    label: '회의록작성',
    icon: 'document-text',
    requiresMeeting: true,
    roles: ['stenographer', 'admin'],
    items: [
      {
        id: 'vod-detail',
        label: 'VOD 상세·STT',
        requiresMeeting: true,
        getHref: (meetingId) => `/vod/${meetingId}`,
      },
      {
        id: 'minutes',
        label: '회의록 작성',
        requiresMeeting: true,
        getHref: (meetingId) => `/vod/${meetingId}/minutes`,
      },
      {
        id: 'stenography',
        label: '속기록 관리',
        requiresMeeting: true,
        getHref: (meetingId) => `/vod/${meetingId}/stenography`,
      },
    ],
  },
  {
    id: 'speaker',
    label: '화자관리',
    icon: 'user-group',
    requiresMeeting: true,
    roles: ['stenographer', 'admin'],
    items: [
      {
        id: 'speaker-edit',
        label: '화자 식별',
        requiresMeeting: true,
        getHref: (meetingId) => `/vod/${meetingId}/speaker`,
      },
    ],
  },
  {
    id: 'clips',
    label: '발언영상',
    icon: 'film',
    // 2026-09 웹 워크벤치 — 회의를 고르지 않아도 들어가서 목록에서 고른다
    // council_guest = 로그인하지 않은 의회망 방문자(2026-09-11 담당자 요청 — 의회 안에서는 로그인 없이)
    roles: ['staff', 'committee_staff', 'meeting_manager', 'stenographer', 'admin', 'council_guest'],
    items: [
      { id: 'clips-workbench', label: '발언영상 추출', href: '/clips' },
      { id: 'clips-jobs', label: '추출 기록 (7일)', href: '/clips/jobs' },
    ],
  },
  {
    id: 'verification',
    label: '대조관리',
    icon: 'check-badge',
    requiresMeeting: true,
    roles: ['stenographer', 'admin'],
    items: [
      {
        id: 'verify',
        label: '자막 검증',
        requiresMeeting: true,
        getHref: (meetingId) => `/vod/${meetingId}/verify`,
      },
    ],
  },
  {
    id: 'proofreading',
    label: '교정/편집관리',
    icon: 'pencil-square',
    requiresMeeting: true,
    roles: ['stenographer', 'admin'],
    items: [
      {
        id: 'edit',
        label: '자막 교정',
        requiresMeeting: true,
        getHref: (meetingId) => `/vod/${meetingId}/edit`,
      },
    ],
  },
  {
    id: 'stenography-mgmt',
    label: '속기관리',
    icon: 'document-duplicate',
    dividerBefore: true,
    roles: ['stenographer', 'admin'],
    items: [
      { id: 'steno-dashboard', label: '속기록 대시보드', href: '/stenography' },
    ],
  },
  {
    id: 'bills',
    label: '의안관리',
    icon: 'clipboard-document-list',
    dividerBefore: true,
    roles: ['committee_staff', 'meeting_manager', 'admin'],
    items: [
      { id: 'bills-list', label: '의안 목록', href: '/bills' },
    ],
  },
  {
    id: 'ai-assistant',
    label: 'AI 어시스턴트',
    icon: 'sparkles',
    // staff(QR 의원) 포함 — 정본은 lib/aiAccess.AI_ROLES(2026-09-14)
    roles: [...AI_ROLES],
    items: [
      { id: 'ai-chat', label: 'AI 질의응답', href: '/ai' },
    ],
  },
  {
    id: 'search',
    label: '통합검색',
    icon: 'magnifying-glass',
    // roles 없음 → 모두 접근 가능
    items: [
      { id: 'search-page', label: '검색', href: '/search' },
    ],
  },
  {
    id: 'system',
    label: '시스템관리',
    icon: 'cog-6-tooth',
    roles: ['admin'],
    items: [
      { id: 'admin', label: '시스템 상태', href: '/admin' },
      { id: 'admin-users', label: '사용자 관리', href: '/admin/users' },
      { id: 'admin-dictionary', label: '용어사전', href: '/admin/dictionary' },
      { id: 'admin-usage', label: 'API 사용량·비용', href: '/admin/usage' },
      // 접속 통계는 누구나 볼 수 있다(사이드바 하단 방문자 수를 눌러도 간다) — 관리자 메뉴에도 둔다
      { id: 'admin-visits', label: '접속 통계', href: '/visits' },
      { id: 'admin-tools', label: '영상추출기 배포', href: '/admin/tools' },
    ],
  },
];

/**
 * 도구 — 외부 링크·다운로드·공지.
 *
 * 업무 메뉴(회의관리·AI·검색·시스템관리)와 성격이 달라 사이드바 **맨 아래 별도 묶음**으로
 * 내린다. 셋 다 "가끔 한 번 여는 것"이라 업무 동선 위에 섞여 있으면 회의관리가
 * 6줄로 불어난다(2026-08-25 개선안 2c).
 */
export interface ToolLink {
  id: string;
  label: string;
  href: string;
  /** true 면 새 탭 — http(s) 외부 주소 */
  external?: boolean;
}

export const TOOL_LINKS: ToolLink[] = [
  {
    id: 'kms-link',
    label: '의회 영상 페이지',
    href: 'https://kms.ggc.go.kr/caster/content/vms/VodLatelyList.do?confcode=N',
    external: true,
  },
  // 2026-09-08 설치형 추출기 재개(사용자 결정) — 웹 워크벤치(/clips)와 병행
  { id: 'extractor-download', label: '영상추출기 다운로드', href: '/tools/extractor' },
  { id: 'updates', label: '업데이트 소식', href: '/updates' },
];

/**
 * 숨김 모듈 (비핵심 — 나중에 더 안전하게 구현되면 재활성화).
 * 핵심 2기능(실시간 자막 + VOD AI 자막) + 검색/AI/시스템만 노출한다.
 * 재활성화하려면 해당 id를 이 Set에서 빼면 즉시 복구된다.
 */
export const HIDDEN_MODULE_IDS = new Set<string>([
  'transcript', // 회의록작성 (속기록 관리 포함)
  'speaker', // 화자관리
  'verification', // 대조관리(자막 검증)
  'proofreading', // 교정/편집관리
  'stenography-mgmt', // 속기관리
  'bills', // 의안관리
]);

/**
 * pathname → 브레드크럼 정적 매핑
 *
 * 회의 ID 가 포함된 동적 경로(/vod/[id]/clips 등)는 정적 키로 매칭할 수 없으므로
 * Breadcrumbs 컴포넌트(components/layout/Breadcrumbs.tsx)의 동적 분기에서 처리한다.
 */
export const BREADCRUMB_MAP: Record<string, string[]> = {
  '/': ['회의관리', '대시보드'],
  '/live': ['회의관리', '실시간 방송'],
  '/vod': ['회의관리', '회의 목록'],
  '/updates': ['도구', '업데이트 소식'],
  '/bills': ['의안관리', '의안 목록'],
  '/ai': ['AI 어시스턴트', 'AI 질의응답'],
  '/search': ['통합검색', '검색'],
  '/admin': ['시스템관리', '시스템 상태'],
  '/admin/users': ['시스템관리', '사용자 관리'],
  '/admin/dictionary': ['시스템관리', '용어사전'],
  '/admin/usage': ['시스템관리', 'API 사용량·비용'],
  '/admin/tools': ['시스템관리', '영상추출기 배포'],
  '/visits': ['접속 통계'],
  '/tools/extractor': ['도구', '영상추출기 다운로드'],
  '/clips': ['발언영상', '발언영상 추출'],
  '/clips/jobs': ['발언영상', '추출 기록'],
  '/stenography': ['속기관리', '속기록 대시보드'],
};

/**
 * URL 경로에서 회의 ID를 추출 (/vod/[id], /vod/[id]/edit, /vod/[id]/verify)
 */
export function extractMeetingIdFromPath(pathname: string): string | null {
  const match = pathname.match(/^\/vod\/([^/]+)/);
  return match?.[1] ?? null;
}
