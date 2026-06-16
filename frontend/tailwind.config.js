/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx,ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // Yotpo brand. Key names kept (purple/light/pale/border) so existing
        // class names rebrand to blue with no churn; dark/ink/accent are new.
        yotpo: {
          purple: '#0042E4',  // primary (Yotpo blue)
          light:  '#3366FF',  // hover / lighter blue
          pale:   '#EEF3FF',  // tinted background
          border: '#C7D6FF',  // tinted border
          dark:   '#001A66',  // deep navy
          ink:    '#0B0B0F',  // near-black (hero / headings)
          accent: '#1F6FFF',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'Segoe UI', 'sans-serif'],
      },
      boxShadow: {
        card: '0 1px 2px rgba(11,11,15,.04), 0 4px 16px rgba(11,11,15,.05)',
        'card-hover': '0 2px 4px rgba(11,11,15,.06), 0 12px 28px rgba(0,66,228,.10)',
        ring: '0 8px 30px rgba(0,66,228,.18)',
      },
      keyframes: {
        'fade-up': {
          '0%': { opacity: '0', transform: 'translateY(6px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
      },
      animation: {
        'fade-up': 'fade-up .35s ease-out both',
      },
    },
  },
  plugins: [],
}
