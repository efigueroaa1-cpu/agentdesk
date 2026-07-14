/**
 * TrendIndicator.jsx — Tendencia del agente: icono, etiqueta y puntos
 * de las últimas 5 tareas (verde = ok, rojo = fallo, gris = sin dato).
 */
import { displayTendencia } from "./statsUtils";

export default function TrendIndicator({ tendencia, ultimasTareas }) {
  const d = displayTendencia(tendencia);
  const ultimas = ultimasTareas.slice(-5);
  return (
    <div className="flex items-center gap-[7px]">
      <div
        className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full border-[1.5px] text-sm font-extrabold ${d.textCls} ${d.chipCls}`}
      >
        {d.icon}
      </div>
      <div>
        <div className={`text-[.78rem] font-semibold ${d.textCls}`}>
          {d.label}
        </div>
        <div className="mt-[3px] flex gap-0.5">
          {ultimas.map((t, i) => (
            <div
              key={i}
              className={`h-1.5 w-1.5 rounded-full ${t === "ok" ? "bg-neon-green" : "bg-neon-red"}`}
            />
          ))}
          {Array.from({ length: Math.max(0, 5 - ultimas.length) }).map(
            (_, i) => (
              <div
                key={`e${i}`}
                className="h-1.5 w-1.5 rounded-full bg-slate-800"
              />
            ),
          )}
        </div>
      </div>
    </div>
  );
}
