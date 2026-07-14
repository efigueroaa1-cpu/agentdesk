/**
 * MonitorTaskTable.jsx — Listado de fuentes monitoreadas y su estado
 * (Activo/Pausado, última y próxima ejecución). Presentacional: consume el
 * Puerto de Telemetría (useMonitorData) vía props.
 */
import { RefreshCw } from "../../icons.js";
import { FUENTE_ESTADO, fmtProxima, fmtUltima } from "./monitorUtils";
import MonitorConfigForm from "./MonitorConfigForm";
import LoadingSpinner from "./LoadingSpinner";

export default function MonitorTaskTable({ fuentes, cargando, acciones }) {
  const activos = fuentes.filter((f) => f.activo).length;
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-4 rounded-[14px] border border-neon-blue/20 bg-neon-blue/5 px-[18px] py-3">
        <div>
          <div className="text-[.95rem] font-extrabold text-[var(--t-text)]">
            🤖 Agente de Monitoreo Automático
          </div>
          <div className="mt-[3px] text-[.75rem] text-[var(--t-text-muted)]">
            {activos} de {fuentes.length} monitores activos · corre en segundo
            plano
          </div>
        </div>
        <div className="flex items-center gap-2">
          <div
            className={`h-2.5 w-2.5 shrink-0 rounded-full ${
              activos > 0
                ? "bg-neon-green shadow-[0_0_10px_#00ff9d]"
                : "bg-slate-700"
            }`}
          />
          <span
            className={`text-[.78rem] font-semibold ${
              activos > 0 ? "text-neon-green" : "text-slate-500"
            }`}
          >
            {activos > 0 ? "Sistema activo" : "Sistema inactivo"}
          </span>
          <button
            onClick={acciones.recargar}
            className="cursor-pointer rounded-full border border-[var(--t-border)] bg-transparent px-2.5 py-1 font-[inherit] text-[.72rem] text-[var(--t-text-muted)]"
          >
            <RefreshCw size={12} />
          </button>
        </div>
      </div>

      <div className="rounded-xl border border-[var(--t-border)] bg-[var(--t-bg-base)] px-4 py-2.5 text-[.75rem] leading-[1.8] text-[var(--t-text-muted)]">
        <strong className="text-[var(--t-accent)]">Flujo de datos:</strong>{" "}
        Monitor Web → <span className="text-amber-500">Datos Crudos</span> →
        SQLite (sin filtros) → <span className="text-neon-blue">Agente IA</span>{" "}
        → <span className="text-neon-purple">Pipeline</span> →{" "}
        <span className="text-neon-green">Informe Verificado</span>
        <br />
        Los datos reales NO pasan por pipeline. Solo el análisis del agente es
        validado.
      </div>

      {cargando ? (
        <LoadingSpinner />
      ) : (
        <div className="flex flex-col gap-3">
          {fuentes.map((f) => {
            const est = FUENTE_ESTADO[f.estado] ?? FUENTE_ESTADO.pendiente;
            return (
              <div
                key={f.id}
                className={`rounded-[14px] border-2 px-[1.4rem] py-[1.1rem] ${
                  f.activo
                    ? "border-neon-blue bg-[var(--t-bg-surface)]"
                    : "border-slate-700 bg-[var(--t-bg-base)]"
                }`}
              >
                <div className="flex flex-wrap items-start justify-between gap-4">
                  <div className="flex items-center gap-3">
                    <span className="text-[26px]">{f.icono}</span>
                    <div>
                      <div className="text-base font-extrabold text-[var(--t-text)]">
                        {f.nombre}
                      </div>
                      <div className="mt-1.5 flex flex-wrap items-center gap-2">
                        <span
                          className={`rounded-full px-[11px] py-[3px] text-[.72rem] font-extrabold ${est.cls}`}
                        >
                          {est.label}
                        </span>
                        <span className="text-[.74rem] font-medium text-[var(--t-text-muted)]">
                          Última:{" "}
                          <strong className="text-[var(--t-text)]">
                            {fmtUltima(f.ultimo_fetch)}
                          </strong>
                        </span>
                        {f.activo && (
                          <span className="text-[.74rem] font-semibold text-neon-blue">
                            Próxima: {fmtProxima(f.proxima_ejecucion)}
                          </span>
                        )}
                      </div>
                    </div>
                  </div>
                  <MonitorConfigForm
                    fuente={f}
                    onCambiarFrecuencia={acciones.cambiarFrecuencia}
                    onEjecutar={acciones.ejecutarAhora}
                    onAlternar={acciones.alternar}
                  />
                </div>
              </div>
            );
          })}
          {fuentes.length === 0 && (
            <div className="p-8 text-center text-[.85rem] text-[var(--t-text-muted)]">
              No hay tareas de monitoreo configuradas en el scheduler.
            </div>
          )}
        </div>
      )}
    </div>
  );
}
