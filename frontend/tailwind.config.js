/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ['./app/**/*.{ts,tsx}', './components/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        nolan: {
          bg:      '#faf7f0',
          surface: '#f5f1e8',
          card:    '#ffffff',
          border:  '#e6ded1',
          accent:  '#a67c4a',
          gold:    '#c9a86c',
          red:     '#b85345',
          green:   '#4e8065',
          text:    '#2d2d2d',
          muted:   '#6b6255',
        },
      },
      fontFamily: {
        sans: ['IBM Plex Sans', 'Inter', 'system-ui', 'sans-serif'],
        mono: ['Courier Prime', 'Courier New', 'monospace'],
        serif: ['Libre Baskerville', 'Georgia', 'Times New Roman', 'serif'],
      },
      animation: {
        pulse_slow: 'pulse 3s cubic-bezier(0.4,0,0.6,1) infinite',
        glow:       'glow 2s ease-in-out infinite alternate',
        typewriter: 'typewriter 0.05s steps(1) forwards',
      },
      keyframes: {
        glow: {
          '0%':   { boxShadow: '0 0 5px #6c47ff44' },
          '100%': { boxShadow: '0 0 20px #6c47ff99, 0 0 40px #6c47ff33' },
        },
      },
    },
  },
  plugins: [],
}
