/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx,ts,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['"Inter"', '-apple-system', 'sans-serif'],
        display: ['"Cormorant Garamond"', 'Georgia', 'serif'],
        mono: ['"JetBrains Mono"', '"Courier New"', 'monospace'],
      },
      colors: {
        // ── Paper (原型 #fbfaf6) ──
        paper: {
          50: '#fbfaf6',
          100: '#f5f0e6',
          200: '#e8dfc7',
          300: '#d8cea8',
        },
        // ── Ink (原型 #3a3328 深棕) ─
        ink: {
          50: '#faf8f4',
          100: '#f0ebe0',
          300: '#c4b896',
          500: '#9b8d6f',
          700: '#6f6657',
          900: '#3a3328',
        },
        // ── Dossier (辅助暖色) ──
        dossier: {
          50: '#faf7ee',
          100: '#f0ebe0',
          500: '#8a6b3a',
          700: '#5c4928',
        },
        // ─ Signal (原型强调色 #8a6b3a 金棕) ──
        signal: {
          50: '#faf5ec',
          100: '#f0e8d8',
          200: '#e0d3b0',
          300: '#c4b07a',
          500: '#8a6b3a',
          600: '#70450c',
          700: '#5a4520',
        },
        // ── Accent (语义同 signal) ──
        accent: {
          50: '#faf5ec',
          100: '#f0e8d8',
          200: '#e0d3b0',
          300: '#c4b07a',
          400: '#a8884a',
          500: '#8a6b3a',
          600: '#70450c',
          700: '#5a4520',
        },
        // ── Caution (警告 — 保留语义) ──
        caution: {
          100: '#f8e6c6',
          300: '#dfa94b',
          500: '#ad6f16',
          700: '#70450c',
        },
        // ── Risk (危险 — 保留语义) ──
        risk: {
          100: '#f5d6d0',
          300: '#dc8977',
          500: '#a8542a',
          700: '#6d2318',
        },
      },
      borderRadius: {
        // 原型使用 2px 直角风格（矩形元素）
        '2xl': '2px',
        'xl': '2px',
        'lg': '2px',
        'md': '2px',
        'sm': '2px',
        // 'full' 保持默认 9999px — spinner、状态点、pill 等需要真圆形
      },
      boxShadow: {
        dossier: '0 4px 12px -4px rgba(58, 51, 40, 0.12)',
        insetline: 'inset 0 1px 0 rgba(255, 255, 255, 0.6)',
      },
      animation: {
        'fade-in': 'fadeIn 260ms ease-out both',
        'rise-in': 'riseIn 360ms ease-out both',
        'scan-line': 'scanLine 2.2s ease-in-out infinite',
        'scale-in': 'scaleIn 300ms ease-out both',
      },
      keyframes: {
        fadeIn: {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        riseIn: {
          '0%': { opacity: '0', transform: 'translateY(10px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        scanLine: {
          '0%, 100%': { transform: 'translateX(-8%)', opacity: '0.3' },
          '50%': { transform: 'translateX(108%)', opacity: '0.7' },
        },
        scaleIn: {
          '0%': { transform: 'scale(0.85)', opacity: '0' },
          '100%': { transform: 'scale(1)', opacity: '1' },
        },
      },
    },
  },
  plugins: [],
};
