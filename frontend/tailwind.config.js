/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './src/pages/**/*.{js,ts,jsx,tsx,mdx}',
    './src/components/**/*.{js,ts,jsx,tsx,mdx}',
    './src/app/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      colors: {
        // === GAC (Gyeonggi Assembly Council) Design System ===
        // 공공기관 브랜드 팔레트 — 디자인 번들 2026-04-20 기준
        gac: {
          'dark-blue': '#3C5D89',
          blue: '#0099CC',
          gold: '#AD8B3A',
          gray: '#7D7D7D',
          silver: '#999999',
          'navy-900': '#1E3358',
          'navy-800': '#2A4670',
          'navy-50': '#EEF3FA',
          'blue-50': '#E6F4FB',
          'blue-100': '#CDE9F6',
        },
        // ink.* — KRDS 회색 램프로 정렬 (gray.* 와 동일 값)
        ink: {
          900: '#1e2124',
          800: '#33363d',
          700: '#464c53',
          600: '#58616a',
          500: '#6d7882',
          400: '#8a949e',
          300: '#b1b8be',
          200: '#cdd1d5',
          100: '#e6e8ea',
          50: '#f4f5f6',
        },
        // Party colors (의원 소속 정당 표시용) — 유지
        party: {
          dem: '#0047A0',     // 더불어민주당
          pp: '#E61E2B',      // 국민의힘
          speaker: '#3C5D89', // 의장단
        },
        // Semantic 별칭 (KRDS 시맨틱으로 값 교체)
        'live-red': '#de3412',
        'warn-amber': '#9e6a00',
        'ok-green': '#228738',
        // === Brand semantic tokens — 경기도의회 네이비로 수렴 ===
        // 2026-08-22: KRDS 기본 파랑 #256ef4 는 계약 v1.0 이 **폐기한 값**이다.
        // 값의 정본은 design/ggc-tokens.css 이고 여기는 그것을 Tailwind 이름에
        // 잇는 자리다. **램프 전체를 함께 옮긴다** — DEFAULT 만 바꾸고 hover/active 를
        // 두고 가면 마우스를 올리는 순간 폐기값 파랑이 드러난다(실제로 그 상태였다).
        brand: {
          DEFAULT: '#3C5D93',  // --ggc-primary
          light: '#345080',    // hover  = --ggc-primary-dark
          dark: '#2E4A78',     // active = --ggc-primary-deep
          border: 'rgba(60, 93, 147, 0.3)',
        },
        // Surface & Background (LIGHT) — KRDS gray 램프 기반
        surface: {
          DEFAULT: '#ffffff',   // page background
          deep: '#ffffff',      // deepest / button bg
          raised: '#f4f5f6',    // slightly raised (gray-5)
          overlay: '#e6e8ea',   // card / panel bg (gray-10)
        },
        // Border Hierarchy — KRDS gray 램프 기반
        border: {
          DEFAULT: '#e6e8ea',   // standard (gray-10)
          subtle: '#f4f5f6',    // barely visible (gray-5)
          strong: '#cdd1d5',    // prominent (gray-20)
          light: '#e6e8ea',     // secondary
          accent: '#8a949e',    // tertiary (gray-40)
        },
        // Text — KRDS gray 램프 기반
        text: {
          DEFAULT: '#1e2124',   // primary (gray-90)
          secondary: '#464c53', // secondary (gray-70)
          muted: '#6d7882',     // muted (gray-50)
          dim: '#8a949e',       // very dim (gray-40)
        },
        // Primary — 경기도의회 네이비 램프 (정본 design/ggc-tokens.css)
        // 5·10 은 정본의 tint 두 단계, 40·60·70 은 hover/active/최심도다.
        // 중간 단계(20·30)는 정본에 없어 두 tint 사이를 잇는 파생값이며,
        // **새 색이 아니라 같은 색상각의 명도 변형**이다.
        primary: {
          DEFAULT: '#3C5D93',  // --ggc-primary
          light: '#345080',    // --ggc-primary-dark
          dark: '#2E4A78',     // --ggc-primary-deep
          5: '#eef3fa',        // --ggc-primary-light
          10: '#dbe6f5',       // --ggc-primary-light-strong
          20: '#c3d3ea',
          30: '#9db4d5',
          40: '#345080',
          60: '#2E4A78',
          70: '#24395f',
        },
        accent: {
          DEFAULT: '#AD8B3A',  // GAC Gold (의회 정체성 액센트 — PageHeader 라인 전용)
          light: '#C4A55E',
          dark: '#8B6F2E',
        },
        // KRDS 시맨틱 컬러
        success: '#228738',
        error: '#de3412',
        danger: '#de3412',
        warning: '#9e6a00',        // 텍스트용
        'warning-bg': '#ffb114',   // 아이콘/포인트용
        'warning-dark': '#805600', // 경고 틴트 배경 위 소형 텍스트용 (AA 4.5:1 확보)
        info: '#0b78cb',
        live: '#de3412',
        highlight: '#fef08a',
        // Gray scale — KRDS 회색 램프 오버라이드
        // (KRDS gray-5~90 ↔ Tailwind gray-50~900 매핑)
        gray: {
          50: '#f4f5f6',
          100: '#e6e8ea',
          200: '#cdd1d5',
          300: '#b1b8be',
          400: '#8a949e',
          500: '#6d7882',
          600: '#58616a',
          700: '#464c53',
          800: '#33363d',
          900: '#1e2124',
          950: '#131416',
        },
      },
      fontFamily: {
        sans: [
          // next/font/local이 해시 패밀리명으로 등록하므로 var(--font-pretendard) 참조 (layout.tsx)
          'var(--font-pretendard)',
          'Pretendard',
          'system-ui',
          '-apple-system',
          'BlinkMacSystemFont',
          'sans-serif',
        ],
        mono: ['JetBrains Mono', 'Source Code Pro', 'Consolas', 'monospace'],
      },
      animation: {
        pulse: 'pulse 1.5s ease-in-out infinite',
        shimmer: 'shimmer 2s ease-in-out infinite',
        'text-flash': 'textFlash 0.6s ease-out',
        blink: 'blink 1s step-end infinite',
        'fade-in': 'fadeIn 0.3s ease-out',
        'live-pulse': 'livePulse 1.4s ease-in-out infinite',
        'live-pulse-fast': 'livePulse 1.2s ease-in-out infinite',
      },
      keyframes: {
        fadeIn: {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        shimmer: {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0.7' },
        },
        textFlash: {
          '0%': { backgroundColor: 'rgba(37, 110, 244, 0.15)' },
          '100%': { backgroundColor: 'transparent' },
        },
        blink: {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0' },
        },
        livePulse: {
          '0%, 100%': { opacity: '1', transform: 'scale(1)' },
          '50%': { opacity: '0.4', transform: 'scale(0.85)' },
        },
      },
      boxShadow: {
        'ring': '0 0 0 1px rgba(37, 110, 244, 0.1)',
        'ring-light': '0 0 0 1px #e6e8ea',
        'card': '0 1px 2px rgba(0, 0, 0, 0.04), 0 1px 3px rgba(0, 0, 0, 0.06)',
        'card-elevated': '0 4px 6px -1px rgba(0, 0, 0, 0.06), 0 2px 4px -1px rgba(0, 0, 0, 0.04)',
        'focus': 'rgba(37, 110, 244, 0.2) 0px 0px 0px 3px',
      },
      letterSpacing: {
        'heading': '-0.04em',
        'heading-tight': '-0.06em',
        'code': '0.075em',
      },
      borderRadius: {
        'pill': '9999px',
      },
      screens: {
        sm: '640px',
        md: '768px',
        lg: '1024px',
        xl: '1280px',
      },
    },
  },
  plugins: [],
};
