/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        whv: {
          primary: "#1a1a1a",
          accent: "#0ea5e9",
        },
      },
    },
  },
  plugins: [],
};
