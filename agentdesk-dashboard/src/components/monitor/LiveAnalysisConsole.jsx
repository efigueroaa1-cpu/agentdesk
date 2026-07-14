/**
 * LiveAnalysisConsole.jsx — Consola de análisis en tiempo real: muestra el
 * stream de eventos del FilterLogHandler (WebSocket /ws/telemetria) que
 * entrega el Puerto de Telemetría. Filtros, pausa y autoscroll.
 */
import { useState, useEffect, useRef } from "react";
import TabPills from "./TabPills";

const FILTROS = [
  { id: "todos", label: "Todos" },
  { id: "monitor", label: "Monitor" },
  { id: "errores", label: "Errores" },
];

function pasaFiltro(ev, filtro) {
  if (filtro === "monitor")
    return (
      (ev.tipo || "").startsWith("monitor") ||
      ev.tipo === "scheduler_actualizado"
    );
  if (filtro === "errores")
    return (ev.tipo || "").includes("error") || ev.status === "error";
  return true;
}

function resumen(ev) {
  return (
    ev.mensaje ||
    ev.error ||
    [ev.agente, ev.nombre, ev.tarea, ev.status].filter(Boolean).join(" · ") ||
    JSON.stringify(ev).slice(0, 120)
  );
}

function colorTipo(tipo = "") {
  if (tipo.includes("error")) return "text-neon-red";
  if (tipo.includes("completad") || tipo === "tarea_completada")
    return "text-neon-green";
  if (tipo.startsWith("monitor") || tipo === "telemetria")
    return "text-neon-blue";
  return "text-slate-500";
}

export default function LiveAnalysisConsole({ eventos, onLimpiar }) {
  const [filtro, setFiltro] = useState("todos");
  const [pausado, setPausado] = useState(false);
  const [snapshot, setSnapshot] = useState([]);
  const finRef = useRef(null);

  const visibles = (pausado ? snapshot : eventos).filter((ev) =>
    pasaFiltro(ev, filtro),
  );

  useEffect(() => {
    if (!pausado) finRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [visibles.length, pausado]);

  function togglePausa() {
    if (!pausado) setSnapshot(eventos);
    setPausado(!pausado);
  }

  return (
    <div className="overflow-hidden rounded-[14px] border border-[var(--t-border)] bg-[var(--t-bg-surface)]">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[var(--t-border)] bg-[var(--t-bg-base)] px-4 py-2.5">
        <div className="text-[.8rem] font-bold text-[var(--t-text)]">
          🖥️ Consola de Análisis en Vivo{" "}
          <span className="font-normal text-[var(--t-text-muted)]">
            ({visibles.length} eventos)
          </span>
        </div>
        <div className="flex items-center gap-2">
          <TabPills items={FILTROS} active={filtro} onChange={setFiltro} />
          <button
            onClick={togglePausa}
            className={`cursor-pointer rounded-full border px-3 py-1 font-[inherit] text-[.72rem] font-semibold ${
              pausado
                ? "border-amber-500 bg-amber-500/10 text-amber-500"
                : "border-[var(--t-border)] text-[var(--t-text-muted)]"
            }`}
          >
            {pausado ? "▶ Reanudar" : "⏸ Pausar"}
          </button>
          <button
            onClick={onLimpiar}
            className="cursor-pointer rounded-full border border-[var(--t-border)] px-3 py-1 font-[inherit] text-[.72rem] text-[var(--t-text-muted)]"
          >
            Limpiar
          </button>
        </div>
      </div>

      <div className="h-[420px] overflow-y-auto p-3 font-mono text-[.72rem]">
        {visibles.length === 0 ? (
          <div className="p-8 text-center text-[var(--t-text-muted)]">
            Sin eventos todavía. La consola se llena en tiempo real con la
            telemetría del backend.
          </div>
        ) : (
          visibles.map((ev, i) => (
            <div
              key={`${ev._ts}-${i}`}
              className="flex gap-2 border-b border-[var(--t-border)]/40 py-1"
            >
              <span className="shrink-0 text-slate-600">
                {new Date(ev._ts).toLocaleTimeString("es")}
              </span>
              <span className={`shrink-0 font-bold ${colorTipo(ev.tipo)}`}>
                [{ev.tipo || "evento"}]
              </span>
              <span className="min-w-0 flex-1 truncate text-[var(--t-text)]">
                {resumen(ev)}
              </span>
            </div>
          ))
        )}
        <div ref={finRef} />
      </div>
    </div>
  );
}
