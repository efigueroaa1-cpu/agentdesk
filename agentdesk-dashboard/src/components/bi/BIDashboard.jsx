/**
 * BIDashboard.jsx — Panel de Control Central (ID 9).
 *
 * Consume GET /sistema/salud para obtener KPIs maestros consolidados:
 *   score, Gantt, Finanzas, Compliance, Riesgo
 *
 * Diseño: cyber-dark con tarjetas por dominio y gauge de salud central.
 */

import { useState, useEffect, useCallback } from "react";
import {
  AreaChart, Area, BarChart, Bar,
  XAxis, YAxis, Tooltip, ResponsiveContainer, Cell,
} from "recharts";
import { API_BASE } from "../../services/agent.service";

const REFRESH_MS = 30_000;

// ── Palette ──────────────────────────────────────────────────────────────────
const C = {
  ok:       "#22c55e",
  warn:     "#f59e0b",
  critico:  "#ef4444",
  blue:     "#00d4ff",
  blueDim:  "rgba(0,212,255,0.12)",
  card:     "#0f1a2e",
  border:   "rgba(0,212,255,0.15)",
  text:     "#e2e8f0",
  muted:    "#64748b",
};

// ── Helpers ───────────────────────────────────────────────────────────────────
function scoreColor(s) {
  if (s >= 80) return C.ok;
  if (s >= 50) return C.warn;
  return C.critico;
}

function nivelColor(n) {
  if (n === "CRITICO") return C.critico;
  if (n === "ALTO")    return C.warn;
  return C.blue;
}

function fmt(n, dec = 1) {
  if (n == null) return "—";
  return Number(n).toLocaleString("es-CL", { maximumFractionDigits: dec });
}

// ── Gauge SVG ─────────────────────────────────────────────────────────────────
function HealthGauge({ score }) {
  const color  = scoreColor(score ?? 0);
  const radius = 54;
  const circ   = 2 * Math.PI * radius;
  const pct    = (score ?? 0) / 100;
  const dash   = circ * 0.75;    // arco 270°
  const offset = dash * (1 - pct);

  return (
    <svg width={160} height={120} viewBox="0 0 160 120" style={{ overflow: "visible" }}>
      {/* fondo del arco */}
      <circle
        cx={80} cy={90} r={radius}
        fill="none" stroke="rgba(255,255,255,0.08)" strokeWidth={12}
        strokeDasharray={`${dash} ${circ - dash}`}
        strokeDashoffset={circ * 0.375}
        strokeLinecap="round"
        transform="rotate(-135 80 90)"
      />
      {/* arco de progreso */}
      <circle
        cx={80} cy={90} r={radius}
        fill="none" stroke={color} strokeWidth={12}
        strokeDasharray={`${dash} ${circ - dash}`}
        strokeDashoffset={offset}
        strokeLinecap="round"
        transform="rotate(-135 80 90)"
        style={{ transition: "stroke-dashoffset .6s ease, stroke .4s" }}
      />
      <text x={80} y={88} textAnchor="middle"
            fill={color} fontSize={28} fontWeight={700} fontFamily="monospace">
        {score ?? "—"}
      </text>
      <text x={80} y={108} textAnchor="middle"
            fill={C.muted} fontSize={10} fontFamily="monospace">
        HEALTH SCORE
      </text>
    </svg>
  );
}

// ── KPI Card ─────────────────────────────────────────────────────────────────
function KPICard({ label, value, sub, color }) {
  return (
    <div style={{
      background: C.card, border: `1px solid ${C.border}`,
      borderRadius: 12, padding: "14px 18px",
      display: "flex", flexDirection: "column", gap: 4,
      minWidth: 130,
    }}>
      <span style={{ color: C.muted, fontSize: 11, textTransform: "uppercase", letterSpacing: ".06em" }}>
        {label}
      </span>
      <span style={{ color: color ?? C.blue, fontSize: 24, fontWeight: 700, fontFamily: "monospace" }}>
        {value}
      </span>
      {sub && <span style={{ color: C.muted, fontSize: 11 }}>{sub}</span>}
    </div>
  );
}

// ── Alerta Row ────────────────────────────────────────────────────────────────
function AlertRow({ a }) {
  return (
    <div style={{
      display: "grid", gridTemplateColumns: "60px 1fr auto",
      gap: 12, alignItems: "start",
      padding: "8px 0", borderBottom: `1px solid rgba(255,255,255,0.05)`,
    }}>
      <span style={{
        fontSize: 10, fontWeight: 700, letterSpacing: ".05em",
        color: nivelColor(a.nivel),
        background: `${nivelColor(a.nivel)}18`,
        border: `1px solid ${nivelColor(a.nivel)}44`,
        borderRadius: 6, padding: "2px 6px", textAlign: "center",
      }}>
        {a.nivel}
      </span>
      <div>
        <div style={{ color: C.text, fontSize: 12, fontWeight: 600 }}>
          {a.tarea_nombre ?? a.agente_id ?? "—"}
        </div>
        <div style={{ color: C.muted, fontSize: 11, marginTop: 2, lineHeight: 1.4 }}>
          {a.mensaje ?? a.razon ?? ""}
        </div>
      </div>
      <span style={{ color: C.muted, fontSize: 11, whiteSpace: "nowrap" }}>
        {a.impacto_financiero != null
          ? `$${fmt(a.impacto_financiero, 0)} ${a.moneda ?? "USD"}`
          : ""}
      </span>
    </div>
  );
}

// ── Sección ───────────────────────────────────────────────────────────────────
function Section({ title, children, accent }) {
  return (
    <div style={{
      background: C.card, border: `1px solid ${accent ?? C.border}`,
      borderRadius: 14, padding: "16px 20px",
    }}>
      <h3 style={{
        color: accent ?? C.blue, fontSize: 11, fontWeight: 700,
        letterSpacing: ".1em", textTransform: "uppercase",
        margin: "0 0 14px",
      }}>
        {title}
      </h3>
      {children}
    </div>
  );
}

// ── Proyectos Gantt mini-bar ──────────────────────────────────────────────────
function ProyectoBar({ p }) {
  const pct = p.resumen?.pct_avance ?? 0;
  return (
    <div style={{ marginBottom: 10 }}>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
        <span style={{ color: C.text, fontSize: 12 }}>{p.proyecto_id}</span>
        <span style={{ color: C.muted, fontSize: 11 }}>{fmt(pct, 0)}%</span>
      </div>
      <div style={{ background: "rgba(255,255,255,0.06)", borderRadius: 4, height: 6 }}>
        <div style={{
          height: 6, borderRadius: 4, width: `${Math.min(100, pct)}%`,
          background: pct >= 80 ? C.ok : pct >= 40 ? C.blue : C.warn,
          transition: "width .5s ease",
        }} />
      </div>
    </div>
  );
}

// ── BIDashboard ───────────────────────────────────────────────────────────────
export default function BIDashboard() {
  const [data,     setData]     = useState(null);
  const [loading,  setLoading]  = useState(true);
  const [error,    setError]    = useState(null);
  const [lastTs,   setLastTs]   = useState(null);

  const cargar = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/sistema/salud`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = await res.json();
      setData(json);
      setLastTs(new Date().toLocaleTimeString("es-CL"));
      setError(null);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    cargar();
    const t = setInterval(cargar, REFRESH_MS);
    return () => clearInterval(t);
  }, [cargar]);

  // ── Datos derivados ────────────────────────────────────────────────────────
  const score      = data?.score ?? null;
  const gantt      = data?.gantt ?? {};
  const finanzas   = data?.finanzas ?? {};
  const compliance = data?.compliance ?? {};
  const criticos   = data?.alertas_criticas ?? 0;
  const altas      = data?.alertas_altas ?? 0;

  // Preparar datos para gráfica de alertas por guardrail (compliance)
  const guardrailData = Object.entries(compliance.por_guardrail ?? {}).map(
    ([k, v]) => ({ name: k.replace("Guard", ""), value: v }),
  ).sort((a, b) => b.value - a.value).slice(0, 6);

  // Proyectos Gantt
  const proyectos = gantt.proyectos ?? [];

  // Alertas combinadas (riesgo + compliance)
  const alertasRiesgo = (gantt.proyectos ?? [])
    .flatMap(p => p.alertas ?? [])
    .filter(a => a.nivel === "CRITICO" || a.nivel === "ALTO")
    .slice(0, 6);

  const alertasCompliance = (compliance.alertas_nivel ?? [])
    .map(a => ({
      nivel:       a.nivel,
      agente_id:   a.agente_id,
      tarea_nombre: `Agente: ${a.agente_id}`,
      mensaje:     `${a.total_abortos} abortos — ${Object.entries(a.guardrails ?? {}).map(([k,v]) => `${k.replace("Guard","")}: ${v}`).join(", ")}`,
    }))
    .slice(0, 4);

  const alertasTotales = [...alertasRiesgo, ...alertasCompliance].slice(0, 8);

  // ── Render ─────────────────────────────────────────────────────────────────
  if (loading) return (
    <div style={{ display: "flex", justifyContent: "center", alignItems: "center",
                  height: 300, color: C.muted, fontFamily: "monospace", fontSize: 13 }}>
      Cargando KPIs maestros…
    </div>
  );

  if (error) return (
    <div style={{ padding: 24, background: C.card, borderRadius: 14,
                  border: "1px solid rgba(239,68,68,0.3)", color: "#ef4444",
                  fontFamily: "monospace", fontSize: 13 }}>
      Error al cargar salud del sistema: {error}
    </div>
  );

  return (
    <div style={{ fontFamily: "monospace", color: C.text, display: "flex",
                  flexDirection: "column", gap: 20 }}>

      {/* Header ──────────────────────────────────────────────────────────── */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between",
                    flexWrap: "wrap", gap: 12 }}>
        <div>
          <h2 style={{ margin: 0, color: C.blue, fontSize: 15, fontWeight: 700,
                       letterSpacing: ".1em", textTransform: "uppercase" }}>
            Central Control Panel
          </h2>
          <div style={{ color: C.muted, fontSize: 11, marginTop: 3 }}>
            Última actualización: {lastTs} · Auto-refresh cada 30 s
          </div>
        </div>
        <button
          onClick={cargar}
          style={{ padding: "6px 16px", borderRadius: 8, fontSize: 11, fontWeight: 700,
                   background: C.blueDim, border: `1px solid ${C.border}`,
                   color: C.blue, cursor: "pointer" }}
        >
          Actualizar
        </button>
      </div>

      {/* Gauge + KPIs ────────────────────────────────────────────────────── */}
      <div style={{ display: "flex", gap: 16, flexWrap: "wrap", alignItems: "center" }}>
        <div style={{
          background: C.card, border: `1px solid ${C.border}`,
          borderRadius: 14, padding: "20px 28px",
          display: "flex", flexDirection: "column", alignItems: "center", gap: 4,
        }}>
          <HealthGauge score={score} />
          <span style={{ color: C.muted, fontSize: 11 }}>
            {criticos > 0 ? `${criticos} crítico(s)` : altas > 0 ? `${altas} alto(s)` : "Sin alertas críticas"}
          </span>
        </div>

        <div style={{ display: "flex", gap: 12, flexWrap: "wrap", flex: 1 }}>
          <KPICard
            label="Proyectos"
            value={gantt.n_proyectos ?? "—"}
            sub="Activos en Gantt"
          />
          <KPICard
            label="Avance Global"
            value={gantt.avance_promedio != null ? `${fmt(gantt.avance_promedio)}%` : "—"}
            sub="Promedio de proyectos"
            color={gantt.avance_promedio >= 70 ? C.ok : C.warn}
          />
          <KPICard
            label="Flujo Neto"
            value={finanzas.flujo_neto != null
              ? `$${fmt(finanzas.flujo_neto, 0)}`
              : "—"}
            sub={`UF ${fmt(finanzas.uf_valor, 2)} · USD ${fmt(finanzas.dolar_valor, 0)}`}
            color={finanzas.flujo_neto >= 0 ? C.ok : C.critico}
          />
          <KPICard
            label="Certificado"
            value={compliance.certificado === true ? "✓ OK"
                 : compliance.certificado === false ? "✗ Riesgo"
                 : "—"}
            sub={`${compliance.total_eventos ?? 0} eventos guardados`}
            color={compliance.certificado ? C.ok : C.critico}
          />
          <KPICard
            label="Alertas Críticas"
            value={criticos + altas}
            sub={`${criticos} críticas · ${altas} altas`}
            color={criticos > 0 ? C.critico : altas > 0 ? C.warn : C.ok}
          />
        </div>
      </div>

      {/* Fila central: Gantt + Guardrails ───────────────────────────────── */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>

        {/* Progreso por proyecto */}
        <Section title="Avance de Proyectos Gantt">
          {proyectos.length === 0 ? (
            <div style={{ color: C.muted, fontSize: 12 }}>Sin proyectos activos.</div>
          ) : (
            proyectos.slice(0, 8).map(p => (
              <ProyectoBar key={p.proyecto_id} p={p} />
            ))
          )}
        </Section>

        {/* Guardrail aborts por tipo */}
        <Section title="Abortos por Guardrail (últimos 30 días)">
          {guardrailData.length === 0 ? (
            <div style={{ color: C.muted, fontSize: 12 }}>Sin eventos de guardrail registrados.</div>
          ) : (
            <ResponsiveContainer width="100%" height={180}>
              <BarChart data={guardrailData} barSize={22}
                        margin={{ top: 4, right: 4, bottom: 0, left: -28 }}>
                <XAxis dataKey="name" tick={{ fill: C.muted, fontSize: 10 }} />
                <YAxis tick={{ fill: C.muted, fontSize: 10 }} allowDecimals={false} />
                <Tooltip
                  contentStyle={{ background: C.card, border: `1px solid ${C.border}`,
                                  borderRadius: 8, fontSize: 12, color: C.text }}
                  cursor={{ fill: "rgba(255,255,255,0.04)" }}
                />
                <Bar dataKey="value" radius={[4, 4, 0, 0]}>
                  {guardrailData.map((d, i) => (
                    <Cell key={i}
                          fill={d.value >= 5 ? C.critico : d.value >= 2 ? C.warn : C.blue} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          )}
        </Section>
      </div>

      {/* Alertas activas ─────────────────────────────────────────────────── */}
      <Section
        title={`Alertas Activas (${alertasTotales.length})`}
        accent={alertasTotales.some(a => a.nivel === "CRITICO") ? C.critico : C.border}
      >
        {alertasTotales.length === 0 ? (
          <div style={{ color: C.ok, fontSize: 12 }}>
            ✓ Sin alertas activas. Sistema operando dentro de parámetros.
          </div>
        ) : (
          alertasTotales.map((a, i) => <AlertRow key={i} a={a} />)
        )}
      </Section>

      {/* Info pie ────────────────────────────────────────────────────────── */}
      {data?.generado_en && (
        <div style={{ textAlign: "right", color: C.muted, fontSize: 10 }}>
          Datos de servidor: {data.generado_en.replace("T", " ").slice(0, 19)} UTC
        </div>
      )}
    </div>
  );
}
