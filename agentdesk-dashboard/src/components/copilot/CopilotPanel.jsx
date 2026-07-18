/**
 * CopilotPanel.jsx — Copiloto de Intención (Fase 27, ADR-0025).
 * El operador escribe un OBJETIVO en lenguaje natural; el motor propone un
 * plan (pasos, habilidades Hermes, acciones OT ya filtradas por límites
 * físicos, tareas Gantt) y con un clic lo inserta en el Gantt P6 con el
 * impacto en Curva S. Las acciones OT SIEMPRE van a la bandeja de
 * aprobación (Human-in-the-loop, ADR-0024) — el Copiloto nunca ejecuta.
 */
import { useState } from "react";
import { API_BASE } from "../../services/agent.service";

export default function CopilotPanel() {
  const [objetivo, setObjetivo] = useState("");
  const [proyectoId, setProyectoId] = useState("");
  const [plan, setPlan] = useState(null);
  const [resultado, setResultado] = useState(null);
  const [error, setError] = useState("");
  const [ocupado, setOcupado] = useState(false);
  const token = sessionStorage.getItem("agentdesk-jwt-token");
  const headers = {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };

  const planificar = async () => {
    setOcupado(true);
    setError("");
    setResultado(null);
    try {
      const r = await fetch(`${API_BASE}/copiloto/planificar`, {
        method: "POST",
        headers,
        body: JSON.stringify({ objetivo, proyecto_id: proyectoId }),
      });
      const data = await r.json();
      if (!r.ok) throw new Error(data.detail ?? "Error al planificar.");
      setPlan(data);
    } catch (e) {
      setError(e.message);
    } finally {
      setOcupado(false);
    }
  };

  const aplicar = async () => {
    setOcupado(true);
    setError("");
    try {
      const r = await fetch(`${API_BASE}/copiloto/aplicar`, {
        method: "POST",
        headers,
        body: JSON.stringify({ plan, proyecto_id: proyectoId }),
      });
      const data = await r.json();
      if (!r.ok) throw new Error(data.detail ?? "Error al aplicar.");
      setResultado(data);
    } catch (e) {
      setError(e.message);
    } finally {
      setOcupado(false);
    }
  };

  return (
    <div className="flex flex-col gap-4">
      <div className="rounded-xl border border-[var(--t-border)] bg-[var(--t-bg-base)] p-5">
        <div className="mb-2 text-[.95rem] font-bold text-[var(--t-text)]">
          🧭 Copiloto de Intención
        </div>
        <p className="mb-3 text-[.78rem] text-[var(--t-text-muted)]">
          Describe tu objetivo en lenguaje natural. El Copiloto propone el plan:
          tareas, habilidades aprendidas y acciones OT (siempre con aprobación
          del operador). Tú decides; nada se ejecuta solo.
        </p>
        <textarea
          value={objetivo}
          onChange={(e) => setObjetivo(e.target.value)}
          placeholder="Ej: Optimizar el consumo de la línea 4 tras el reporte de fallas"
          rows={3}
          className="mb-2 w-full rounded-lg border border-[var(--t-border)] bg-[var(--t-bg-deep)] p-3 text-[.85rem] text-[var(--t-text)] outline-none"
        />
        <div className="flex flex-wrap items-center gap-2">
          <input
            value={proyectoId}
            onChange={(e) => setProyectoId(e.target.value)}
            placeholder="ID de proyecto Gantt (opcional para planificar)"
            className="min-w-60 flex-1 rounded-lg border border-[var(--t-border)] bg-[var(--t-bg-deep)] px-3 py-2 text-[.8rem] text-[var(--t-text)] outline-none"
          />
          <button
            onClick={planificar}
            disabled={ocupado || !objetivo.trim()}
            className="cursor-pointer rounded-lg border border-[var(--t-accent)] bg-[var(--t-bg-accent)] px-4 py-2 text-[.8rem] font-semibold text-[var(--t-accent)] disabled:opacity-50"
          >
            {ocupado ? "Pensando…" : "Proponer plan"}
          </button>
        </div>
        {error && (
          <div className="mt-2 text-[.78rem] text-neon-red">{error}</div>
        )}
      </div>

      {plan && (
        <div className="rounded-xl border border-[var(--t-border)] bg-[var(--t-bg-base)] p-5">
          <div className="mb-1 flex items-center justify-between">
            <span className="text-[.88rem] font-bold text-[var(--t-text)]">
              Plan propuesto{" "}
              <span className="text-[.68rem] font-normal text-[var(--t-text-muted)]">
                (origen: {plan.origen})
              </span>
            </span>
            <button
              onClick={aplicar}
              disabled={ocupado || !proyectoId.trim()}
              title={
                proyectoId.trim()
                  ? "Insertar en Gantt y proponer acciones OT"
                  : "Indica el ID de proyecto Gantt para aplicar"
              }
              className="cursor-pointer rounded-lg border border-neon-green/50 bg-neon-green/10 px-4 py-1.5 text-[.78rem] font-semibold text-neon-green disabled:opacity-50"
            >
              Aplicar en Gantt P6
            </button>
          </div>

          <ol className="mb-3 list-decimal pl-5">
            {plan.pasos.map((p, i) => (
              <li key={i} className="mb-1 text-[.8rem] text-[var(--t-text)]">
                <strong>{p.titulo}</strong>
                <span className="text-[var(--t-text-muted)]">
                  {" "}
                  — {p.descripcion} ({p.duracion_dias} d
                  {p.agente_sugerido ? ` · ${p.agente_sugerido}` : ""})
                </span>
              </li>
            ))}
          </ol>

          {plan.habilidades.length > 0 && (
            <div className="mb-2 text-[.76rem] text-[var(--t-text-muted)]">
              🧠 Habilidades Hermes: {plan.habilidades.join(", ")}
            </div>
          )}

          {plan.acciones_ot.map((a, i) => (
            <div
              key={i}
              className="mb-1 rounded-lg border border-amber-500/40 bg-amber-500/[.05] px-3 py-2 text-[.78rem] text-amber-500"
            >
              🦾 Acción OT validada: {a.adaptador}.{a.tag_id} = {a.valor} —{" "}
              {a.justificacion}
              <span className="ml-1 text-[.68rem]">
                (requiere aprobación en Monitor → Acciones OT)
              </span>
            </div>
          ))}

          {plan.descartadas_por_filtro.map((a, i) => (
            <div
              key={i}
              className="mb-1 rounded-lg border border-neon-red/40 bg-neon-red/[.05] px-3 py-2 text-[.78rem] text-neon-red"
            >
              ⛔ Descartada por filtro de seguridad: {a.tag_id} = {a.valor} (
              {a.motivo_descarte})
            </div>
          ))}
        </div>
      )}

      {resultado && (
        <div className="rounded-xl border border-neon-green/40 bg-neon-green/[.04] p-5 text-[.8rem] text-[var(--t-text)]">
          <div className="mb-1 font-bold text-neon-green">
            ✅ Plan aplicado: {resultado.tareas_creadas.length} tareas en el
            Gantt · {resultado.propuestas_ot.length} acción(es) OT en la bandeja
            de aprobación
          </div>
          <div className="text-[.74rem] text-[var(--t-text-muted)]">
            Curva S — BAC antes: {resultado.impacto_curva_s.antes?.bac ?? "—"} →
            después: {resultado.impacto_curva_s.despues?.bac ?? "—"}
          </div>
        </div>
      )}
    </div>
  );
}
