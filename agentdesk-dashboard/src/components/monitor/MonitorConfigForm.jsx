/**
 * MonitorConfigForm.jsx — Configuración de una fuente monitoreada:
 * frecuencia de escaneo, ejecución inmediata y activar/pausar.
 * Presentacional puro: recibe la fuente y callbacks del Puerto de Telemetría.
 * (El backend hoy solo permite editar frecuencia y estado; la URL/endpoint
 * de cada fuente es fija por preset.)
 */
import { Play } from "../../icons.js";
import { INTERVALOS } from "./monitorUtils";

export default function MonitorConfigForm({
  fuente,
  onCambiarFrecuencia,
  onEjecutar,
  onAlternar,
}) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <select
        value={fuente.intervalo_min}
        onChange={(e) => onCambiarFrecuencia(fuente, Number(e.target.value))}
        className="rounded-lg border border-[var(--t-border)] bg-[var(--t-bg-base)] px-2.5 py-[5px] font-[inherit] text-[.76rem] text-[var(--t-text)] outline-none"
      >
        {INTERVALOS.map((op) => (
          <option key={op.val} value={op.val}>
            {op.label}
          </option>
        ))}
      </select>
      <button
        onClick={() => onEjecutar(fuente)}
        disabled={fuente.estado === "ejecutando"}
        className="flex cursor-pointer items-center gap-[5px] rounded-lg border border-[var(--t-accent)] bg-neon-blue/10 px-3 py-1.5 font-[inherit] text-[.76rem] font-bold text-[var(--t-accent)] disabled:cursor-not-allowed disabled:opacity-50"
      >
        <Play size={13} /> Ahora
      </button>
      <button
        onClick={() => onAlternar(fuente)}
        className={`cursor-pointer rounded-lg border-none px-4 py-1.5 font-[inherit] text-[.78rem] font-extrabold ${
          fuente.activo
            ? "bg-neon-green text-cyber-900"
            : "bg-[var(--t-border)] text-[var(--t-text-muted)]"
        }`}
      >
        {fuente.activo ? "● ACTIVO" : "○ PAUSADO"}
      </button>
    </div>
  );
}
