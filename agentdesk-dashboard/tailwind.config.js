/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        // Colores personalizados del tema AgentDesk
        // Mapeados a las CSS variables de index.css
        "neon-blue":  "#00d4ff",
        "neon-green": "#00ff9d",
        "neon-red":   "#ff2d55",
        "neon-purple":"#7c3aed",
        // Paleta cyber (fondo oscuro)
        "cyber": {
          900: "#020818",   // --t-bg-deep
          800: "#060d24",   // --t-bg-base
          700: "#0d1a3e",   // --t-bg-surface
          600: "#162454",   // --t-border
          500: "#1e3a6e",
          400: "#2d5299",
        },
        // Alias para compatibilidad
        "brand": {
          DEFAULT: "#00d4ff",
          dark:    "#0097b8",
        },
      },
      fontFamily: {
        mono: ["JetBrains Mono", "Fira Code", "monospace"],
      },
    },
  },
  plugins: [],
};
