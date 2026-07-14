/**
 * LeagueStandingsTable.jsx — Tabla de posiciones de la liga seleccionada.
 */
import { RACHA_ICON, colorPosicion } from "./monitorUtils";

const GRID =
  "grid grid-cols-[34px_1.8fr_40px_40px_40px_40px_50px_50px_50px_65px_90px] gap-1";

export default function LeagueStandingsTable({ tabla }) {
  if (tabla.length === 0)
    return (
      <div className="rounded-xl border-2 border-dashed border-[var(--t-border)] p-8 text-center text-[.82rem] text-[var(--t-text-muted)]">
        Sin tabla de posiciones disponible para esta liga.
      </div>
    );

  return (
    <div className="overflow-hidden rounded-xl border border-[var(--t-border)]">
      <div
        className={`${GRID} border-b-2 border-[var(--t-accent)] bg-[var(--t-bg-base)] px-3.5 py-2.5 text-center text-[.72rem] font-extrabold uppercase text-[var(--t-accent)]`}
      >
        <span>#</span>
        <span className="text-left">Equipo</span>
        <span>PJ</span>
        <span>G</span>
        <span>E</span>
        <span>P</span>
        <span>GF</span>
        <span>GC</span>
        <span>DG</span>
        <span>Pts</span>
        <span>Forma</span>
      </div>
      {tabla.map((eq, i) => {
        const c = colorPosicion(eq.posicion, tabla.length);
        const forma = (eq.forma || "").split("").slice(0, 5);
        return (
          <div
            key={i}
            className={`${GRID} items-center px-3.5 py-[11px] text-center ${
              i < tabla.length - 1 ? "border-b border-[var(--t-border)]" : ""
            } ${i % 2 === 0 ? "bg-transparent" : "bg-white/[.02]"}`}
          >
            <span
              className={`border-l-[3px] pl-[5px] text-[.85rem] font-black ${c.text} ${c.border}`}
            >
              {eq.posicion}
            </span>
            <span
              className={`truncate text-left text-[.85rem] text-[var(--t-text)] ${
                eq.posicion <= 3 ? "font-extrabold" : "font-medium"
              }`}
            >
              {eq.equipo}
            </span>
            <span className="text-[.82rem] text-[var(--t-text-muted)]">
              {eq.pj}
            </span>
            <span className="text-[.85rem] font-bold text-neon-green">
              {eq.victorias}
            </span>
            <span className="text-[.82rem] font-semibold text-amber-500">
              {eq.empates}
            </span>
            <span className="text-[.82rem] font-semibold text-neon-red">
              {eq.derrotas}
            </span>
            <span className="text-[.82rem] text-[var(--t-text-muted)]">
              {eq.gf}
            </span>
            <span className="text-[.82rem] text-slate-500">{eq.gc}</span>
            <span
              className={`text-[.85rem] font-bold ${
                eq.diferencia > 0
                  ? "text-neon-green"
                  : eq.diferencia < 0
                    ? "text-neon-red"
                    : "text-slate-500"
              }`}
            >
              {eq.diferencia > 0 ? "+" : ""}
              {eq.diferencia}
            </span>
            <span
              className={`inline-block rounded-lg px-2 py-[3px] text-[.95rem] font-black text-white ${c.bg}`}
            >
              {eq.puntos}
            </span>
            <div className="flex justify-center gap-0.5">
              {forma.map((f, k) => (
                <span key={k} className="text-[13px]">
                  {RACHA_ICON[f] ?? ""}
                </span>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}
