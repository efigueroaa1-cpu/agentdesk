/**
 * OTAccionesTab.jsx — Bandeja de aprobación Human-in-the-loop (ADR-0024).
 * Propuestas de comando OT de los agentes: el operador (supervisor+) las
 * aprueba o rechaza; nada se escribe a la planta sin ese clic.
 */
import { useCallback, useEffect, useState } from "react";
import { API_BASE } from "../../services/agent.service";

const ESTADO_CLS = {
  pendiente: "border-amber-500/40 bg-amber-500/[.05] text-amber-500",
  ejecutada: "border-neon-green/40 bg-neon-green/[.05] text-neon-green",
  rechazada: "border-slate-500/40 bg-slate-500/[.05] text-slate-400",
  expirada: "border-slate-500/40 bg-slate-500/[.05] text-slate-400",
  fallida: "border-neon-red/40 bg-neon-red/[.05] text-neon-red",
};

export default function OTAccionesTab() {
  const [acciones, setAcciones] = useState([]);
  const [error, setError] = useState("");
  const [ocupado, setOcupado] = useState(0);
  const token = sessionStorage.getItem("agentdesk-jwt-token");
  const headers = token ? { Authorization: `Bearer ${token}` } : {};

  const cargar = useCallback(async () => {
    try {
      const r = await fetch(`${API_BASE}/ot/acciones`, { headers });
      if (r.status === 403) {
        setError(
          "Se requiere rol supervisor o admin para ver las acciones OT.",
        );
        return;
      }
      const data = await r.json();
      setAcciones(data.acciones ?? []);
      setError("");
    } catch {
      setError("API no disponible.");
    }
  }, [token]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    cargar();
    const t = setInterval(cargar, 10000);
    return () => clearInterval(t);
  }, [cargar]);

  const resolver = async (id, verbo) => {
    setOcupado(id);
    try {
      const r = await fetch(`${API_BASE}/ot/acciones/${id}/${verbo}`, {
        method: "POST",
        headers,
      });
      const data = await r.json();
      if (!r.ok) setError(data.detail ?? `Error al ${verbo}.`);
      await cargar();
    } catch {
      setError("API no disponible.");
    } finally {
      setOcupado(0);
    }
  };

  if (error)
    return (
      <div className="rounded-xl border border-neon-red/25 bg-neon-red/[.03] p-4 text-[.82rem] text-neon-red">
        {error}
      </div>
    );

  if (acciones.length === 0)
    return (
      <div className="rounded-xl border-2 border-dashed border-[var(--t-border)] p-8 text-center text-[.85rem] text-[var(--t-text-muted)]">
        Sin propuestas de comando OT. Los agentes proponen; tú decides.
      </div>
    );

  return (
    <div className="flex flex-col gap-2">
      {acciones.map((a) => (
        <div
          key={a.id}
          className={`rounded-xl border px-4 py-3 ${ESTADO_CLS[a.estado] ?? ESTADO_CLS.rechazada}`}
        >
          <div className="mb-1 flex items-center justify-between gap-2">
            <span className="text-[.82rem] font-bold">
              #{a.id} · {a.adaptador}.{a.tag_id} = {a.valor}
            </span>
            <span className="text-[.68rem] uppercase">{a.estado}</span>
          </div>
          <div className="text-[.78rem] text-[var(--t-text-muted)]">
            {a.justificacion}
            <span className="ml-2 text-[.68rem]">
              (agente: {a.agente_id || "—"} ·{" "}
              {new Date(a.creada * 1000).toLocaleString("es")})
            </span>
          </div>
          {a.estado === "pendiente" && (
            <div className="mt-2 flex gap-2">
              <button
                onClick={() => resolver(a.id, "aprobar")}
                disabled={ocupado === a.id}
                className="cursor-pointer rounded-lg border border-neon-green/50 bg-neon-green/10 px-3 py-1 text-[.74rem] font-semibold text-neon-green"
              >
                Aprobar y ejecutar
              </button>
              <button
                onClick={() => resolver(a.id, "rechazar")}
                disabled={ocupado === a.id}
                className="cursor-pointer rounded-lg border border-neon-red/50 bg-neon-red/10 px-3 py-1 text-[.74rem] font-semibold text-neon-red"
              >
                Rechazar
              </button>
            </div>
          )}
          {a.resultado && (
            <div className="mt-1 text-[.7rem] text-[var(--t-text-muted)]">
              Resultado: {a.resultado.ok ? "OK" : "FALLO"} —{" "}
              {a.resultado.detalle}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
