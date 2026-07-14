/**
 * monitorUtils.js — Constantes y helpers puros del módulo Monitor.
 * La presentación se expresa como clases Tailwind (temas via tokens del config).
 */

export const MONITOR_TABS = [
  { id: "automatico", label: "🤖 Automático" },
  { id: "consola", label: "🖥️ Consola" },
  { id: "ligas", label: "⚽ Ligas & Tablas" },
  { id: "energia", label: "⚡ Energía" },
  { id: "historial", label: "📊 Historial" },
  { id: "alertas", label: "🔔 Alertas" },
];

export const RACHA_ICON = {
  W: "🟢",
  D: "🟡",
  L: "🔴",
  w: "🟢",
  d: "🟡",
  l: "🔴",
};

export const ALERTA_CLS = {
  info: {
    text: "text-neon-blue",
    box: "border-neon-blue/25 bg-neon-blue/[.03]",
  },
  warn: {
    text: "text-amber-500",
    box: "border-amber-500/25 bg-amber-500/[.03]",
  },
  critico: {
    text: "text-neon-red",
    box: "border-neon-red/25 bg-neon-red/[.03]",
  },
  default: {
    text: "text-slate-500",
    box: "border-slate-500/25 bg-slate-500/[.03]",
  },
};

export const FUENTE_ESTADO = {
  ok: { cls: "bg-neon-green text-cyber-900", label: "✓ Completado" },
  ejecutando: { cls: "bg-neon-blue text-cyber-900", label: "⟳ Ejecutando..." },
  error: { cls: "bg-neon-red text-white", label: "✗ Error" },
  pendiente: { cls: "bg-slate-500/20 text-slate-400", label: "◷ Pendiente" },
};

export const INTERVALOS = [
  { label: "15 min", val: 15 },
  { label: "30 min", val: 30 },
  { label: "1 hora", val: 60 },
  { label: "3 horas", val: 180 },
  { label: "6 horas", val: 360 },
  { label: "12 horas", val: 720 },
  { label: "24 horas", val: 1440 },
];

/* ISO UTC → "en 42s" / "en 5min" / "en 2h" */
export function fmtProxima(iso) {
  if (!iso) return "—";
  const s = Math.round((new Date(iso + "Z") - Date.now()) / 1000);
  if (s <= 0) return "¡Ahora!";
  if (s < 60) return `en ${s}s`;
  if (s < 3600) return `en ${Math.round(s / 60)}min`;
  return `en ${Math.round(s / 3600)}h`;
}

export function fmtUltima(iso) {
  return iso
    ? new Date(iso + "Z").toLocaleString("es", {
        day: "2-digit",
        month: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "Nunca";
}

/* Posición en la tabla → tokens de color (clasificación/descenso) */
export function colorPosicion(pos, total) {
  return pos <= 4
    ? { text: "text-neon-blue", border: "border-neon-blue", bg: "bg-neon-blue" }
    : pos <= 6
      ? {
          text: "text-neon-green",
          border: "border-neon-green",
          bg: "bg-neon-green",
        }
      : pos >= total - 2
        ? {
            text: "text-neon-red",
            border: "border-neon-red",
            bg: "bg-neon-red",
          }
        : {
            text: "text-[var(--t-text-muted)]",
            border: "border-slate-500",
            bg: "bg-slate-500",
          };
}
