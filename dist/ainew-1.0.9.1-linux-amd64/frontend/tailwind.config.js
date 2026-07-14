/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        cyber: {
          deep:   '#070b14',
          base:   '#0a0f1e',
          card:   '#0d1424',
          card2:  '#111827',
          hover:  '#151f35',
          border: 'rgba(99,130,194,0.15)',
        },
        neon: {
          cyan:   '#22d3ee',
          blue:   '#3b82f6',
          purple: '#a855f7',
          green:  '#10b981',
          orange: '#f59e0b',
          red:    '#ef4444',
          pink:   '#ec4899',
        },
      },
      backgroundImage: {
        'gradient-radial': 'radial-gradient(var(--tw-gradient-stops))',
        'cyber-grid': "linear-gradient(rgba(99,130,194,0.05) 1px, transparent 1px), linear-gradient(90deg, rgba(99,130,194,0.05) 1px, transparent 1px)",
      },
      backgroundSize: {
        'cyber-grid': '40px 40px',
      },
      boxShadow: {
        'neon-cyan':   '0 0 20px rgba(34,211,238,0.4), 0 0 60px rgba(34,211,238,0.1)',
        'neon-blue':   '0 0 20px rgba(59,130,246,0.4), 0 0 60px rgba(59,130,246,0.1)',
        'neon-purple': '0 0 20px rgba(168,85,247,0.4), 0 0 60px rgba(168,85,247,0.1)',
        'neon-green':  '0 0 20px rgba(16,185,129,0.4), 0 0 60px rgba(16,185,129,0.1)',
        'neon-orange': '0 0 20px rgba(245,158,11,0.4), 0 0 60px rgba(245,158,11,0.1)',
        'neon-red':    '0 0 20px rgba(239,68,68,0.4),  0 0 60px rgba(239,68,68,0.1)',
        'card':        '0 4px 24px rgba(0,0,0,0.4)',
        'card-hover':  '0 8px 40px rgba(0,0,0,0.5), 0 0 0 1px rgba(99,179,237,0.1)',
        'inner-glow':  'inset 0 1px 0 rgba(255,255,255,0.05)',
      },
      animation: {
        'pulse-slow':    'pulse 3s ease-in-out infinite',
        'pulse-fast':    'pulse 1s ease-in-out infinite',
        'shimmer':       'shimmer 2s infinite',
        'float':         'float 6s ease-in-out infinite',
        'glow-pulse':    'glowPulse 2s ease-in-out infinite',
        'scan':          'scan 4s linear infinite',
        'data-flow':     'dataFlow 3s linear infinite',
        'border-glow':   'borderGlow 3s ease-in-out infinite',
        'count-up':      'countUp 0.5s ease-out',
        'slide-in-left': 'slideInLeft 0.3s ease-out',
        'slide-in-up':   'slideInUp 0.3s ease-out',
        'fade-in':       'fadeIn 0.4s ease-out',
      },
      keyframes: {
        float: {
          '0%, 100%': { transform: 'translateY(0px)' },
          '50%':      { transform: 'translateY(-6px)' },
        },
        glowPulse: {
          '0%, 100%': { opacity: '0.6' },
          '50%':      { opacity: '1' },
        },
        scan: {
          '0%':   { transform: 'translateY(-100%)' },
          '100%': { transform: 'translateY(100vh)' },
        },
        slideInLeft: {
          from: { opacity: '0', transform: 'translateX(-16px)' },
          to:   { opacity: '1', transform: 'translateX(0)' },
        },
        slideInUp: {
          from: { opacity: '0', transform: 'translateY(12px)' },
          to:   { opacity: '1', transform: 'translateY(0)' },
        },
        fadeIn: {
          from: { opacity: '0' },
          to:   { opacity: '1' },
        },
      },
      fontFamily: {
        mono: ['JetBrains Mono', 'Fira Code', 'Cascadia Code', 'Consolas', 'monospace'],
      },
    },
  },
  plugins: [
    require('@tailwindcss/typography'),
  ],
}
