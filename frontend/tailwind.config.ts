import type { Config } from 'tailwindcss'

export default {
  content: [
    './index.html',
    './src/**/*.{vue,js,ts,jsx,tsx}',
  ],
  theme: {
    extend: {
      colors: {
        // ── Xiaomi Design System Colors ──
        xm: {
          primary: '#FF6700',        // 小米橙 — CTA、关键指标、选中态
          'primary-hover': '#E55A00',
          'primary-light': '#FFF0E6',
          bg: {
            page: '#FAFAFA',         // 页面背景
            card: '#FFFFFF',         // 卡片背景
            surface: '#F5F5F5',      // 次级背景
            sidebar: '#FAFAFA',      // 侧边栏背景
          },
          border: {
            DEFAULT: '#E0E0E0',
            light: '#EEEEEE',
          },
          text: {
            primary: '#1A1A1A',
            secondary: '#666666',
            tertiary: '#999999',
          },
        },
        // Profit/Loss (Xiaomi-tuned, lower saturation)
        profit: {
          DEFAULT: '#16A34A',
          light: '#4ADE80',
          bg: '#F0FDF4',
        },
        loss: {
          DEFAULT: '#DC2626',
          light: '#F87171',
          bg: '#FEF2F2',
        },
        // Risk indicators
        risk: {
          green: '#22C55E',
          yellow: '#EAB308',
          red: '#EF4444',
        },
        // Chart palette
        chart: {
          blue: '#3B82F6',
          cyan: '#06B6D4',
          purple: '#8B5CF6',
          orange: '#F97316',
          pink: '#EC4899',
          teal: '#14B8A6',
        },
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "-apple-system", "'PingFang SC'", "'Microsoft YaHei'", "sans-serif"],
        mono: ["'JetBrains Mono'", "'Fira Code'", "monospace"],
      },
      fontSize: {
        'xxs': '0.6875rem',        // 11px
        'md': '0.9375rem',          // 15px
      },
      spacing: {
        '18': '4.5rem',
        '88': '22rem',
        'sidebar': '240px',
      },
      animation: {
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.2, 1) infinite',
        'flash-green': 'flashGreen 0.5s ease-out',
        'flash-red': 'flashRed 0.5s ease-out',
        'fade-in': 'fadeIn 200ms cubic-bezier(0.4, 0, 0.2, 1)',
        'slide-up': 'slideUp 300ms cubic-bezier(0.4, 0, 0.2, 1)',
      },
      keyframes: {
        flashGreen: {
          '0%': { backgroundColor: 'rgba(22, 163, 74, 0.15)' },
          '100%': { backgroundColor: 'transparent' },
        },
        flashRed: {
          '0%': { backgroundColor: 'rgba(220, 38, 38, 0.15)' },
          '100%': { backgroundColor: 'transparent' },
        },
        fadeIn: {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        slideUp: {
          '0%': { opacity: '0', transform: 'translateY(8px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
      },
      transitionTimingFunction: {
        'xm': 'cubic-bezier(0.4, 0, 0.2, 1)',
      },
      transitionDuration: {
        'xm': '200ms',
      },
      boxShadow: {
        'xm': '0 1px 3px rgba(0, 0, 0, 0.04), 0 1px 2px rgba(0, 0, 0, 0.06)',
        'xm-md': '0 4px 8px rgba(0, 0, 0, 0.04), 0 2px 4px rgba(0, 0, 0, 0.06)',
        'xm-lg': '0 10px 25px rgba(0, 0, 0, 0.04), 0 4px 10px rgba(0, 0, 0, 0.06)',
      },
      borderRadius: {
        'xm': '8px',
      },
    },
  },
  plugins: [],
} satisfies Config
