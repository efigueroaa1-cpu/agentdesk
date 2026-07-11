/**
 * TendenciasPanel.jsx — Análisis histórico de tendencias (BI tab).
 *
 * Muestra:
 *   - Flujo de caja histórico de un agente (GET /finanzas/historico/:id)
 *   - Tendencia: "mejora" / "empeora" / "estable"
 *   - Eventos de cumplimiento en el tiempo (GET /compliance/reporte)
 *   - Análisis de riesgo por proyecto (GET /riesgo/analisis/:pid)
 */

import { useState, useEffect, useCallback } from "react";
import {
  AreaChart, Area, LineChart, Line,
  XAxis, YAxis, Tooltip, Legend, ResponsiveContainer,
} from "recharts";
import { API_BASE } from "../../services/agent.service";

const C = {
  ok:      "#22c55e",
  warn:    "#f59e0b",
  critico: "#ef4444",
  blue:    "#00d4ff",
  purple:  "#a78bfa",
  card:    "#0f1a2e",
  border:  "rgba(0,212,255,0.15)",
  text:    "#e2e8f0",
  muted:   "#64748b",
};

function Section({ title, children }) {
  return (
    <div style={{
      background: C.card, border: `1px solid ${C.border}`,
      borderRadius: 14, padding: "16px 20px",
    }}>
      <h3 style={{ color: C.blue, fontSize: 11, fontWeight: 700,
                   letterSpacing: ".1em", textTransform: "uppercase",
                   margin: "0 0 14px" }}>
        {title}
      </h3>
      {children}
    </div>
  );
}

function TendenciaBadge({ t }) {
  const conf = {
    mejora:  { color: C.ok,      label: "▲ Mejora"  },
    empeora: { color: C.critico, label: "▼ Empeora" },
    estable: { color: C.warn,    label: "→ Estable"  },
  }[t] ?? { color: C.muted, label: "—" };

  return (
    <span style={{
      color: conf.color, fontSize: 11, fontWeight: 700,
      background: `${conf.color}18`,
      border: `1px solid ${conf.color}44`,
      borderRadius: 6, padding: "2px 8px",
    }}>
      {conf.label}
    </span>
  );
}

// ── Panel Finanzas Históricas ─────────────────────────────────────────────────
function HistoricoFinanciero({ agenteId }) {
  const [hist,      setHist]      = useState([]);
  const [tendencia, setTendencia] = useState(null);
  const [loading,   setLoading]   = useState(false);

  useEffect(() => {
    if (!agenteId) return;
    setLoading(true);
    Promise.all([
      fetch(`${API_BASE}/finanzas/historico/${encodeURIComponent(agenteId)}?n=12`).then(r => r.ok ? r.json() : []),
      fetch(`${API_BASE}/finanzas/tendencia/${encodeURIComponent(agenteId)}`).then(r => r.ok ? r.json() : null),
    ]).then(([h, t]) => {
      setHist(h ?? []);
      setTendencia(t?.tendencia ?? null);
    }).catch(() => {
      setHist([]);
    }).finally(() => setLoading(false));
  }, [agenteId]);

  const chartData = hist.map((h, i) => ({
    mes:      `#${hist.length - i}`,
    ingresos: h.flujo?.ingresos ?? 0,
    egresos:  h.flujo?.egresos  ?? 0,
    neto:     h.flujo_neto       ?? 0,
  })).reverse();

  if (loading) return <div style={{ color: C.muted, fontSize: 12 }}>Cargando histórico…</div>;
  if (!agenteId) return <div style={{ color: C.muted, fontSize: 12 }}>Selecciona un agente.</div>;
  if (hist.length === 0) return <div style={{ color: C.muted, fontSize: 12 }}>Sin análisis financieros guardados para este agente.</div>;

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 12 }}>
        <span style={{ color: C.muted, fontSize: 11 }}>Tendencia:</span>
        <TendenciaBadge t={tendencia} />
      </div>
      <ResponsiveContainer width="100%" height={200}>
        <AreaChart data={chartData} margin={{ top: 4, right: 4, bottom: 0, left: -20 }}>
          <defs>
            <linearGradient id="gIng" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%"  stopColor={C.ok}   stopOpacity={0.3} />
              <stop offset="95%" stopColor={C.ok}   stopOpacity={0}   />
            </linearGradient>
            <linearGradient id="gEgr" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%"  stopColor={C.critico} stopOpacity={0.3} />
              <stop offset="95%" stopColor={C.critico} stopOpacity={0}   />
            </linearGradient>
            <linearGradient id="gNeto" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%"  stopColor={C.blue} stopOpacity={0.25} />
              <stop offset="95%" stopColor={C.blue} stopOpacity={0}    />
            </linearGradient>
          </defs>
          <XAxis dataKey="mes" tick={{ fill: C.muted, fontSize: 10 }} />
          <YAxis tick={{ fill: C.muted, fontSize: 10 }} />
          <Tooltip
            contentStyle={{ background: C.card, border: `1px solid ${C.border}`,
                            borderRadius: 8, fontSize: 11, color: C.text }}
          />
          <Legend wrapperStyle={{ fontSize: 11, color: C.muted }} />
          <Area type="monotone" dataKey="ingresos" stroke={C.ok}      fill="url(#gIng)"  strokeWidth={1.5} />
          <Area type="monotone" dataKey="egresos"  stroke={C.critico} fill="url(#gEgr)"  strokeWidth={1.5} />
          <Area type="monotone" dataKey="neto"     stroke={C.blue}    fill="url(#gNeto)" strokeWidth={2}   />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

// ── Panel Cumplimiento Historial ──────────────────────────────────────────────
function ComplianceTrend() {
  const [reporte, setReporte] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch(`${API_BASE}/compliance/reporte?dias=90`)
      .then(r => r.ok ? r.json() : null)
      .then(d => setReporte(d))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <div style={{ color: C.muted, fontSize: 12 }}>Cargando compliance…</div>;
  if (!reporte) return <div style={{ color: C.muted, fontSize: 12 }}>Sin datos de compliance.</div>;

  const guardrailData = Object.entries(reporte.por_guardrail ?? {})
    .map(([k, v]) => ({ name: k.replace("Guard", ""), value: v }))
    .sort((a, b) => b.value - a.value);

  const agentData = Object.entries(reporte.por_agente ?? {})
    .map(([k, v]) => ({ name: k, value: Object.values(v).reduce((a, b) => a + b, 0) }))
    .sort((a, b) => b.value - a.value)
    .slice(0, 8);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={{ display: "flex", gap: 16, alignItems: "center", flexWrap: "wrap" }}>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <span style={{ color: C.muted, fontSize: 11 }}>Período:</span>
          <span style={{ color: C.text, fontSize: 12 }}>{reporte.periodo}</span>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <span style={{ color: C.muted, fontSize: 11 }}>Total eventos:</span>
          <span style={{ color: C.blue, fontSize: 14, fontWeight: 700, fontFamily: "monospace" }}>
            {reporte.total_eventos}
          </span>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <span style={{ color: C.muted, fontSize: 11 }}>Certificado:</span>
          <span style={{ color: reporte.certificado ? C.ok : C.critico, fontSize: 12, fontWeight: 700 }}>
            {reporte.certificado ? "✓ Emitido" : "✗ Denegado"}
          </span>
        </div>
      </div>

      {agentData.length > 0 && (
        <div>
          <div style={{ color: C.muted, fontSize: 11, marginBottom: 8 }}>Abortos por agente</div>
          <ResponsiveContainer width="100%" height={150}>
            <LineChart data={agentData} margin={{ top: 4, right: 8, bottom: 0, left: -24 }}>
              <XAxis dataKey="name" tick={{ fill: C.muted, fontSize: 9 }} />
              <YAxis tick={{ fill: C.muted, fontSize: 10 }} allowDecimals={false} />
              <Tooltip
                contentStyle={{ background: C.card, border: `1px solid ${C.border}`,
                                borderRadius: 8, fontSize: 11, color: C.text }}
              />
              <Line type="monotone" dataKey="value" stroke={C.warn}
                    dot={{ r: 3, fill: C.warn }} strokeWidth={2} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {reporte.sugerencias_temp?.length > 0 && (
        <div>
          <div style={{ color: C.warn, fontSize: 11, fontWeight: 700,
                        textTransform: "uppercase", letterSpacing: ".06em",
                        marginBottom: 8 }}>
            Sugerencias de temperatura
          </div>
          {reporte.sugerencias_temp.map((s, i) => (
            <div key={i} style={{
              padding: "8px 12px", borderRadius: 8, marginBottom: 6,
              background: "rgba(245,158,11,0.08)",
              border: "1px solid rgba(245,158,11,0.25)",
            }}>
              <div style={{ color: C.text, fontSize: 12, fontWeight: 600 }}>
                {s.agente_nombre}
              </div>
              <div style={{ color: C.muted, fontSize: 11, marginTop: 2 }}>
                {s.razon}
              </div>
              <code style={{ color: C.warn, fontSize: 10 }}>{s.accion}</code>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── TendenciasPanel ───────────────────────────────────────────────────────────
export default function TendenciasPanel() {
  const [agentes,   setAgentes]   = useState([]);
  const [agenteId,  setAgenteId]  = useState("");

  useEffect(() => {
    fetch(`${API_BASE}/agentes`)
      .then(r => r.ok ? r.json() : [])
      .then(data => {
        const lista = Array.isArray(data) ? data : (data.agentes ?? []);
        setAgentes(lista);
        if (lista.length > 0 && !agenteId) setAgenteId(lista[0].id ?? lista[0].agente_id ?? "");
      })
      .catch(() => {});
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div style={{ fontFamily: "monospace", color: C.text,
                  display: "flex", flexDirection: "column", gap: 20 }}>
      <h2 style={{ margin: 0, color: C.blue, fontSize: 14, fontWeight: 700,
                   letterSpacing: ".1em", textTransform: "uppercase" }}>
        Tendencias Históricas
      </h2>

      {/* Selector de agente */}
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <label style={{ color: C.muted, fontSize: 11 }}>Agente:</label>
        <select
          value={agenteId}
          onChange={e => setAgenteId(e.target.value)}
          style={{
            background: C.card, border: `1px solid ${C.border}`,
            color: C.text, borderRadius: 8, padding: "5px 10px",
            fontSize: 12, fontFamily: "monospace",
          }}
        >
          {agentes.length === 0 && <option value="">Sin agentes</option>}
          {agentes.map(a => (
            <option key={a.id ?? a.agente_id} value={a.id ?? a.agente_id}>
              {a.nombre ?? a.id ?? a.agente_id}
            </option>
          ))}
        </select>
      </div>

      {/* Flujo de caja histórico */}
      <Section title="Flujo de Caja Histórico">
        <HistoricoFinanciero agenteId={agenteId} />
      </Section>

      {/* Compliance 90 días */}
      <Section title="Cumplimiento de Guardrails (90 días)">
        <ComplianceTrend />
      </Section>
    </div>
  );
}
