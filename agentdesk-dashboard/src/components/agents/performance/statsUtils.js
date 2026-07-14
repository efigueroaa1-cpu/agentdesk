/**
 * statsUtils.js — Helpers puros de estadísticas de agentes.
 *
 * Cálculo de tasa de éxito, latencia, tendencia y su presentación
 * (clases Tailwind, sin estilos inyectados). Persistencia en localStorage.
 */

export const STATS_KEY = "agentdesk-agent-stats-v2";

export function cargarStats() {
  try {
    return JSON.parse(localStorage.getItem(STATS_KEY) ?? "{}");
  } catch {
    return {};
  }
}

export function guardarStats(stats) {
  try {
    localStorage.setItem(STATS_KEY, JSON.stringify(stats));
  } catch {
    /* almacenamiento no disponible */
  }
}

export function statsVacias() {
  return {
    ok: 0,
    fail: 0,
    latencias: [],
    ultimasTareas: [],
    ultima_ts: null,
    tarea_inicio: null,
  };
}

/* Tasa de éxito en % (null si no hay tareas registradas) */
export function tasaExito(s) {
  const total = s.ok + s.fail;
  return total === 0 ? null : Math.round((s.ok / total) * 100);
}

/* Latencia promedio (s) de las últimas 10 tareas */
export function latenciaProm(s) {
  return s.latencias.length
    ? (
        s.latencias.slice(-10).reduce((acc, l) => acc + l, 0) /
        Math.min(s.latencias.length, 10)
      ).toFixed(3)
    : null;
}

/* Duración estimada (ms) = promedio de las últimas 5 latencias */
export function duracionEstimadaMs(s) {
  return s.latencias.length
    ? (s.latencias.slice(-5).reduce((acc, l) => acc + l, 0) /
        Math.min(s.latencias.length, 5)) *
        1000
    : null;
}

/* Tendencia según las últimas 5 tareas */
export function tendencia(s) {
  const ultimas = s.ultimasTareas.slice(-5);
  if (ultimas.length < 2) return "nueva";
  const score = ultimas.reduce((acc, t) => acc + (t === "ok" ? 1 : -1), 0);
  return score >= 3 ? "mejora" : score <= -2 ? "empeora" : "estable";
}

/* Presentación de la salud según la tasa de éxito (clases Tailwind) */
export function estadoDeTasa(tasa) {
  return tasa === null
    ? {
        emoji: "❓",
        label: "Sin datos",
        textCls: "text-slate-500",
        barCls: "bg-slate-500",
      }
    : tasa >= 95
      ? {
          emoji: "😊",
          label: "Excelente",
          textCls: "text-neon-green",
          barCls: "bg-neon-green",
        }
      : tasa >= 80
        ? {
            emoji: "😐",
            label: "Aceptable",
            textCls: "text-amber-500",
            barCls: "bg-amber-500",
          }
        : {
            emoji: "😟",
            label: "Revisar",
            textCls: "text-neon-red",
            barCls: "bg-neon-red",
          };
}

/* Presentación de la tendencia (clases Tailwind) */
export function displayTendencia(t) {
  const MAP = {
    mejora: {
      icon: "↑",
      label: "Mejorando",
      textCls: "text-neon-green",
      chipCls: "bg-neon-green/10 border-neon-green/30",
    },
    estable: {
      icon: "=",
      label: "Estable",
      textCls: "text-amber-500",
      chipCls: "bg-amber-500/10 border-amber-500/30",
    },
    empeora: {
      icon: "↓",
      label: "Empeorando",
      textCls: "text-neon-red",
      chipCls: "bg-neon-red/10 border-neon-red/30",
    },
    nueva: {
      icon: "✦",
      label: "Sin historial",
      textCls: "text-slate-500",
      chipCls: "bg-slate-500/10 border-slate-500/30",
    },
  };
  return MAP[t] ?? MAP.nueva;
}

/* ms transcurridos → "42s" / "2m 5s" */
export function fmtTiempo(ms) {
  if (!ms) return "—";
  const s = Math.floor(ms / 1000);
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${s % 60}s`;
}
