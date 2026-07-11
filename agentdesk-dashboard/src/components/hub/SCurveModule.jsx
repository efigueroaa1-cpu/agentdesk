/**
 * SCurveModule.jsx — Curva S de Valor Ganado (EVM) (ID 17)
 *
 * Muestra tres curvas acumuladas:
 *   PV  (Planned Value)   — línea blanca/gris: avance planificado × presupuesto
 *   EV  (Earned Value)    — línea cyan:        avance real × presupuesto
 *   AC  (Actual Cost)     — línea naranja:     costo real incurrido
 *
 * KPIs: SPI, CPI, SV, CV, EAC, VAC, BAC
 *
 * Flujo:
 *   1. Usuario selecciona un proyecto_id.
 *   2. React llama a GET /analytics/curva-s/:id (requiere token supervisor+).
 *   3. El backend calcula EVM en su hilo y responde + broadcast WS.
 *   4. Si alerta CRITICO/ALTO → notificación nativa vía tauri-plugin-notification.
 *
 * Requisito de ingeniería Sprint 8: cálculo en backend, no en UI thread.
 */

import { useState, useEffect, useRef, useCallback } from "react";
import {
  ComposedChart, Area, Line, XAxis, YAxis,
  Tooltip, Legend, ReferenceLine, ResponsiveContainer,
} from "recharts";
import { TrendingDown, TrendingUp, Minus, RefreshCw, Download, AlertTriangle } from "lucide-react";
import { API_BASE, AgentService } from "../../services/agent.service";

// ── Palette ──────────────────────────────────────────────────────────────────
const C = {
  pv:      "#94a3b8",   // gris-slate: valor planificado
  ev:      "#00d4ff",   // cyan:       valor ganado
  ac:      "#f59e0b",   // ámbar:      costo real
  ok:      "#22c55e",
  warn:    "#f59e0b",
  critico: "#ef4444",
  card:    "rgba(10,20,40,0.9)",
  border:  "rgba(0,212,255,0.2)",
  text:    "#e2e8f0",
  muted:   "#64748b",
};

// ── Helpers ───────────────────────────────────────────────────────────────────
function fmt(n, dec = 0) {
  if (n == null) return "—";
  return Number(n).toLocaleString("es-CL", {
    minimumFractionDigits: dec,
    maximumFractionDigits: dec,
  });
}

function fmtPct(n) {
  if (n == null) return "—";
  return `${Number(n).toFixed(1)}%`;
}

function indexColor(v, umbralOk = 1.0, umbralWarn = 0.9) {
  if (v >= umbralOk) return C.ok;
  if (v >= umbralWarn) return C.warn;
  return C.critico;
}

// ── Insignia de tendencia ─────────────────────────────────────────────────────
function KPIBadge({ label, value, color, sub }) {
  return (
    <div style={{
      background: "rgba(0,0,0,0.3)", border: `1px solid ${color}33`,
      borderRadius: 10, padding: "10px 14px", minWidth: 100,
    }}>
      <div style={{ color: C.muted, fontSize: 10, textTransform: "uppercase",
                    letterSpacing: ".07em", marginBottom: 4 }}>
        {label}
      </div>
      <div style={{ color, fontSize: 22, fontWeight: 700, fontFamily: "monospace", lineHeight: 1 }}>
        {value}
      </div>
      {sub && <div style={{ color: C.muted, fontSize: 10, marginTop: 4 }}>{sub}</div>}
    </div>
  );
}

// ── Tooltip personalizado ─────────────────────────────────────────────────────
function CustomTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div style={{
      background: C.card, border: `1px solid ${C.border}`,
      borderRadius: 10, padding: "10px 14px", fontSize: 12,
    }}>
      <div style={{ color: C.muted, marginBottom: 6 }}>{label}</div>
      {payload.map(p => (
        <div key={p.dataKey} style={{ color: p.color, marginBottom: 3 }}>
          {p.name}: ${fmt(p.value)}
        </div>
      ))}
    </div>
  );
}

// ── Panel de alertas ──────────────────────────────────────────────────────────
function AlertaBanner({ alerta, kpis }) {
  if (!alerta) return null;
  const esCritico = alerta === "CRITICO";
  const color     = esCritico ? C.critico : C.warn;
  return (
    <div style={{
      display: "flex", alignItems: "flex-start", gap: 10,
      padding: "10px 14px", borderRadius: 10, marginBottom: 12,
      background: `${color}14`, border: `1px solid ${color}55`,
    }}>
      <AlertTriangle size={16} style={{ color, flexShrink: 0, marginTop: 1 }} />
      <div>
        <div style={{ color, fontSize: 12, fontWeight: 700 }}>
          Desvío {alerta} detectado
        </div>
        <div style={{ color: C.muted, fontSize: 11, marginTop: 2 }}>
          SPI={kpis?.spi?.toFixed(2)} · CPI={kpis?.cpi?.toFixed(2)} —
          {esCritico
            ? " El proyecto está fuera de control. Se requiere acción inmediata."
            : " Revisar avance y presupuesto. Riesgo de desviación significativa."}
        </div>
      </div>
    </div>
  );
}

// ── SCurveModule ──────────────────────────────────────────────────────────────
export default function SCurveModule() {
  const [proyectos,    setProyectos]    = useState([]);
  const [proyectoId,   setProyectoId]   = useState("");
  const [datos,        setDatos]        = useState(null);
  const [loading,      setLoading]      = useState(false);
  const [error,        setError]        = useState(null);
  const [mostrarFutu,  setMostrarFutu]  = useState(true);
  const wsRef = useRef(null);

  // ── Cargar proyectos disponibles ─────────────────────────────────────────
  useEffect(() => {
    fetch(`${API_BASE}/gantt/proyectos`)
      .then(r => r.ok ? r.json() : [])
      .then(lista => {
        setProyectos(lista);
        if (lista.length > 0 && !proyectoId) setProyectoId(lista[0].proyecto_id);
      })
      .catch(() => {});
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Calcular Curva S ────────────────────────────────────────────────────
  const calcular = useCallback(async (pid) => {
    if (!pid) return;
    setLoading(true);
    setError(null);
    try {
      const token = localStorage.getItem("token") || sessionStorage.getItem("token") || "";
      const res   = await fetch(`${API_BASE}/analytics/curva-s/${encodeURIComponent(pid)}`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (res.status === 403) {
        setError("Se requiere rol supervisor o admin para ver la Curva S.");
        return;
      }
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = await res.json();
      setDatos(json);

      // Notificación nativa si hay alerta crítica
      if (json.alerta) {
        const kpis = json.kpis ?? {};
        AgentService.sendNotification(
          `Desvío ${json.alerta} — Proyecto ${pid}`,
          `SPI=${kpis.spi?.toFixed(2)} · CPI=${kpis.cpi?.toFixed(2)}`,
        ).catch(() => {});
      }
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (proyectoId) calcular(proyectoId);
  }, [proyectoId, calcular]);

  // ── WebSocket: recibir actualizaciones en tiempo real ───────────────────
  useEffect(() => {
    const ws = new WebSocket(`ws://${window.location.hostname}:8000/ws/telemetria`);
    wsRef.current = ws;

    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data);
        if (msg.tipo === "curva_s_actualizada" && msg.proyecto_id === proyectoId) {
          setDatos(prev => prev ? { ...prev, kpis: msg.kpis, curva: msg.curva, alerta: msg.alerta } : prev);
        }
        if (msg.tipo === "curva_s_alerta" && msg.proyecto_id === proyectoId) {
          AgentService.sendNotification(msg.titulo, msg.cuerpo).catch(() => {});
        }
      } catch { /* ignorar */ }
    };

    return () => { try { ws.close(); } catch { /* noop */ } };
  }, [proyectoId]);

  // ── Datos para el gráfico ─────────────────────────────────────────────
  const curvaFiltrada = (datos?.curva ?? []).filter(p => mostrarFutu || !p.es_futuro);
  const kpis          = datos?.kpis ?? {};
  const alerta        = datos?.alerta ?? null;

  // Línea divisoria "hoy"
  const hoyLabel = curvaFiltrada.find(p => !p.es_futuro)
    ? curvaFiltrada.filter(p => !p.es_futuro).slice(-1)[0]?.fecha
    : null;

  return (
    <div style={{
      fontFamily: "monospace", color: C.text,
      display: "flex", flexDirection: "column", gap: 16,
    }}>
      {/* Header ─────────────────────────────────────────────────────────── */}
      <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
        <div>
          <h2 style={{ margin: 0, color: C.ev, fontSize: 14, fontWeight: 700,
                       letterSpacing: ".1em", textTransform: "uppercase" }}>
            Curva S — Valor Ganado (EVM)
          </h2>
          <div style={{ color: C.muted, fontSize: 11, marginTop: 2 }}>
            Avance planificado vs. real vs. costo incurrido
          </div>
        </div>

        <div style={{ marginLeft: "auto", display: "flex", gap: 8, flexWrap: "wrap" }}>
          {/* Selector de proyecto */}
          <select
            value={proyectoId}
            onChange={e => setProyectoId(e.target.value)}
            style={{
              background: C.card, border: `1px solid ${C.border}`,
              color: C.text, borderRadius: 8, padding: "5px 10px",
              fontSize: 12, fontFamily: "monospace",
            }}
          >
            {proyectos.length === 0 && <option value="">Sin proyectos</option>}
            {proyectos.map(p => (
              <option key={p.proyecto_id} value={p.proyecto_id}>
                {p.proyecto_id}
              </option>
            ))}
          </select>

          {/* Toggle futuro */}
          <button
            onClick={() => setMostrarFutu(v => !v)}
            style={{
              padding: "5px 12px", borderRadius: 8, fontSize: 11, fontWeight: 600,
              background: mostrarFutu ? "rgba(0,212,255,0.15)" : "rgba(255,255,255,0.05)",
              border: `1px solid ${mostrarFutu ? C.ev : C.muted}`,
              color: mostrarFutu ? C.ev : C.muted, cursor: "pointer",
            }}
          >
            {mostrarFutu ? "Ocultar proyección" : "Mostrar proyección"}
          </button>

          {/* Recalcular */}
          <button
            onClick={() => calcular(proyectoId)}
            disabled={loading || !proyectoId}
            style={{
              padding: "5px 12px", borderRadius: 8, fontSize: 11, fontWeight: 600,
              background: "rgba(0,212,255,0.1)", border: `1px solid ${C.border}`,
              color: C.ev, cursor: loading ? "wait" : "pointer",
              opacity: loading ? 0.6 : 1,
              display: "flex", alignItems: "center", gap: 6,
            }}
          >
            <RefreshCw size={12} style={{ animation: loading ? "spin 1s linear infinite" : "none" }} />
            Recalcular
          </button>
        </div>
      </div>

      {/* Error ─────────────────────────────────────────────────────────── */}
      {error && (
        <div style={{ padding: "10px 14px", borderRadius: 10, color: C.critico,
                      background: `${C.critico}12`, border: `1px solid ${C.critico}44`,
                      fontSize: 12 }}>
          {error}
        </div>
      )}

      {/* Alerta de desvío ───────────────────────────────────────────────── */}
      {datos && <AlertaBanner alerta={alerta} kpis={kpis} />}

      {/* KPI Cards ──────────────────────────────────────────────────────── */}
      {datos && (
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
          <KPIBadge
            label="SPI"
            value={kpis.spi?.toFixed(3) ?? "—"}
            color={indexColor(kpis.spi ?? 1)}
            sub={kpis.spi >= 1 ? "En plazo" : kpis.spi >= 0.9 ? "Leve atraso" : "Atraso crítico"}
          />
          <KPIBadge
            label="CPI"
            value={kpis.cpi?.toFixed(3) ?? "—"}
            color={indexColor(kpis.cpi ?? 1)}
            sub={kpis.cpi >= 1 ? "Bajo presupuesto" : kpis.cpi >= 0.9 ? "Leve sobrecosto" : "Sobrecosto crítico"}
          />
          <KPIBadge
            label="BAC"
            value={`$${fmt(kpis.bac)}`}
            color={C.pv}
            sub="Presupuesto total"
          />
          <KPIBadge
            label="EV"
            value={`$${fmt(kpis.ev)}`}
            color={C.ev}
            sub={`${fmtPct(kpis.pct_completado_global)} completado`}
          />
          <KPIBadge
            label="AC"
            value={`$${fmt(kpis.ac)}`}
            color={C.ac}
            sub="Costo real acumulado"
          />
          <KPIBadge
            label="EAC"
            value={`$${fmt(kpis.eac)}`}
            color={indexColor(kpis.cpi ?? 1)}
            sub="Estimado al cierre"
          />
          <KPIBadge
            label="VAC"
            value={`$${fmt(kpis.vac)}`}
            color={kpis.vac >= 0 ? C.ok : C.critico}
            sub={kpis.vac >= 0 ? "Ahorro proyectado" : "Sobrecosto proyectado"}
          />
          <KPIBadge
            label="SV"
            value={`$${fmt(kpis.sv)}`}
            color={kpis.sv >= 0 ? C.ok : C.warn}
            sub="Varianza cronograma"
          />
        </div>
      )}

      {/* Gráfico Curva S ────────────────────────────────────────────────── */}
      <div style={{
        background: C.card, border: `1px solid ${C.border}`,
        borderRadius: 14, padding: "20px 12px 8px",
        minHeight: 340,
      }}>
        {loading && !datos && (
          <div style={{ display: "flex", justifyContent: "center", alignItems: "center",
                        height: 280, color: C.muted, fontSize: 13 }}>
            Calculando Curva S en el servidor…
          </div>
        )}

        {!loading && curvaFiltrada.length === 0 && (
          <div style={{ display: "flex", justifyContent: "center", alignItems: "center",
                        height: 280, color: C.muted, fontSize: 13 }}>
            {proyectoId
              ? "Sin tareas con fechas definidas en este proyecto."
              : "Selecciona un proyecto para calcular la Curva S."}
          </div>
        )}

        {curvaFiltrada.length > 0 && (
          <ResponsiveContainer width="100%" height={300}>
            <ComposedChart data={curvaFiltrada} margin={{ top: 4, right: 12, bottom: 0, left: 0 }}>
              <defs>
                <linearGradient id="gradPV" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%"  stopColor={C.pv} stopOpacity={0.15} />
                  <stop offset="95%" stopColor={C.pv} stopOpacity={0}    />
                </linearGradient>
                <linearGradient id="gradEV" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%"  stopColor={C.ev} stopOpacity={0.2} />
                  <stop offset="95%" stopColor={C.ev} stopOpacity={0}   />
                </linearGradient>
              </defs>

              <XAxis
                dataKey="fecha"
                tick={{ fill: C.muted, fontSize: 9 }}
                tickFormatter={v => v?.slice(5)}  // MM-DD
                interval="preserveStartEnd"
              />
              <YAxis
                tick={{ fill: C.muted, fontSize: 9 }}
                tickFormatter={v => `$${v >= 1000 ? `${(v/1000).toFixed(0)}k` : v}`}
              />
              <Tooltip content={<CustomTooltip />} />
              <Legend
                wrapperStyle={{ fontSize: 11, color: C.muted, paddingTop: 8 }}
              />

              {/* Línea "Hoy" */}
              {hoyLabel && (
                <ReferenceLine
                  x={hoyLabel}
                  stroke={C.ok}
                  strokeDasharray="4 3"
                  label={{ value: "Hoy", fill: C.ok, fontSize: 10, position: "insideTopRight" }}
                />
              )}

              {/* PV — Área planificada */}
              <Area
                type="monotone"
                dataKey="pv_acum"
                name="PV (Planificado)"
                stroke={C.pv}
                strokeWidth={1.5}
                fill="url(#gradPV)"
                dot={false}
                strokeDasharray={mostrarFutu ? undefined : "4 2"}
              />

              {/* EV — Línea de valor ganado */}
              <Area
                type="monotone"
                dataKey="ev_acum"
                name="EV (Valor Ganado)"
                stroke={C.ev}
                strokeWidth={2.5}
                fill="url(#gradEV)"
                dot={false}
              />

              {/* AC — Línea de costo real */}
              <Line
                type="monotone"
                dataKey="ac_acum"
                name="AC (Costo Real)"
                stroke={C.ac}
                strokeWidth={2}
                dot={false}
                strokeDasharray="6 3"
              />
            </ComposedChart>
          </ResponsiveContainer>
        )}
      </div>

      {/* Leyenda de interpretación ──────────────────────────────────────── */}
      <div style={{
        display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
        gap: 10,
      }}>
        {[
          { color: C.pv, label: "PV > EV", desc: "Trabajo planificado supera al ejecutado → atraso" },
          { color: C.ev, label: "EV > AC", desc: "Valor ganado supera costo real → eficiencia" },
          { color: C.ac, label: "AC > EV", desc: "Costo real supera al valor ganado → sobrecosto" },
        ].map(i => (
          <div key={i.label} style={{
            padding: "8px 12px", borderRadius: 8, fontSize: 11,
            background: "rgba(0,0,0,0.2)", border: `1px solid rgba(255,255,255,0.05)`,
          }}>
            <div style={{ color: i.color, fontWeight: 700, marginBottom: 2 }}>{i.label}</div>
            <div style={{ color: C.muted }}>{i.desc}</div>
          </div>
        ))}
      </div>

      <style>{`
        @keyframes spin { to { transform: rotate(360deg); } }
      `}</style>
    </div>
  );
}
