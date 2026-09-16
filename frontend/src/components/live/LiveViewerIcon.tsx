/**
 * LiveViewer 전용 인라인 SVG 아이콘 세트
 *
 * 디자인 시안(Viewer.jsx)의 Icon 컴포넌트를 Next.js/TS로 포팅.
 * lucide-react 대신 인라인 SVG를 쓰는 이유는 번들 사이즈 최소화 +
 * 시안과의 시각적 일치(stroke 두께, viewBox)를 보장하기 위함.
 */

export type IconName =
  | 'search' | 'bookmark' | 'star' | 'volume' | 'cc' | 'expand'
  | 'chevron-right' | 'globe' | 'type' | 'clock' | 'mic' | 'file' | 'download';

interface IconProps {
  name: IconName;
  size?: number;
  color?: string;
  stroke?: number;
  className?: string;
}

export function LiveIcon({
  name,
  size = 20,
  color = 'currentColor',
  stroke = 1.75,
  className,
}: IconProps) {
  const common = {
    width: size,
    height: size,
    viewBox: '0 0 24 24',
    fill: 'none',
    stroke: color,
    strokeWidth: stroke,
    strokeLinecap: 'round' as const,
    strokeLinejoin: 'round' as const,
    className,
  };
  switch (name) {
    case 'search':
      return <svg {...common}><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>;
    case 'bookmark':
      return <svg {...common}><path d="M6 4h12v17l-6-4-6 4z"/></svg>;
    case 'star':
      return <svg {...common}><path d="m12 3 2.7 5.7 6.3.9-4.5 4.4 1 6.2L12 17.3 6.5 20.2l1-6.2L3 9.6l6.3-.9z"/></svg>;
    case 'volume':
      return <svg {...common}><path d="M5 9v6h4l5 4V5L9 9zM16 9a4 4 0 0 1 0 6M19 6a8 8 0 0 1 0 12"/></svg>;
    case 'cc':
      return <svg {...common}><rect x="3" y="5" width="18" height="14" rx="2"/><path d="M9 10.5a2 2 0 1 0 0 3M16 10.5a2 2 0 1 0 0 3"/></svg>;
    case 'expand':
      return <svg {...common}><path d="M4 10V4h6M20 10V4h-6M4 14v6h6M20 14v6h-6"/></svg>;
    case 'chevron-right':
      return <svg {...common}><path d="m9 6 6 6-6 6"/></svg>;
    case 'globe':
      return <svg {...common}><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/></svg>;
    case 'type':
      return <svg {...common}><path d="M4 7V5h16v2M9 19h6M12 5v14"/></svg>;
    case 'clock':
      return <svg {...common}><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>;
    case 'mic':
      return <svg {...common}><rect x="9" y="3" width="6" height="12" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/></svg>;
    case 'file':
      return <svg {...common}><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8zM14 3v5h5"/></svg>;
    case 'download':
      return <svg {...common}><path d="M12 4v12m0 0-4-4m4 4 4-4M5 20h14"/></svg>;
    default:
      return null;
  }
}
