/**
 * DiagnosticsPanel.jsx — Módulo Diagnóstico (Fase 9, ADR-0007).
 * Estado OPEN/CLOSED de los Circuit Breakers y latencia por proveedor LLM
 * en tiempo real (poll 5s a /diagnostico/llm), y trazas de auditoría IA
 * recientes (/auditoria/interacciones, requiere rol supervisor+).
 */
import { useState, useEffect, useCallback } from "react";
import { API_BASE } from "../../services/agent.service";

const POLL_MS = 5000;

function authHeaders() {
  const token = sessionStorage.getItem("agentdesk-jwt-token");
  return token ? { Authorization: `Bearer ${token}` } : {};
}

function ProviderCard({ nombre, info }) {
  const abierto = info.estado === "OPEN";
  const cls = abierto
    ? "border-neon-red/40 bg-neon-red/[.05]"
    : "border-neon-green/40 bg-neon-green/[.05]";
  return (
    <div className={`rounded-xl border-2 px-4 py-3.5 ${cls}`}>
      <div className="flex items-center justify-between">
        <span className="text-sm font-extrabold uppercase tracking-wide text-[var(--t-text)]">
          {nombre}
        </span>
        <span
          className={`rounded-full px-2.5 py-0.5 text-[.68rem] font-black ${
            abierto ? "bg-neon-red text-white" : "bg-neon-green text-cyber-900"
          }`}
        >
          {abierto ? "● OPEN" : "● CLOSED"}
        </span>
      </div>
      <div className="mt-2 grid grid-cols-2 gap-1 text-[.72rem] text-[var(--t-text-muted)]">
        <span>Latencia prom.</span>
        <span className="text-right font-mono text-[var(--t-text)]">
          {info.latencia_prom_s != null ? `${info.latencia_prom_s}s` : "—"}
        </span>
        <span>Última latencia</span>
        <span className="text-right font-mono text-[var(--t-text)]">
          {info.latencia_ultima_s != null ? `${info.latencia_ultima_s}s` : "—"}
        </span>
        <span>Fallos seguidos</span>
        <span className="text-right font-mono text-[var(--t-text)]">
          {info.fallos_consecutivos}
        </span>
        {abierto && (
          <>
            <span>Reabre en</span>
            <span className="text-right font-mono text-neon-red">
              {info.reabre_en_s}s
            </span>
          </>
        )}
      </div>
      {info.ultimo_error && (
        <div
          className="mt-2 truncate text-[.68rem] text-amber-500"
          title={info.ultimo_error}
        >
          ⚠ {info.ultimo_error}
        </div>
      )}
    </div>
  );
}

export default function DiagnosticsPanel() {
  const [circuitos, setCircuitos] = useState({});
  const [cadena, setCadena] = useState([]);
  const [trazas, setTrazas] = useState(null); // null = sin permiso/cargando

  const cargar = useCallback(async () => {
    try {
      const r = await fetch(`${API_BASE}/diagnostico/llm`).then((x) =>
        x.json(),
      );
      setCircuitos(r.circuitos || {});
      setCadena(r.cadena || []);
    } catch {
      /* backend fuera de línea: se reintenta en el próximo poll */
    }
    try {
      const a = await fetch(`${API_BASE}/auditoria/interacciones?limit=15`, {
        headers: authHeaders(),
      });
      setTrazas(a.ok ? (await a.json()).interacciones : null);
    } catch {
      setTrazas(null);
    }
  }, []);

  useEffect(() => {
    cargar();
    const t = setInterval(cargar, POLL_MS);
    return () => clearInterval(t);
  }, [cargar]);

  return (
    <div className="flex flex-col gap-5">
      <div>
        <h3 className="mb-1 text-base font-extrabold text-[var(--t-text)]">
          🩺 Circuit Breakers — cadena de inteligencia
        </h3>
        <p className="mb-3 text-[.75rem] text-[var(--t-text-muted)]">
          Fallback automático: {cadena.join(" → ") || "…"} · CLOSED = operativo,
          OPEN = aislado por fallos/latencia (se recupera solo).
        </p>
        <div className="grid grid-cols-[repeat(auto-fill,minmax(220px,1fr))] gap-3">
          {cadena.map((p) => (
            <ProviderCard key={p} nombre={p} info={circuitos[p] || {}} />
          ))}
        </div>
      </div>

      <div>
        <h3 className="mb-1 text-base font-extrabold text-[var(--t-text)]">
          📜 Auditoría IA — trazas recientes
        </h3>
        {trazas === null ? (
          <p className="text-[.78rem] text-[var(--t-text-muted)]">
            Requiere rol supervisor o admin (inicia sesión con permisos para ver
            las trazas forenses).
          </p>
        ) : (
          <div className="overflow-x-auto rounded-xl border border-[var(--t-border)]">
            <table className="w-full text-[.72rem]">
              <thead className="bg-[var(--t-bg-surface)] text-left text-[var(--t-text-muted)]">
                <tr>
                  {[
                    "Fecha",
                    "Usuario",
                    "Agente",
                    "Tipo",
                    "Tokens",
                    "Guardrail",
                    "OK",
                  ].map((h) => (
                    <th key={h} className="px-3 py-2 font-semibold">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="text-[var(--t-text)]">
                {trazas.map((t) => (
                  <tr key={t.id} className="border-t border-[var(--t-border)]">
                    <td className="px-3 py-1.5 font-mono">
                      {(t.ts || "").slice(0, 19).replace("T", " ")}
                    </td>
                    <td className="px-3 py-1.5">{t.user_id}</td>
                    <td className="px-3 py-1.5">{t.agente_id}</td>
                    <td className="px-3 py-1.5">{t.tipo}</td>
                    <td className="px-3 py-1.5 text-right font-mono">
                      {t.costo_estimado}
                    </td>
                    <td className="px-3 py-1.5">{t.veredicto_guardrail}</td>
                    <td className="px-3 py-1.5">{t.exitoso ? "✅" : "❌"}</td>
                  </tr>
                ))}
                {trazas.length === 0 && (
                  <tr>
                    <td
                      colSpan={7}
                      className="px-3 py-4 text-center text-[var(--t-text-muted)]"
                    >
                      Sin interacciones registradas todavía.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
