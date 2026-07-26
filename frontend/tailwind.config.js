/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ['./app/**/*.{ts,tsx}', './components/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        nolan: {
          bg:      '#07111f',
          surface: '#0c1a2d',
          card:    '#10233d',
          border:  '#24405f',
          accent:  '#35b8ff',
          gold:    '#f5c542',
          red:     '#ff4d6d',
          green:   '#50d5a5',
          text:    '#edf6ff',
          muted:   '#91a4ba',
        },
      },
      fontFamily: {
        mono: ['JetBrains Mono', 'Fira Code', 'monospace'],
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
