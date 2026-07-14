/**
 * HistoryTab.jsx — Pestaña "Historial": datos crudos persistidos en SQLite.
 * Presentacional: los datos vienen del Puerto de Telemetría (useMonitorData).
 */
import { useEffect } from "react";
import { RefreshCw } from "../../icons.js";

export default function HistoryTab({ historial, onCargar }) {
  useEffect(() => {
    onCargar();
  }, [onCargar]);

  return (
    <div className="overflow-hidden rounded-xl border border-[var(--t-border)]">
      <div className="flex items-center justify-between border-b border-[var(--t-border)] bg-[var(--t-bg-base)] px-3.5 py-2">
        <span className="text-[.78rem] font-bold uppercase text-[var(--t-text-muted)]">
          Datos Monitoreados ({historial.length})
        </span>
        <button
          onClick={onCargar}
          className="cursor-pointer rounded-full border border-[var(--t-border)] bg-transparent px-2.5 py-[3px] text-[.7rem] text-[var(--t-text-muted)]"
        >
          <RefreshCw size={12} />
        </button>
      </div>
      {historial.length === 0 ? (
        <div className="p-8 text-center text-[.82rem] text-[var(--t-text-muted)]">
          Sin datos todavía. Consulta Ligas o Energía para generar historial.
        </div>
      ) : (
        historial.map((d, i) => (
          <div
            key={i}
            className={`grid grid-cols-[1fr_1.5fr_.7fr_.8fr] px-3.5 py-2 text-[.75rem] text-[var(--t-text)] ${
              i < historial.length - 1
                ? "border-b border-[var(--t-border)]"
                : ""
            } ${i % 2 === 0 ? "bg-transparent" : "bg-white/[.02]"}`}
          >
            <span className="text-[var(--t-text-muted)]">{d.categoria}</span>
            <span className="truncate">{d.clave}</span>
            <span className="font-bold text-[var(--t-accent)]">{d.valor}</span>
            <span className="text-[var(--t-text-muted)]">
              {new Date(d.ts).toLocaleString("es", {
                day: "2-digit",
                month: "2-digit",
                hour: "2-digit",
                minute: "2-digit",
              })}
            </span>
          </div>
        ))
      )}
    </div>
  );
}
