/**
 * LeagueHeader.jsx — Cabecera de liga (nombre, país, temporada, refrescar)
 * y tarjetas de estadísticas destacadas.
 */
import { RefreshCw } from "../../icons.js";

const STAT_CARDS = [
  ["Líder", "lider", "border-neon-green text-neon-green"],
  ["Puntos líder", "max_puntos", "border-neon-blue text-neon-blue"],
  ["Más goles", "equipo_mas_goles", "border-amber-500 text-amber-500"],
  [
    "Total goles",
    "total_goles_marcados",
    "border-neon-purple text-neon-purple",
  ],
];

export function LeagueHeader({ liga, datos, stats, cargando, onRefrescar }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-neon-blue/20 bg-neon-blue/[.06] px-4 py-3">
      <div>
        <div className="text-base font-extrabold text-[var(--t-text)]">
          ⚽ {liga.nombre}
        </div>
        <div className="mt-0.5 text-[.72rem] text-[var(--t-text-muted)]">
          {liga.pais} · {datos?.temporada ?? "temporada actual"}
          {stats.equipos ? ` · ${stats.equipos} equipos` : ""}
        </div>
      </div>
      <button
        onClick={onRefrescar}
        disabled={cargando}
        className="flex cursor-pointer items-center gap-[5px] rounded-full border border-[var(--t-accent)] bg-neon-blue/10 px-3.5 py-[5px] font-[inherit] text-[.75rem] text-[var(--t-accent)]"
      >
        <RefreshCw size={13} className={cargando ? "animate-spin" : ""} />{" "}
        Actualizar
      </button>
    </div>
  );
}

export function LeagueStatsCards({ stats }) {
  return (
    <div className="grid grid-cols-[repeat(auto-fill,minmax(160px,1fr))] gap-3">
      {STAT_CARDS.map(([label, key, cls]) => (
        <div
          key={label}
          className={`rounded-xl border-2 bg-[var(--t-bg-base)] px-4 py-3.5 ${cls}`}
        >
          <div className="mb-[7px] text-[.72rem] font-semibold uppercase tracking-[.05em] text-[var(--t-text-muted)]">
            {label}
          </div>
          <div className="truncate text-[1.1rem] font-black">
            {stats[key] && stats[key] !== "?" ? (
              stats[key]
            ) : (
              <span className="text-[.85rem] text-slate-600">Sin datos</span>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
