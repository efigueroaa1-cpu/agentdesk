/**
 * MetricCard.jsx — Celda de tasa de éxito: valor, barra de progreso y conteos.
 */
import { estadoDeTasa } from "./statsUtils";

export default function MetricCard({ tasa, ok, fail }) {
  const estado = estadoDeTasa(tasa);
  const total = ok + fail;
  return (
    <div>
      <div className={`font-extrabold text-[.95rem] ${estado.textCls}`}>
        {tasa !== null ? `${tasa}%` : "—"}
      </div>
      {total > 0 && (
        <div className="mt-1 h-1 w-[60px] rounded bg-[var(--t-border)]">
          <div
            className={`h-full rounded transition-[width] duration-400 ${estado.barCls}`}
            style={{ width: `${tasa}%` }}
          />
        </div>
      )}
      <div className="mt-0.5 text-[.63rem] text-slate-600">
        {ok}✓ {fail}✗
      </div>
    </div>
  );
}
