/**
 * GanttModule.jsx — Cronograma Gantt con Ruta Crítica (ID 16)
 *
 * Renderizado: SVG nativo (sin librerías de terceros).
 * Características:
 *   - Barras de tareas con progreso real (fill animado)
 *   - Flechas de dependencia Fin→Inicio
 *   - Tareas de ruta crítica con borde rojo
 *   - Actualización en tiempo real via WebSocket (evento gantt_progreso)
 *   - Exportación PDF vía GET /gantt/:proyecto_id/pdf
 *   - Formulario para crear tareas con validación frontend
 */

import { useState, useEffect, useRef, useCallback } from "react";
import { Plus, Download, RefreshCw, AlertTriangle, CheckCircle2, Clock, Trash2 } from "lucide-react";
import { AgentService, API_BASE } from "../../services/agent.service";

// ── Configuración visual ──────────────────────────────────────────────────────
const ROW_H     = 40;      // px por fila
const BAR_H     = 22;      // altura de la barra
const BAR_Y_OFF = (ROW_H - BAR_H) / 2;
const COL_LABEL = 210;     // ancho columna nombres (px)
const PX_DAY    = 28;      // px por día
const HEADER_H  = 36;      // altura del header de fechas
const ARROW_CLR = "#64748b";
const CRITICO_CLR = "#ef4444";
const AVANCE_CLR  = "#00d4ff";

// ── Helpers ───────────────────────────────────────────────────────────────────
function parseDate(s) {
  if (!s) return null;
  return new Date(s.slice(0, 10));
}
function daysBetween(a, b) {
  return Math.max(0, (b - a) / 86_400_000);
}
function addDays(d, n) {
  const r = new Date(d);
  r.setDate(r.getDate() + n);
  return r;
}
function fmtDate(d) {
  if (!d) return "";
  const dt = typeof d === "string" ? new Date(d) : d;
  return dt.toLocaleDateString("es-CL", { day: "2-digit", month: "2-digit" });
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

// ── Flecha de dependencia ─────────────────────────────────────────────────────
function DependencyArrow({ fromX, fromY, toX, toY }) {
  const mx = fromX + 12;
  const my = fromY + BAR_H / 2;
  const ty = toY + BAR_H / 2;
  const d = `M${fromX},${my} H${mx} V${ty} H${toX}`;
  return (
    <>
      <path d={d} stroke={ARROW_CLR} strokeWidth="1.5" fill="none" strokeDasharray="4 2" />
      <polygon
        points={`${toX},${ty} ${toX - 6},${ty - 4} ${toX - 6},${ty + 4}`}
        fill={ARROW_CLR}
      />
    </>
  );
}

// ── Barra de tarea ────────────────────────────────────────────────────────────
function TaskBar({ tarea, x, w, y, onClick, selected }) {
  const critica  = tarea.en_ruta_critica;
  const pct      = tarea.pct_completado ?? 0;
  const wDone    = Math.max(0, Math.min(w, w * pct / 100));
  const color    = tarea.color || AVANCE_CLR;

  return (
    <g
      onClick={onClick}
      style={{ cursor: "pointer" }}
      aria-label={tarea.nombre}
    >
      {/* Sombra selección */}
      {selected && (
        <rect x={x - 2} y={y - 2} width={w + 4} height={BAR_H + 4}
          rx={5} fill="none" stroke="#f59e0b" strokeWidth="2" />
      )}
      {/* Fondo */}
      <rect x={x} y={y} width={w} height={BAR_H}
        rx={4} fill="rgba(255,255,255,0.07)"
        stroke={critica ? CRITICO_CLR : "rgba(255,255,255,0.15)"}
        strokeWidth={critica ? 1.5 : 0.8} />
      {/* Progreso */}
      {wDone > 0 && (
        <rect x={x} y={y} width={wDone} height={BAR_H}
          rx={4} fill={critica ? CRITICO_CLR : color} opacity={0.85} />
      )}
      {/* Etiqueta */}
      <text x={x + 6} y={y + BAR_H / 2 + 4} fontSize={10}
        fill="white" fontWeight={critica ? "700" : "500"}
        style={{ userSelect: "none" }}>
        {tarea.nombre.slice(0, Math.max(3, Math.floor(w / 7)))}
      </text>
      {/* % */}
      <text x={x + w + 4} y={y + BAR_H / 2 + 4} fontSize={9}
        fill={pct === 100 ? "#4ade80" : "#94a3b8"} style={{ userSelect: "none" }}>
        {pct.toFixed(0)}%
      </text>
    </g>
  );
}

// ── Modal Nueva Tarea ─────────────────────────────────────────────────────────
function NuevaTareaModal({ proyectoId, agentes, tareas, onCreada, onClose }) {
  const [form, setForm] = useState({
    nombre:        "",
    agente_id:     "",
    inicio_plan:   new Date().toISOString().slice(0, 10),
    duracion_dias: 5,
    dependencias:  [],
    color:         "#00d4ff",
  });
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(false);

  const set = (k, v) => setForm(p => ({ ...p, [k]: v }));

  const submit = async () => {
    if (!form.nombre.trim()) { setErr("El nombre es obligatorio."); return; }
    if (form.duracion_dias <= 0) { setErr("La duración debe ser positiva."); return; }
    setLoading(true); setErr("");
    try {
      const tarea = await apiFetch(`/gantt/${proyectoId}/tareas`, {
        method: "POST",
        body: JSON.stringify({
          ...form,
          inicio_plan: new Date(form.inicio_plan).toISOString(),
        }),
      });
      onCreada(tarea);
    } catch (e) {
      setErr(String(e));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center" onClick={onClose}>
      <div className="bg-cyber-800 border border-neon-blue/30 rounded-2xl p-6 w-[440px] max-w-full shadow-2xl"
        onClick={e => e.stopPropagation()}>
        <h3 className="text-white font-bold text-base mb-4">Nueva Tarea</h3>

        <div className="flex flex-col gap-3">
          <input type="text" placeholder="Nombre de la tarea *"
            value={form.nombre} onChange={e => set("nombre", e.target.value)}
            className="bg-cyber-700 border border-cyber-600 rounded-lg text-sm text-white px-3 py-2 placeholder:text-gray-600" />

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-gray-500 mb-1 block">Inicio planificado</label>
              <input type="date" value={form.inicio_plan} onChange={e => set("inicio_plan", e.target.value)}
                className="w-full bg-cyber-700 border border-cyber-600 rounded text-sm text-white px-2 py-1.5" />
            </div>
            <div>
              <label className="text-xs text-gray-500 mb-1 block">Duración (días)</label>
              <input type="number" min="1" value={form.duracion_dias}
                onChange={e => set("duracion_dias", Number(e.target.value))}
                className="w-full bg-cyber-700 border border-cyber-600 rounded text-sm text-white px-2 py-1.5 font-mono" />
            </div>
          </div>

          <div>
            <label className="text-xs text-gray-500 mb-1 block">Agente responsable</label>
            <select value={form.agente_id} onChange={e => set("agente_id", e.target.value)}
              className="w-full bg-cyber-700 border border-cyber-600 rounded text-sm text-white px-2 py-1.5">
              <option value="">— Sin asignar —</option>
              {agentes.map(a => <option key={a.id} value={a.id}>{a.nombre}</option>)}
            </select>
          </div>

          {tareas.length > 0 && (
            <div>
              <label className="text-xs text-gray-500 mb-1 block">Predecesoras (Fin→Inicio)</label>
              <div className="flex flex-wrap gap-1.5 max-h-24 overflow-y-auto">
                {tareas.map(t => {
                  const sel = form.dependencias.includes(t.id);
                  return (
                    <button key={t.id}
                      onClick={() => set("dependencias", sel
                        ? form.dependencias.filter(d => d !== t.id)
                        : [...form.dependencias, t.id])}
                      className={`text-xs px-2 py-0.5 rounded-full border transition-colors ${
                        sel ? "bg-neon-blue/20 border-neon-blue text-neon-blue"
                            : "bg-cyber-700 border-cyber-600 text-gray-400"}`}>
                      {t.nombre.slice(0, 18)}
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          <div className="flex items-center gap-2">
            <label className="text-xs text-gray-500">Color</label>
            <input type="color" value={form.color} onChange={e => set("color", e.target.value)}
              className="w-8 h-8 rounded cursor-pointer bg-transparent border-0" />
          </div>
        </div>

        {err && <p className="text-xs text-red-400 mt-2">{err}</p>}

        <div className="flex gap-2 mt-5">
          <button onClick={onClose}
            className="flex-1 text-sm text-gray-400 border border-cyber-600 rounded-lg py-2 hover:bg-cyber-700 transition-colors">
            Cancelar
          </button>
          <button onClick={submit} disabled={loading}
            className="flex-1 text-sm text-neon-blue border border-neon-blue/40 bg-neon-blue/10 rounded-lg py-2 hover:bg-neon-blue/20 transition-colors disabled:opacity-40">
            {loading ? "Creando…" : "Crear Tarea"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Componente principal ──────────────────────────────────────────────────────
export default function GanttModule({ proyectoId = "proyecto_01", agentes = [] }) {
  const [tareas,      setTareas]      = useState([]);
  const [resumen,     setResumen]     = useState({});
  const [loading,     setLoading]     = useState(true);
  const [error,       setError]       = useState(null);
  const [selectedId,  setSelectedId]  = useState(null);
  const [modalOpen,   setModalOpen]   = useState(false);
  const [exporting,   setExporting]   = useState(false);
  const svgRef = useRef(null);

  // ── Carga de datos ──────────────────────────────────────────────────────────
  const cargar = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const data = await apiFetch(`/gantt/${proyectoId}`);
      setTareas(data.tareas || []);
      setResumen(data.resumen || {});
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [proyectoId]);

  useEffect(() => { cargar(); }, [cargar]);

  // ── Suscripción WebSocket: gantt_progreso ────────────────────────────────────
  useEffect(() => {
    const unsub = AgentService.onWsMessage((msg) => {
      if (msg.tipo === "gantt_progreso" && msg.proyecto === proyectoId) {
        setTareas(prev => prev.map(t =>
          t.id === msg.tarea_id ? { ...t, pct_completado: msg.pct } : t
        ));
      }
    });
    return () => unsub?.();
  }, [proyectoId]);

  // ── Cálculo del espacio SVG ──────────────────────────────────────────────────
  const fechasInicio = tareas.map(t => parseDate(t.inicio_plan)).filter(Boolean);
  const fechasFin    = tareas.map(t => parseDate(t.fin_plan    )).filter(Boolean);
  const t0 = fechasInicio.length ? new Date(Math.min(...fechasInicio)) : new Date();
  const t1 = fechasFin.length    ? new Date(Math.max(...fechasFin))    : addDays(t0, 30);
  const rangoDias   = Math.max(1, daysBetween(t0, t1));
  const svgW        = COL_LABEL + rangoDias * PX_DAY + 60;
  const svgH        = HEADER_H + tareas.length * ROW_H + 16;

  // Mapeo id → índice de fila
  const rowIndex = Object.fromEntries(tareas.map((t, i) => [t.id, i]));

  function xOf(date) {
    const d = typeof date === "string" ? parseDate(date) : date;
    return COL_LABEL + daysBetween(t0, d) * PX_DAY;
  }
  function yOf(id) {
    return HEADER_H + (rowIndex[id] ?? 0) * ROW_H + BAR_Y_OFF;
  }

  // ── Acciones ─────────────────────────────────────────────────────────────────
  const handleCreada = (tarea) => {
    setModalOpen(false);
    cargar();  // recargar para obtener CPM actualizado
  };

  const handleEliminar = async (id) => {
    if (!window.confirm("¿Eliminar esta tarea?")) return;
    try {
      await apiFetch(`/gantt/tareas/${id}`, { method: "DELETE" });
      cargar();
    } catch (e) {
      setError(String(e));
    }
  };

  const handleExportPdf = async () => {
    setExporting(true);
    try {
      const res = await fetch(`${API_BASE}/gantt/${proyectoId}/pdf`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const blob = await res.blob();
      const url  = URL.createObjectURL(blob);
      const a    = document.createElement("a");
      a.href = url; a.download = `avance_${proyectoId}.pdf`; a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(String(e));
    } finally {
      setExporting(false);
    }
  };

  // ── Header de fechas (semanas) ───────────────────────────────────────────────
  const semanas = [];
  for (let d = 0; d <= rangoDias; d += 7) {
    semanas.push({ d, fecha: addDays(t0, d) });
  }

  // ── Render ───────────────────────────────────────────────────────────────────
  return (
    <div className="flex flex-col gap-4 p-4">

      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div>
          <h2 className="text-lg font-bold text-white">Cronograma Gantt</h2>
          <p className="text-xs text-gray-500">Proyecto: <span className="text-neon-blue">{proyectoId}</span></p>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={cargar}
            className="flex items-center gap-1.5 text-xs text-gray-400 hover:text-neon-blue transition-colors px-2 py-1">
            <RefreshCw size={12} /> Actualizar
          </button>
          <button onClick={handleExportPdf} disabled={exporting || tareas.length === 0}
            className="flex items-center gap-1.5 text-xs border border-neon-blue/30 text-neon-blue
                       px-3 py-1.5 rounded-lg hover:bg-neon-blue/10 transition-colors disabled:opacity-40">
            <Download size={12} /> {exporting ? "Generando…" : "Exportar PDF"}
          </button>
          <button onClick={() => setModalOpen(true)}
            className="flex items-center gap-1.5 text-xs bg-neon-blue/10 border border-neon-blue/40
                       text-neon-blue px-3 py-1.5 rounded-lg hover:bg-neon-blue/20 transition-colors">
            <Plus size={12} /> Nueva Tarea
          </button>
        </div>
      </div>

      {/* KPIs */}
      {Object.keys(resumen).length > 0 && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
          {[
            { label: "Avance global",   value: `${resumen.pct_avance ?? 0}%`,          icon: CheckCircle2, color: "text-neon-green" },
            { label: "Total tareas",    value: resumen.total_tareas ?? 0,               icon: Clock,        color: "text-neon-blue"  },
            { label: "Ruta crítica",    value: `${resumen.tareas_criticas ?? 0} tareas`, icon: AlertTriangle, color: "text-red-400"   },
            { label: "Fin planificado", value: (resumen.fecha_fin || "—").slice(0, 10), icon: Clock,        color: "text-yellow-400" },
          ].map(({ label, value, icon: Icon, color }) => (
            <div key={label} className="bg-cyber-800 border border-neon-blue/10 rounded-xl p-3 flex items-center gap-2">
              <Icon size={16} className={color} />
              <div>
                <p className="text-xs text-gray-500">{label}</p>
                <p className={`text-sm font-bold font-mono ${color}`}>{value}</p>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="text-xs text-red-400 bg-red-400/10 border border-red-400/20 rounded px-3 py-2">
          {error}
        </div>
      )}

      {/* Loading */}
      {loading && (
        <div className="text-xs text-gray-500 animate-pulse py-8 text-center">Cargando cronograma…</div>
      )}

      {/* SVG Gantt */}
      {!loading && tareas.length > 0 && (
        <div className="bg-cyber-800 border border-neon-blue/10 rounded-xl overflow-hidden">
          <div className="overflow-x-auto" style={{ maxWidth: "100%" }}>
            <svg
              ref={svgRef}
              width={svgW}
              height={svgH}
              style={{ fontFamily: "monospace", display: "block" }}
            >
              {/* Fondo */}
              <rect width={svgW} height={svgH} fill="#0d1f35" />

              {/* Franjas alternas de filas */}
              {tareas.map((_, i) => (
                <rect key={i}
                  x={0} y={HEADER_H + i * ROW_H}
                  width={svgW} height={ROW_H}
                  fill={i % 2 === 0 ? "rgba(255,255,255,0.02)" : "transparent"} />
              ))}

              {/* Columna fija: nombres */}
              <rect x={0} y={0} width={COL_LABEL} height={svgH} fill="#081624" />
              <line x1={COL_LABEL} y1={0} x2={COL_LABEL} y2={svgH}
                stroke="rgba(0,212,255,0.2)" strokeWidth="1" />

              {/* Header: fechas (semanas) */}
              <rect x={0} y={0} width={svgW} height={HEADER_H} fill="#081624" />
              <line x1={0} y1={HEADER_H} x2={svgW} y2={HEADER_H}
                stroke="rgba(0,212,255,0.2)" strokeWidth="1" />

              {/* Hoy */}
              {(() => {
                const xHoy = xOf(new Date());
                return xHoy > COL_LABEL && xHoy < svgW ? (
                  <>
                    <line x1={xHoy} y1={HEADER_H} x2={xHoy} y2={svgH}
                      stroke="#f59e0b" strokeWidth="1" strokeDasharray="3 3" opacity="0.6" />
                    <text x={xHoy + 3} y={HEADER_H - 4} fontSize={8} fill="#f59e0b">hoy</text>
                  </>
                ) : null;
              })()}

              {semanas.map(({ d, fecha }) => {
                const x = COL_LABEL + d * PX_DAY;
                return (
                  <g key={d}>
                    <line x1={x} y1={HEADER_H} x2={x} y2={svgH}
                      stroke="rgba(255,255,255,0.05)" strokeWidth="1" />
                    <text x={x + 3} y={HEADER_H - 10} fontSize={9} fill="#4b6073">
                      {fmtDate(fecha)}
                    </text>
                  </g>
                );
              })}

              {/* Nombres de tareas en columna fija */}
              {tareas.map((t, i) => {
                const y = HEADER_H + i * ROW_H;
                const critica = t.en_ruta_critica;
                return (
                  <g key={t.id} onClick={() => setSelectedId(t.id === selectedId ? null : t.id)}>
                    <rect x={0} y={y} width={COL_LABEL} height={ROW_H}
                      fill="transparent" style={{ cursor: "pointer" }} />
                    {/* Indicador crítica */}
                    {critica && (
                      <rect x={0} y={y + ROW_H / 4} width={3} height={ROW_H / 2}
                        fill={CRITICO_CLR} rx={1} />
                    )}
                    <text x={10} y={y + ROW_H / 2 + 4} fontSize={10.5}
                      fill={critica ? CRITICO_CLR : "#cbd5e1"}
                      fontWeight={critica ? "700" : "500"}
                      style={{ userSelect: "none" }}>
                      {t.nombre.slice(0, 22)}
                    </text>
                    {t.agente_id && (
                      <text x={10} y={y + ROW_H / 2 + 15} fontSize={8} fill="#4b6073"
                        style={{ userSelect: "none" }}>
                        {t.agente_id.slice(0, 20)}
                      </text>
                    )}
                    {/* Botón eliminar (solo cuando seleccionado) */}
                    {selectedId === t.id && (
                      <g onClick={e => { e.stopPropagation(); handleEliminar(t.id); }}>
                        <rect x={COL_LABEL - 20} y={y + 10} width={16} height={16}
                          rx={3} fill="rgba(239,68,68,0.2)" style={{ cursor: "pointer" }} />
                        <text x={COL_LABEL - 14} y={y + 21} fontSize={10} fill="#ef4444"
                          style={{ userSelect: "none" }}>✕</text>
                      </g>
                    )}
                  </g>
                );
              })}

              {/* Flechas de dependencia */}
              {tareas.flatMap(t =>
                (t.dependencias || []).map(depId => {
                  const dep = tareas.find(d => d.id === depId);
                  if (!dep) return null;
                  const fromX = xOf(dep.fin_plan) + 2;
                  const fromY = yOf(dep.id);
                  const toX   = xOf(t.inicio_plan) - 2;
                  const toY   = yOf(t.id);
                  return (
                    <DependencyArrow
                      key={`${depId}->${t.id}`}
                      fromX={fromX} fromY={fromY}
                      toX={toX}   toY={toY}
                    />
                  );
                }).filter(Boolean)
              )}

              {/* Barras de tareas */}
              {tareas.map(t => {
                const x = xOf(t.inicio_plan);
                const w = Math.max(6, daysBetween(parseDate(t.inicio_plan), parseDate(t.fin_plan)) * PX_DAY);
                const y = yOf(t.id);
                return (
                  <TaskBar
                    key={t.id}
                    tarea={t}
                    x={x} w={w} y={y}
                    selected={selectedId === t.id}
                    onClick={() => setSelectedId(t.id === selectedId ? null : t.id)}
                  />
                );
              })}

              {/* Etiquetas de la cabecera de columna fija */}
              <text x={10} y={HEADER_H - 10} fontSize={9} fill="#4b6073"
                fontWeight="600" style={{ userSelect: "none" }}>
                TAREA / AGENTE
              </text>
            </svg>
          </div>

          {/* Leyenda */}
          <div className="flex items-center gap-5 px-4 py-2.5 border-t border-neon-blue/10 text-xs text-gray-500">
            <span className="flex items-center gap-1.5">
              <span className="w-4 h-2.5 rounded" style={{ background: AVANCE_CLR }} /> Avance real
            </span>
            <span className="flex items-center gap-1.5">
              <span className="w-4 h-2.5 rounded border border-red-500" style={{ background: "rgba(239,68,68,0.4)" }} />
              Ruta crítica
            </span>
            <span className="flex items-center gap-1.5">
              <span className="w-4 h-2.5 rounded" style={{ background: "#f59e0b" }} /> Hoy
            </span>
            <span className="ml-auto text-gray-600">Escala: {PX_DAY}px/día · Clic en tarea para seleccionar</span>
          </div>
        </div>
      )}

      {/* Estado vacío */}
      {!loading && tareas.length === 0 && !error && (
        <div className="bg-cyber-800 border border-dashed border-neon-blue/20 rounded-xl p-10 text-center">
          <p className="text-gray-500 text-sm mb-3">No hay tareas en este proyecto.</p>
          <button onClick={() => setModalOpen(true)}
            className="text-xs text-neon-blue border border-neon-blue/30 px-4 py-2 rounded-lg
                       hover:bg-neon-blue/10 transition-colors">
            <Plus size={12} className="inline mr-1" /> Crear primera tarea
          </button>
        </div>
      )}

      {/* Modal */}
      {modalOpen && (
        <NuevaTareaModal
          proyectoId={proyectoId}
          agentes={agentes}
          tareas={tareas}
          onCreada={handleCreada}
          onClose={() => setModalOpen(false)}
        />
      )}
    </div>
  );
}
