/**
 * PerformanceTable.jsx — Tabla "Rendimiento por Agente":
 * tasa de éxito, latencia promedio, tendencia y salud por agente.
 */
import { RefreshCw } from "../../../icons.js";
import { statsVacias, tasaExito, latenciaProm, tendencia } from "./statsUtils";
import MetricCard from "./MetricCard";
import LatencyChart from "./LatencyChart";
import TrendIndicator from "./TrendIndicator";
import HealthIndicator from "./HealthIndicator";

const GRID = "grid grid-cols-[1.6fr_.8fr_.9fr_1.1fr_.7fr]";

export default function PerformanceTable({ agentes, stats, running, onReset }) {
  return (
    <div className="overflow-hidden rounded-[14px] border border-[var(--t-border)] bg-[var(--t-bg-surface)]">
      <div className="flex items-center justify-between border-b border-[var(--t-border)] bg-neon-blue/[.04] px-4 py-3">
        <div className="text-[.85rem] font-bold text-[var(--t-text)]">
          📊 Rendimiento por Agente
        </div>
        <button
          onClick={onReset}
          className="flex cursor-pointer items-center gap-[5px] rounded-full border border-[var(--t-border)] bg-transparent px-2.5 py-[3px] font-[inherit] text-[.7rem] text-slate-500"
        >
          <RefreshCw size={11} /> Resetear
        </button>
      </div>

      <div
        className={`${GRID} border-b border-[var(--t-border)] bg-[var(--t-bg-base)] px-4 py-2 text-[.68rem] font-bold uppercase tracking-[.05em] text-[var(--t-text-muted)]`}
      >
        <span>Agente</span>
        <span>Tasa Éxito</span>
        <span>Latencia prom.</span>
        <span>Tendencia</span>
        <span>Estado</span>
      </div>

      {agentes.map((ag, idx) => {
        const s = stats[ag.id] || statsVacias();
        const tasa = tasaExito(s);
        const total = s.ok + s.fail;
        const activo = !!running[ag.id];
        return (
          <div
            key={ag.id}
            className={`${GRID} items-center px-4 py-3.5 transition-colors duration-200
              ${idx < agentes.length - 1 ? "border-b border-[var(--t-border)]" : ""}
              ${activo ? "bg-neon-blue/[.03]" : "bg-transparent"}`}
          >
            <div className="flex items-center gap-[9px]">
              <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-neon-blue/30 bg-neon-blue/10 text-[15px]">
                🤖
              </div>
              <div>
                <div className="text-[.82rem] font-bold text-[var(--t-text)]">
                  {ag.nombre}
                </div>
                <div className="text-[.66rem] text-[var(--t-text-muted)]">
                  {ag.area} · {total} tareas
                </div>
              </div>
            </div>

            <MetricCard tasa={tasa} ok={s.ok} fail={s.fail} />
            <LatencyChart latencias={s.latencias} promedio={latenciaProm(s)} />
            <TrendIndicator
              tendencia={tendencia(s)}
              ultimasTareas={s.ultimasTareas}
            />
            <HealthIndicator tasa={tasa} />
          </div>
        );
      })}
    </div>
  );
}
