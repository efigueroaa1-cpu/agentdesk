/**
 * AlertsTab.jsx — Pestaña "Alertas": alertas generadas por el monitor.
 * Presentacional: los datos vienen del Puerto de Telemetría (useMonitorData).
 */
import { useEffect } from "react";
import { ALERTA_CLS } from "./monitorUtils";

export default function AlertsTab({ alertas, onCargar }) {
  useEffect(() => {
    onCargar();
  }, [onCargar]);

  if (alertas.length === 0)
    return (
      <div className="rounded-xl border-2 border-dashed border-[var(--t-border)] p-8 text-center text-[.85rem] text-[var(--t-text-muted)]">
        Sin alertas generadas todavía.
      </div>
    );

  return (
    <div className="flex flex-col gap-2">
      {alertas.map((a, i) => {
        const cls = ALERTA_CLS[a.nivel] ?? ALERTA_CLS.default;
        return (
          <div key={i} className={`rounded-xl border px-4 py-3 ${cls.box}`}>
            <div className="mb-1 flex justify-between">
              <span className={`text-[.82rem] font-bold ${cls.text}`}>
                {a.titulo}
              </span>
              <span className="text-[.68rem] text-[var(--t-text-muted)]">
                {new Date(a.ts).toLocaleString("es")}
              </span>
            </div>
            <div className="text-[.78rem] text-[var(--t-text-muted)]">
              {a.descripcion}
            </div>
          </div>
        );
      })}
    </div>
  );
}
