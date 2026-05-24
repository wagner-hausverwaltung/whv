/** @type {import('tailwindcss').Config} */
// Palette + typography mirror wagner-hausverwaltung.com (Astra/Elementor):
//   #1863DC primary blue   · #0C66B4 hover · #0056A7 depth
//   #212121 body text      · #4E4B66 muted
//   #FBFBFB page bg        · #F4F4F4 soft card · #EBEBEB borders
//
// Fonts: Montserrat (display, h1/h2/buttons), Noto Sans (body).
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        whv: {
          blue: "#1863DC",
          "blue-hover": "#0C66B4",
          "blue-deep": "#0056A7",
          text: "#212121",
          muted: "#4E4B66",
          bg: "#FBFBFB",
          surface: "#F4F4F4",
          border: "#EBEBEB",
        },
      },
      fontFamily: {
        display: ["Montserrat", "system-ui", "sans-serif"],
        sans: ["Noto Sans", "system-ui", "sans-serif"],
      },
    },
  },
  plugins: [],
};
