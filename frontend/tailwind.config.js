/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx,ts,tsx}'],
  theme: {
    extend: {
      colors: {
        yotpo: {
          purple: '#3C1053',
          light:  '#6B21A8',
          pale:   '#F5F0FF',
          border: '#DDD6FE',
        },
      },
    },
  },
  plugins: [],
}
