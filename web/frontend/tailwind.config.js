/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx,ts,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['"IBM Plex Sans"', 'Verdana', 'sans-serif'],
        display: ['"Fraunces"', 'Georgia', 'serif'],
        mono: ['"IBM Plex Mono"', '"Courier New"', 'monospace'],
      },
      colors: {
        paper: {
          50: '#fbf7ef',
          100: '#f2eadb',
          200: '#e2d3b9',
          300: '#cab48b',
        },
        ink: {
          50: '#f4f3ef',
          100: '#dedbd1',
          300: '#918b7b',
          500: '#5f5b51',
          700: '#35322c',
          900: '#171611',
        },
        dossier: {
          50: '#f8f5ec',
          100: '#eee4cd',
          500: '#8a6f3d',
          700: '#5c4928',
        },
        signal: {
          100: '#d8efe8',
          300: '#8fcdbc',
          500: '#227863',
          700: '#185847',
        },
        caution: {
          100: '#f8e6c6',
          300: '#dfa94b',
          500: '#ad6f16',
          700: '#70450c',
        },
        risk: {
          100: '#f5d6d0',
          300: '#dc8977',
          500: '#a33a28',
          700: '#6d2318',
        },
      },
      boxShadow: {
        dossier: '0 18px 45px -30px rgba(23, 22, 17, 0.55)',
        insetline: 'inset 0 1px 0 rgba(255, 255, 255, 0.78)',
      },
      animation: {
        'fade-in': 'fadeIn 260ms ease-out both',
        'rise-in': 'riseIn 360ms ease-out both',
        'scan-line': 'scanLine 2.2s ease-in-out infinite',
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
      },
    },
  },
  plugins: [],
};
