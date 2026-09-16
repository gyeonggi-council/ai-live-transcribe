/**
 * 운영자 콘솔 전용 인라인 SVG 아이콘
 */

export type OpIconName =
  | 'pause' | 'rewind' | 'send' | 'warn' | 'check' | 'plus' | 'x'
  | 'signal' | 'cpu' | 'refresh' | 'edit' | 'globe' | 'youtube' | 'building' | 'monitor';

interface Props {
  name: OpIconName;
  size?: number;
  color?: string;
  stroke?: number;
}

export function OpIcon({ name, size = 18, color = 'currentColor', stroke = 1.8 }: Props) {
  const p = {
    width: size,
    height: size,
    viewBox: '0 0 24 24',
    fill: 'none',
    stroke: color,
    strokeWidth: stroke,
    strokeLinecap: 'round' as const,
    strokeLinejoin: 'round' as const,
  };
  switch (name) {
    case 'pause':
      return <svg {...p}><rect x="6" y="5" width="4" height="14" fill={color}/><rect x="14" y="5" width="4" height="14" fill={color}/></svg>;
    case 'rewind':
      return <svg {...p}><path d="M11 19 2 12l9-7v4c6 0 10 3 11 10-2-4-6-6-11-6z"/></svg>;
    case 'send':
      return <svg {...p}><path d="M4 20 20 12 4 4l4 8z"/><path d="M8 12h12"/></svg>;
    case 'warn':
      return <svg {...p}><path d="M12 3 2 20h20z"/><path d="M12 10v5M12 18v.5"/></svg>;
    case 'check':
      return <svg {...p}><path d="m5 12 5 5L20 7"/></svg>;
    case 'plus':
      return <svg {...p}><path d="M12 5v14M5 12h14"/></svg>;
    case 'x':
      return <svg {...p}><path d="M6 6l12 12M18 6 6 18"/></svg>;
    case 'signal':
      return <svg {...p}><path d="M4 20v-4M9 20v-8M14 20v-12M19 20v-16"/></svg>;
    case 'cpu':
      return <svg {...p}><rect x="4" y="4" width="16" height="16" rx="2"/><rect x="8" y="8" width="8" height="8"/></svg>;
    case 'refresh':
      return <svg {...p}><path d="M3 12a9 9 0 0 1 15-6.7L21 8M21 3v5h-5"/></svg>;
    case 'edit':
      return <svg {...p}><path d="M4 20h4l10-10-4-4L4 16zM14 6l4 4"/></svg>;
    case 'globe':
      return <svg {...p}><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/></svg>;
    case 'youtube':
      return <svg viewBox="0 0 24 24" width={size} height={size}><path fill={color} d="M23 7s-.2-1.6-.9-2.3c-.8-.9-1.8-1-2.2-1C16.7 3.5 12 3.5 12 3.5s-4.7 0-7.9.2c-.4 0-1.4.1-2.2 1C1.2 5.4 1 7 1 7S.8 8.9.8 10.8v1.8c0 1.9.2 3.8.2 3.8s.2 1.6.9 2.3c.8.9 1.9.9 2.4 1 1.7.2 7.7.2 7.7.2s4.7 0 7.9-.2c.4 0 1.4-.1 2.2-1 .7-.7.9-2.3.9-2.3s.2-1.9.2-3.8v-1.8C23.2 8.9 23 7 23 7zm-13.4 7.7V8l6 3.3-6 3.4z"/></svg>;
    case 'building':
      return <svg {...p}><rect x="4" y="4" width="16" height="16"/><path d="M9 8h2M13 8h2M9 12h2M13 12h2M9 16h2M13 16h2"/></svg>;
    case 'monitor':
      return <svg {...p}><rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/></svg>;
    default:
      return null;
  }
}
