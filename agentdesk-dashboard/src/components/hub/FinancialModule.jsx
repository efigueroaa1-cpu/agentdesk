/**
 * FinancialModule.jsx — Módulo de Inteligencia Financiera (ID 15)
 *
 * Muestra:
 *   - Indicadores macro Chile en tiempo real (UF, Dólar, IPC, Euro)
 *   - Formulario de presupuesto con validación de partidas
 *   - AreaChart de proyección de flujo de caja (recharts)
 *   - BarChart de ingresos vs egresos por partida
 *   - Historial de análisis anteriores con tendencia
 *
 * Consume: GET /finanzas/indicadores, POST /finanzas/analizar,
 *          GET /finanzas/historico/:agente_id, GET /finanzas/tendencia/:agente_id
 */

import { useState, useEffect, useCallback } from "react";
import {
  AreaChart, Area, BarChart, Bar,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  ResponsiveContainer, ReferenceLine,
} from "recharts";
import { TrendingUp, TrendingDown, Minus, RefreshCw, Plus, Trash2, DollarSign, Activity } from "lucide-react";
import { API_BASE } from "../../services/agent.service";

// ── Helpers ──────────────────────────────────────────────────────────────────
function fmtCLP(n) {
  if (n == null) return "—";
  return new Intl.NumberFormat("es-CL", { style: "currency", currency: "CLP", maximumFractionDigits: 0 }).format(n);
}
function fmtNum(n, dec = 2) {
  if (n == null) return "—";
  return new Intl.NumberFormat("es-CL", { minimumFractionDigits: dec, maximumFractionDigits: dec }).format(n);
}

async function apiFetch(path, opts = {}) {
  const token = sessionStorage.getItem("agentdesk-jwt-token") || "";
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    ...opts,
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

// ── Tooltip personalizado ─────────────────────────────────────────────────────
function TooltipFinanciero({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-cyber-900 border border-neon-blue/30 rounded-lg p-3 text-xs shadow-xl">
      <p className="text-gray-400 mb-1">Mes {label}</p>
      {payload.map((p) => (
        <p key={p.dataKey} style={{ color: p.color }}>
          {p.name}: {fmtCLP(p.value)}
        </p>
      ))}
    </div>
  );
}

// ── Indicador Macro Card ──────────────────────────────────────────────────────
function IndicadorCard({ label, value, unit = "" }) {
  return (
    <div className="bg-cyber-800 border border-neon-blue/20 rounded-xl p-4 flex flex-col gap-1">
      <span className="text-xs text-gray-500 uppercase tracking-wider">{label}</span>
      <span className="text-xl font-bold text-neon-blue font-mono">
        {value != null ? `$${fmtNum(value, 2)}` : "—"}
        {unit && <span className="text-xs text-gray-400 ml-1">{unit}</span>}
      </span>
    </div>
  );
}

// ── Tendencia Badge ───────────────────────────────────────────────────────────
function TendenciaBadge({ tendencia }) {
  const map = {
    mejora:    { icon: TrendingUp,   color: "text-neon-green", bg: "bg-neon-green/10",  label: "Mejora" },
    empeora:   { icon: TrendingDown, color: "text-red-400",    bg: "bg-red-400/10",     label: "Empeora" },
    estable:   { icon: Minus,        color: "text-yellow-400", bg: "bg-yellow-400/10",  label: "Estable" },
    sin_datos: { icon: Minus,        color: "text-gray-500",   bg: "bg-gray-500/10",    label: "Sin datos" },
  };
  const cfg = map[tendencia] ?? map.sin_datos;
  const Icon = cfg.icon;
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${cfg.color} ${cfg.bg}`}>
      <Icon size={11} /> {cfg.label}
    </span>
  );
}

// ── Componente principal ──────────────────────────────────────────────────────
export default function FinancialModule({ agentId }) {
  const [indicadores,  setIndicadores]  = useState(null);
  const [analisis,     setAnalisis]     = useState(null);
  const [historial,    setHistorial]    = useState([]);
  const [tendencia,    setTendencia]    = useState(null);
  const [loading,      setLoading]      = useState(false);
  const [loadingInd,   setLoadingInd]   = useState(true);
  const [error,        setError]        = useState(null);
  const [periodos,     setPeriodos]     = useState(6);
  const [moneda,       setMoneda]       = useState("CLP");

  // ── Partidas del presupuesto ────────────────────────────────────────────────
  const [items, setItems] = useState([
    { concepto: "Ventas", monto: 0, tipo: "ingreso" },
    { concepto: "Operaciones", monto: 0, tipo: "egreso" },
  ]);

  // ── Carga de indicadores macro ──────────────────────────────────────────────
  const cargarIndicadores = useCallback(async () => {
    setLoadingInd(true);
    try {
      const data = await apiFetch("/finanzas/indicadores");
      if (data.ok) setIndicadores(data.indicadores);
      else setError(data.error);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoadingInd(false);
    }
  }, []);

  // ── Carga de historial ──────────────────────────────────────────────────────
  const cargarHistorial = useCallback(async () => {
    if (!agentId) return;
    try {
      const [hist, tend] = await Promise.all([
        apiFetch(`/finanzas/historico/${agentId}?n=10`),
        apiFetch(`/finanzas/tendencia/${agentId}`),
      ]);
      setHistorial(hist.registros ?? []);
      setTendencia(tend);
    } catch { /* historial puede estar vacío en primer uso */ }
  }, [agentId]);

  useEffect(() => {
    cargarIndicadores();
    cargarHistorial();
  }, [cargarIndicadores, cargarHistorial]);

  // ── Ejecutar análisis ───────────────────────────────────────────────────────
  const ejecutarAnalisis = async () => {
    if (!agentId) { setError("Selecciona un agente primero."); return; }
    const itemsInvalidos = items.filter(i => !i.concepto.trim() || i.monto < 0);
    if (itemsInvalidos.length) { setError("Revisa los ítems: concepto vacío o monto negativo."); return; }

    setLoading(true);
    setError(null);
    try {
      const body = {
        agente_id:   agentId,
        presupuesto: { items, moneda, periodo: "mensual" },
        periodos,
      };
      const data = await apiFetch("/finanzas/analizar", {
        method: "POST",
        body: JSON.stringify(body),
      });
      if (data.ok) {
        setAnalisis(data.analisis);
        cargarHistorial();
      } else {
        setError(data.error ?? "Error en el análisis");
      }
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  };

  // ── Manejo de partidas ──────────────────────────────────────────────────────
  const agregarItem = () =>
    setItems(prev => [...prev, { concepto: "", monto: 0, tipo: "ingreso" }]);

  const eliminarItem = (idx) =>
    setItems(prev => prev.filter((_, i) => i !== idx));

  const actualizarItem = (idx, campo, valor) =>
    setItems(prev => prev.map((it, i) => i === idx ? { ...it, [campo]: valor } : it));

  // ── Datos para recharts ─────────────────────────────────────────────────────
  const proyeccionData = analisis?.proyeccion?.map(p => ({
    mes:       `M${p.mes}`,
    Ingresos:  p.ingreso_proy,
    Egresos:   p.egreso_proy,
    Neto:      p.flujo_neto_proy,
    Acumulado: p.acumulado,
  })) ?? [];

  const barData = items.map(i => ({
    name:   i.concepto || "Sin nombre",
    monto:  i.monto,
    tipo:   i.tipo,
    fill:   i.tipo === "ingreso" ? "#00d4ff" : "#ff3d60",
  }));

  const flujoActual = analisis?.flujo;

  return (
    <div className="flex flex-col gap-6 p-4">

      {/* ── Header ── */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <DollarSign size={18} className="text-neon-blue" />
          <h2 className="text-lg font-bold text-white">Inteligencia Financiera</h2>
          {tendencia && <TendenciaBadge tendencia={tendencia.tendencia} />}
        </div>
        <button
          onClick={() => { cargarIndicadores(); cargarHistorial(); }}
          className="flex items-center gap-1.5 text-xs text-gray-400 hover:text-neon-blue transition-colors"
        >
          <RefreshCw size={12} /> Actualizar
        </button>
      </div>

      {/* ── Indicadores macro ── */}
      <section>
        <p className="text-xs text-gray-500 uppercase tracking-wider mb-2">Banco Central Chile</p>
        {loadingInd ? (
          <div className="text-xs text-gray-500 animate-pulse">Consultando mindicador.cl…</div>
        ) : indicadores ? (
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <IndicadorCard label="UF"    value={indicadores.uf}    unit="CLP" />
            <IndicadorCard label="Dólar" value={indicadores.dolar} unit="CLP" />
            <IndicadorCard label="Euro"  value={indicadores.euro}  unit="CLP" />
            <IndicadorCard label="IPC"   value={indicadores.ipc}   unit="%" />
          </div>
        ) : (
          <div className="text-xs text-yellow-400 bg-yellow-400/10 rounded px-3 py-2">
            Sin conexión al Banco Central. Revisa la red.
          </div>
        )}
      </section>

      {/* ── Presupuesto ── */}
      <section className="bg-cyber-800 rounded-xl border border-neon-blue/10 p-4">
        <div className="flex items-center justify-between mb-3">
          <p className="text-sm font-semibold text-white">Presupuesto</p>
          <div className="flex items-center gap-2">
            <select
              value={moneda}
              onChange={e => setMoneda(e.target.value)}
              className="bg-cyber-700 border border-cyber-600 rounded text-xs text-gray-300 px-2 py-1"
            >
              {["CLP","USD","EUR","UF"].map(m => <option key={m}>{m}</option>)}
            </select>
            <select
              value={periodos}
              onChange={e => setPeriodos(Number(e.target.value))}
              className="bg-cyber-700 border border-cyber-600 rounded text-xs text-gray-300 px-2 py-1"
            >
              {[3,6,12,24].map(p => <option key={p} value={p}>{p} meses</option>)}
            </select>
          </div>
        </div>

        {/* Partidas */}
        <div className="flex flex-col gap-2 mb-3">
          {items.map((item, idx) => (
            <div key={idx} className="flex items-center gap-2">
              <select
                value={item.tipo}
                onChange={e => actualizarItem(idx, "tipo", e.target.value)}
                className={`text-xs rounded px-2 py-1 border ${
                  item.tipo === "ingreso"
                    ? "bg-neon-blue/10 border-neon-blue/30 text-neon-blue"
                    : "bg-red-500/10 border-red-500/30 text-red-400"
                }`}
              >
                <option value="ingreso">Ingreso</option>
                <option value="egreso">Egreso</option>
              </select>
              <input
                type="text"
                value={item.concepto}
                onChange={e => actualizarItem(idx, "concepto", e.target.value)}
                placeholder="Concepto"
                className="flex-1 bg-cyber-700 border border-cyber-600 rounded text-xs text-white px-2 py-1 placeholder:text-gray-600"
              />
              <input
                type="number"
                min="0"
                value={item.monto}
                onChange={e => actualizarItem(idx, "monto", Number(e.target.value))}
                className="w-32 bg-cyber-700 border border-cyber-600 rounded text-xs text-white px-2 py-1 font-mono"
              />
              {items.length > 1 && (
                <button onClick={() => eliminarItem(idx)} className="text-gray-600 hover:text-red-400 transition-colors">
                  <Trash2 size={13} />
                </button>
              )}
            </div>
          ))}
        </div>

        <div className="flex items-center justify-between">
          <button
            onClick={agregarItem}
            className="flex items-center gap-1 text-xs text-gray-400 hover:text-neon-blue transition-colors"
          >
            <Plus size={12} /> Añadir partida
          </button>
          <div className="flex items-center gap-4 text-xs">
            <span className="text-neon-green font-mono">
              + {fmtCLP(items.filter(i=>i.tipo==="ingreso").reduce((a,i)=>a+i.monto,0))}
            </span>
            <span className="text-red-400 font-mono">
              − {fmtCLP(items.filter(i=>i.tipo==="egreso").reduce((a,i)=>a+i.monto,0))}
            </span>
          </div>
        </div>
      </section>

      {/* ── Error ── */}
      {error && (
        <div className="text-xs text-red-400 bg-red-400/10 border border-red-400/20 rounded px-3 py-2">
          {error}
        </div>
      )}

      {/* ── Botón analizar ── */}
      <button
        onClick={ejecutarAnalisis}
        disabled={loading || !agentId}
        className="flex items-center justify-center gap-2 bg-neon-blue/10 border border-neon-blue/40
                   hover:bg-neon-blue/20 text-neon-blue font-semibold rounded-xl py-2.5 text-sm
                   transition-all disabled:opacity-40 disabled:cursor-not-allowed"
      >
        {loading ? (
          <><Activity size={14} className="animate-spin" /> Analizando…</>
        ) : (
          <><Activity size={14} /> Ejecutar Análisis Financiero</>
        )}
      </button>

      {/* ── Resultados de flujo actual ── */}
      {flujoActual && (
        <section className="grid grid-cols-3 gap-3">
          {[
            { label: "Ingresos",   value: flujoActual.ingresos,   color: "text-neon-green" },
            { label: "Egresos",    value: flujoActual.egresos,    color: "text-red-400"    },
            { label: "Flujo Neto", value: flujoActual.flujo_neto, color: flujoActual.flujo_neto >= 0 ? "text-neon-blue" : "text-red-400" },
          ].map(({ label, value, color }) => (
            <div key={label} className="bg-cyber-800 rounded-xl border border-neon-blue/10 p-3 text-center">
              <p className="text-xs text-gray-500 mb-1">{label}</p>
              <p className={`text-base font-bold font-mono ${color}`}>{fmtCLP(value)}</p>
              <p className="text-xs text-gray-600">{flujoActual.moneda} / {flujoActual.periodo}</p>
            </div>
          ))}
        </section>
      )}

      {/* ── AreaChart: Proyección de flujo ── */}
      {proyeccionData.length > 0 && (
        <section className="bg-cyber-800 rounded-xl border border-neon-blue/10 p-4">
          <p className="text-sm font-semibold text-white mb-3">
            Proyección de Flujo de Caja — {periodos} meses
          </p>
          <ResponsiveContainer width="100%" height={220}>
            <AreaChart data={proyeccionData} margin={{ top: 5, right: 10, left: 10, bottom: 0 }}>
              <defs>
                <linearGradient id="gradIngresos" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%"  stopColor="#00d4ff" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="#00d4ff" stopOpacity={0}   />
                </linearGradient>
                <linearGradient id="gradEgresos" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%"  stopColor="#ff3d60" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="#ff3d60" stopOpacity={0}   />
                </linearGradient>
                <linearGradient id="gradAcumulado" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%"  stopColor="#a855f7" stopOpacity={0.4} />
                  <stop offset="95%" stopColor="#a855f7" stopOpacity={0}   />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
              <XAxis dataKey="mes" tick={{ fill: "#6b7280", fontSize: 11 }} axisLine={false} tickLine={false} />
              <YAxis tickFormatter={v => `$${(v/1000).toFixed(0)}K`} tick={{ fill: "#6b7280", fontSize: 10 }} axisLine={false} tickLine={false} />
              <Tooltip content={<TooltipFinanciero />} />
              <Legend wrapperStyle={{ fontSize: 11, color: "#9ca3af" }} />
              <ReferenceLine y={0} stroke="rgba(255,255,255,0.1)" />
              <Area type="monotone" dataKey="Ingresos"  stroke="#00d4ff" fill="url(#gradIngresos)"  strokeWidth={2} dot={false} />
              <Area type="monotone" dataKey="Egresos"   stroke="#ff3d60" fill="url(#gradEgresos)"   strokeWidth={2} dot={false} />
              <Area type="monotone" dataKey="Acumulado" stroke="#a855f7" fill="url(#gradAcumulado)" strokeWidth={2} dot={false} strokeDasharray="4 2" />
            </AreaChart>
          </ResponsiveContainer>
        </section>
      )}

      {/* ── BarChart: Partidas del presupuesto ── */}
      {barData.length > 0 && (
        <section className="bg-cyber-800 rounded-xl border border-neon-blue/10 p-4">
          <p className="text-sm font-semibold text-white mb-3">Distribución por Partida</p>
          <ResponsiveContainer width="100%" height={180}>
            <BarChart data={barData} margin={{ top: 5, right: 10, left: 10, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
              <XAxis dataKey="name" tick={{ fill: "#6b7280", fontSize: 10 }} axisLine={false} tickLine={false} />
              <YAxis tickFormatter={v => `$${(v/1000).toFixed(0)}K`} tick={{ fill: "#6b7280", fontSize: 10 }} axisLine={false} tickLine={false} />
              <Tooltip content={<TooltipFinanciero />} />
              <Bar dataKey="monto" name="Monto" radius={[4, 4, 0, 0]}>
                {barData.map((entry, index) => (
                  <rect key={`cell-${index}`} fill={entry.fill} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </section>
      )}

      {/* ── Historial ── */}
      {historial.length > 0 && (
        <section className="bg-cyber-800 rounded-xl border border-neon-blue/10 p-4">
          <div className="flex items-center justify-between mb-3">
            <p className="text-sm font-semibold text-white">Historial de Análisis</p>
            {tendencia && (
              <span className="text-xs text-gray-400">
                Promedio: <span className="text-neon-blue font-mono">{fmtCLP(tendencia.promedio)}</span>
                {" "}<TendenciaBadge tendencia={tendencia.tendencia} />
              </span>
            )}
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-gray-500 border-b border-cyber-700">
                  <th className="pb-2 text-left font-medium">Fecha</th>
                  <th className="pb-2 text-right font-medium">UF</th>
                  <th className="pb-2 text-right font-medium">Dólar</th>
                  <th className="pb-2 text-right font-medium">Flujo Neto</th>
                </tr>
              </thead>
              <tbody>
                {historial.map((r, i) => (
                  <tr key={r.id ?? i} className="border-b border-cyber-700/50 hover:bg-cyber-700/30 transition-colors">
                    <td className="py-1.5 text-gray-400">
                      {r.ts ? new Date(r.ts).toLocaleString("es-CL", { dateStyle: "short", timeStyle: "short" }) : "—"}
                    </td>
                    <td className="py-1.5 text-right font-mono text-gray-300">
                      {r.uf_valor != null ? `$${fmtNum(r.uf_valor)}` : "—"}
                    </td>
                    <td className="py-1.5 text-right font-mono text-gray-300">
                      {r.dolar_valor != null ? `$${fmtNum(r.dolar_valor)}` : "—"}
                    </td>
                    <td className={`py-1.5 text-right font-mono font-semibold ${(r.flujo_neto ?? 0) >= 0 ? "text-neon-green" : "text-red-400"}`}>
                      {r.flujo_neto != null ? fmtCLP(r.flujo_neto) : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

    </div>
  );
}
