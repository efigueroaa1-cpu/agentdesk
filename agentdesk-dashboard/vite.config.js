import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  base: "/ui/",
  plugins: [react()],
  server: {
    watch: { ignored: ["**/src-tauri/**", "**/.git/**"] },
    port: 5173,
    strictPort: true,
  },
  build: {
    outDir: "dist",
    sourcemap: false,
    rollupOptions: {
      output: {
        // Code-splitting (Fase 8): vendors pesados en chunks propios que el
        // navegador descarga solo cuando un módulo lazy los necesita.
        manualChunks(id) {
          if (!id.includes("node_modules")) return undefined;
          if (
            id.includes("react-simple-maps") ||
            id.includes("d3-geo") ||
            id.includes("d3-zoom") ||
            id.includes("topojson")
          ) {
            return "vendor-maps";
          }
          if (
            id.includes("recharts") ||
            id.includes("d3-") ||
            id.includes("victory")
          ) {
            return "vendor-charts";
          }
          // react + resto del ecosistema en un único chunk base: separarlos
          // producía un ciclo vendor↔vendor-react (zustand/lucide importan react)
          return "vendor";
        },
      },
    },
  },
});
