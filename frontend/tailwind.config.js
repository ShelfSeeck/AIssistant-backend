/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{vue,js,ts,jsx,tsx}"
  ],
  theme: {
    extend: {
      colors: {
        bgMain: '#f3f4f6',
        bgSidebar: '#ffffff',
        borderLight: '#d1d5db',
        borderDark: '#1f2937',
        highlight: '#e5e7eb',
        highlightUser: '#f9fafb',
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
      }
    },
  },
  plugins: [],
}
