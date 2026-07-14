/**
 * LiveTasksTable.jsx — Tabla "Estado de Tareas en Tiempo Real":
 * tarea en curso, estado, progreso estimado y tiempo transcurrido.
 */
import { statsVacias, duracionEstimadaMs, fmtTiempo } from "./statsUtils";
import StatusBadge from "./StatusBadge";
import ProgressBar from "./ProgressBar";

const GRID = "grid grid-cols-[1.6fr_1.4fr_.8fr_1.4fr_.8fr]";

export default function LiveTasksTable({ agentes, stats, running, now }) {
  return (
    <div className="overflow-hidden rounded-[14px] border border-[var(--t-border)] bg-[var(--t-bg-surface)]">
      <div className="border-b border-[var(--t-border)] bg-neon-green/[.04] px-4 py-3 text-[.85rem] font-bold text-[var(--t-text)]">
        ⚡ Estado de Tareas en Tiempo Real
      </div>

      <div
        className={`${GRID} border-b border-[var(--t-border)] bg-[var(--t-bg-base)] px-4 py-2 text-[.68rem] font-bold uppercase tracking-[.05em] text-[var(--t-text-muted)]`}
      >
        <span>Agente</span>
        <span>Tarea</span>
        <span>Estado</span>
        <span>Progreso</span>
        <span>Tiempo</span>
      </div>

      {agentes.map((ag, idx) => {
        const s = stats[ag.id] || statsVacias();
        const tarea = running[ag.id];
        const activo = !!tarea;
        const elapsed = tarea ? now - tarea.inicio : null;
        const estMs = duracionEstimadaMs(s);
        const progreso =
          activo && estMs && elapsed
            ? Math.min(95, Math.round((elapsed / estMs) * 100))
            : null;
        const ultimaHora = s.ultima_ts
          ? new Date(s.ultima_ts).toLocaleTimeString("es", {
              hour: "2-digit",
              minute: "2-digit",
            })
          : null;
        return (
          <div
            key={ag.id}
            className={`${GRID} items-center px-4 py-[13px] transition-colors duration-200
              ${idx < agentes.length - 1 ? "border-b border-[var(--t-border)]" : ""}
              ${activo ? "bg-neon-green/[.025]" : "bg-transparent"}`}
          >
            <div className="flex items-center gap-2">
              <div className="relative">
                <div
                  className={`h-2.5 w-2.5 rounded-full transition-all duration-300 ${
                    activo
                      ? "bg-neon-green shadow-[0_0_8px_#00ff9d]"
                      : "bg-slate-700"
                  }`}
                />
                {activo && (
                  <div className="absolute -left-0.5 -top-0.5 h-3.5 w-3.5 animate-ping rounded-full border-[1.5px] border-neon-green opacity-50" />
                )}
              </div>
              <div>
                <div className="text-[.82rem] font-semibold text-[var(--t-text)]">
                  {ag.nombre}
                </div>
                <div className="text-[.65rem] text-slate-600">{ag.area}</div>
              </div>
            </div>

            <div>
              <div
                className={`overflow-hidden text-ellipsis whitespace-nowrap text-[.78rem] ${
                  activo
                    ? "font-semibold text-[var(--t-text)]"
                    : "font-normal text-slate-600"
                }`}
              >
                {activo
                  ? tarea.tarea
                  : ultimaHora
                    ? `Última: ${ultimaHora}`
                    : "Sin tareas aún"}
              </div>
            </div>

            <div>
              <StatusBadge activo={activo} />
            </div>
            <div>
              <ProgressBar activo={activo} progreso={progreso} />
            </div>

            <div
              className={`text-[.78rem] ${activo ? "font-semibold text-neon-blue" : "font-normal text-slate-600"}`}
            >
              {activo ? fmtTiempo(elapsed) : "—"}
            </div>
          </div>
        );
      })}
    </div>
  );
}
