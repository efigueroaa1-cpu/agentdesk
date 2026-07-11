/**
 * AgentHub.jsx — Vista principal del Orchestrator Hub.
 *
 * Al montar:
 *   - Carga agentes desde FastAPI GET /agentes
 *   - Abre WebSocket /ws/telemetria
 *   - Suscribe a Tauri agent_log → AgentConsole
 *   - Suscribe a Tauri hardware_metrics → AgentMetrics (vía el componente)
 *
 * Flujo de creación:
 *   Botón "Nuevo Agente" → NewAgentModal → POST /agentes
 *   → Python CREAR_AGENTE → WS emite "agente_creado" → lista actualizada sin reload
 */

import { useState, useEffect, useMemo, useRef, Suspense, lazy } from "react";
import { Activity, Play, Square, Plus, RefreshCw, Wifi, WifiOff, ServerCrash, Terminal } from "lucide-react";
import AgentMetrics    from "./AgentMetrics";
import AgentConsole    from "./AgentConsole";
import NewAgentModal   from "./NewAgentModal";
import ErrorBoundary   from "../ui/ErrorBoundary";
import { AgentService, API_BASE } from "../../services/agent.service";

// Lazy-load Three.js and react-simple-maps to avoid init crash in production bundle
const AgentMap        = lazy(() => import("./AgentMap"));
const EmbeddingView3D = lazy(() => import("./EmbeddingView3D"));

// ── Constantes ────────────────────────────────────────────────────────────────
const MAX_LOGS_PER_AGENT = 500;

// ── Colores y estilos por área ────────────────────────────────────────────────
const AREA_CONFIG = {
  Finanzas:   { color: "text-neon-blue",   bg: "bg-neon-blue/10",   border: "border-neon-blue/30"   },
  General:    { color: "text-purple-400",  bg: "bg-purple-400/10",  border: "border-purple-400/30"  },
  Mecanica:   { color: "text-neon-green",  bg: "bg-neon-green/10",  border: "border-neon-green/30"  },
  Rrhh:       { color: "text-yellow-400",  bg: "bg-yellow-400/10",  border: "border-yellow-400/30"  },
  Marketing:  { color: "text-red-400",     bg: "bg-red-400/10",     border: "border-red-400/30"     },
  Logistica:  { color: "text-emerald-400", bg: "bg-emerald-400/10", border: "border-emerald-400/30" },
  Legal:      { color: "text-orange-400",  bg: "bg-orange-400/10",  border: "border-orange-400/30"  },
  Tecnologia: { color: "text-cyan-400",    bg: "bg-cyan-400/10",    border: "border-cyan-400/30"    },
};

function areaStyle(area) {
  const key = area?.charAt(0).toUpperCase() + area?.slice(1).toLowerCase();
  return AREA_CONFIG[key] ?? { color:"text-gray-400", bg:"bg-gray-400/10", border:"border-gray-400/30" };
}

const STATUS_DOT = {
  running: "bg-neon-green animate-pulse",
  idle:    "bg-yellow-400",
  stopped: "bg-gray-600",
  error:   "bg-red-500",
};

// Agentes mock para cuando la API no está disponible
const FALLBACK_AGENTS = [
  { id:"agente_bd_01",       nombre:"Analista de Datos",    area:"General",  status:"stopped", lat:19.4,  lng:-99.1  },
  { id:"agente_finanzas_01", nombre:"Estratega Financiero", area:"Finanzas", status:"stopped", lat:40.7,  lng:-74.0  },
  { id:"agente_test_fire",   nombre:"Test Fire Agent",      area:"General",  status:"idle",    lat:25.0,  lng:-100.0 },
];

// ── Helper: agrega entrada de log con límite de líneas ────────────────────────
function appendLog(prev, agentId, entry) {
  const existing = prev[agentId] ?? [];
  const trimmed  = existing.length >= MAX_LOGS_PER_AGENT
    ? existing.slice(-(MAX_LOGS_PER_AGENT - 1))
    : existing;
  return { ...prev, [agentId]: [...trimmed, { ...entry, ts: entry.ts ?? Date.now() }] };
}

// ── AgentCard ─────────────────────────────────────────────────────────────────
function AgentCard({ agent, selected, logCount, onSelect, onStart, onStop, cmdLoading }) {
  const style   = areaStyle(agent.area);
  const active  = agent.status === "running";
  const loading = cmdLoading === agent.id;

  return (
    <div
      onClick={() => onSelect(agent.id)}
      className={`bg-cyber-800 rounded-xl border p-4 flex flex-col gap-3
                  hover:bg-cyber-700/60 transition-all duration-200 cursor-pointer
                  ${selected
                    ? `${style.border} ring-1 ring-offset-0 ring-neon-blue/60`
                    : style.border
                  }`}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-sm font-semibold text-white truncate">{agent.nombre}</p>
          <p className="text-xs text-gray-700 mt-0.5 truncate">{agent.id}</p>
        </div>
        <div className="flex flex-col items-end gap-1 shrink-0">
          <div className="flex items-center gap-1.5">
            <span className={`w-2 h-2 rounded-full ${STATUS_DOT[agent.status] ?? "bg-gray-600"}`} />
            <span className="text-xs text-gray-600 capitalize">{agent.status}</span>
          </div>
          {logCount > 0 && (
            <div className="flex items-center gap-1 text-gray-700">
              <Terminal size={9} />
              <span className="text-xs tabular-nums">{logCount}</span>
            </div>
          )}
        </div>
      </div>

      {/* Badge de área */}
      <span className={`self-start px-2 py-0.5 rounded-lg text-xs font-medium ${style.color} ${style.bg}`}>
        {agent.area}
      </span>

      {/* Prompt preview */}
      {agent.prompt_base && (
        <p className="text-xs text-gray-700 line-clamp-2 leading-relaxed">
          {agent.prompt_base}
        </p>
      )}

      {/* Botón iniciar/detener — stopPropagation para no activar onSelect */}
      <button
        onClick={(e) => { e.stopPropagation(); active ? onStop(agent.id) : onStart(agent.id); }}
        disabled={loading}
        className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium
                    rounded-lg transition-colors w-full justify-center disabled:opacity-50
                    ${active
                      ? "bg-red-900/40 hover:bg-red-900/70 text-red-400"
                      : "bg-neon-green/10 hover:bg-neon-green/20 text-neon-green border border-neon-green/20"
                    }`}
      >
        {loading
          ? <svg className="animate-spin w-3 h-3" viewBox="0 0 24 24" fill="none">
              <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" strokeDasharray="30 70" />
            </svg>
          : active ? <Square size={11} /> : <Play size={11} />
        }
        {loading ? "..." : active ? "Detener" : "Iniciar"}
      </button>
    </div>
  );
}

// ── AreaGroup ─────────────────────────────────────────────────────────────────
function AreaGroup({ area, agents, logs, selectedAgent, onSelect, onStart, onStop, cmdLoading }) {
  const style   = areaStyle(area);
  const activos = agents.filter(a => a.status === "running").length;
  const [open, setOpen] = useState(true);

  return (
    <div className="flex flex-col gap-3">
      <button onClick={() => setOpen(v => !v)}
              className="flex items-center gap-3 text-left w-full">
        <div className={`h-px flex-1 border-t ${style.border} opacity-40`} />
        <span className={`text-xs font-bold tracking-widest uppercase ${style.color}`}>{area}</span>
        <span className="text-xs text-gray-700">{activos}/{agents.length}</span>
        <div className={`h-px flex-1 border-t ${style.border} opacity-40`} />
        <span className="text-gray-700 text-xs">{open ? "▲" : "▼"}</span>
      </button>

      {open && (
        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-3">
          {agents.map(agent => (
            <AgentCard
              key={agent.id}
              agent={agent}
              selected={selectedAgent === agent.id}
              logCount={(logs[agent.id] ?? []).length}
              onSelect={onSelect}
              onStart={onStart}
              onStop={onStop}
              cmdLoading={cmdLoading}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// ── AgentHub principal ────────────────────────────────────────────────────────
export default function AgentHub() {
  const [agents,        setAgents]        = useState([]);
  const [loading,       setLoading]       = useState(true);
  const [apiDown,       setApiDown]       = useState(false);
  const [wsOnline,      setWsOnline]      = useState(false);
  const [cmdLoading,    setCmdLoading]    = useState(null);
  const [modalOpen,     setModalOpen]     = useState(false);
  const [toast,         setToast]         = useState(null);
  const [selectedAgent, setSelectedAgent] = useState(null);
  const [logs,          setLogs]          = useState({});   // { [agentId]: LogEntry[] }

  const logUnsubRef = useRef(null);

  // ── Toast temporal ────────────────────────────────────────────────────────
  const showToast = (msg, type = "ok") => {
    setToast({ msg, type });
    setTimeout(() => setToast(null), 3500);
  };

  // ── Cargar agentes desde la API ───────────────────────────────────────────
  const cargarAgentes = async () => {
    setLoading(true);
    try {
      const res = await AgentService.getAll();
      setAgents(res.agentes ?? res ?? []);
      setApiDown(false);
    } catch {
      setApiDown(true);
      setAgents(FALLBACK_AGENTS);
    } finally {
      setLoading(false);
    }
  };

  // ── Suscripción a logs Tauri (stdout/stderr del proceso Python) ───────────
  useEffect(() => {
    let alive = true;
    const unlisteners = [];

    AgentService.onLog((entry) => {
      if (!alive) return;
      setLogs(prev => appendLog(prev, entry.id, entry));
    }).then(unsub => { if (alive) unlisteners.push(unsub); else unsub?.(); });

    AgentService.onStarted((e) => {
      if (!alive) return;
      setLogs(prev => appendLog(prev, e.id, {
        id: e.id, message: `Agente "${e.id}" iniciado.`, level: "system",
      }));
    }).then(unsub => { if (alive) unlisteners.push(unsub); else unsub?.(); });

    AgentService.onStopped((e) => {
      if (!alive) return;
      setLogs(prev => appendLog(prev, e.id, {
        id: e.id,
        message: e.crash
          ? `Proceso terminó con error (código ${e.code ?? "?"}).`
          : `Agente "${e.id}" detenido (código ${e.code ?? 0}).`,
        level: e.crash ? "error" : "system",
      }));
    }).then(unsub => { if (alive) unlisteners.push(unsub); else unsub?.(); });

    return () => {
      alive = false;
      unlisteners.forEach(fn => fn?.());
    };
  }, []);

  // ── WebSocket FastAPI: telemetría + eventos de sistema ────────────────────
  useEffect(() => {
    cargarAgentes();

    const unsub = AgentService.onWsMessage((msg) => {
      if (msg.tipo === "conexion") {
        setWsOnline(true);
        return;
      }

      if (msg.tipo === "agente_creado") {
        setAgents(prev => {
          if (prev.some(a => a.nombre === msg.nombre)) return prev;
          return [...prev, {
            id:          `agente_${msg.nombre.toLowerCase().replace(/\s+/g, "_")}`,
            nombre:      msg.nombre,
            area:        msg.area ?? "General",
            status:      "stopped",
            prompt_base: "",
          }];
        });
        showToast(`Agente "${msg.nombre}" registrado en el sistema.`);
        return;
      }

      // Telemetría de guardrail → log en la consola del agente
      if (msg.tipo === "telemetria" && msg.agente) {
        const ok      = msg.status === "ok";
        const durStr  = typeof msg.duracion_s === "number"
          ? ` (${msg.duracion_s.toFixed(3)}s)` : "";
        setLogs(prev => appendLog(prev, msg.agente, {
          id:      msg.agente,
          message: `[${msg.filtro ?? "pipeline"}] ${msg.status ?? "?"}${durStr}`,
          level:   ok ? "info" : "error",
          ts:      Date.now(),
        }));
      }

      // Guardrail abort → log de error + notificación nativa de escritorio
      if (msg.tipo === "pipeline_abortado" && msg.agente) {
        setLogs(prev => appendLog(prev, msg.agente, {
          id:      msg.agente,
          message: `[Guardrail] Pipeline abortado — ${msg.motivo ?? "sin motivo"}`,
          level:   "error",
          ts:      Date.now(),
        }));
        AgentService.sendNotification(
          "AgentDesk — Guardrail activado",
          `Agente: ${msg.agente}\n${msg.motivo ?? "Pipeline abortado tras máximos intentos"}`,
        );
      }
    });

    return () => {
      unsub?.();
      setWsOnline(false);
    };
  }, []);

  // ── Comandos run / stop ───────────────────────────────────────────────────
  const handleStart = async (id) => {
    setCmdLoading(id);
    setSelectedAgent(id);   // auto-seleccionar para ver logs en consola
    try {
      await AgentService.run(id);
      setAgents(prev => prev.map(a => a.id === id ? { ...a, status: "running" } : a));
    } catch (e) {
      showToast(String(e), "error");
      setLogs(prev => appendLog(prev, id, {
        id, message: String(e), level: "error",
      }));
    } finally {
      setCmdLoading(null);
    }
  };

  const handleStop = async (id) => {
    setCmdLoading(id);
    try {
      await AgentService.stop(id);
      setAgents(prev => prev.map(a => a.id === id ? { ...a, status: "stopped" } : a));
    } catch (e) {
      showToast(String(e), "error");
    } finally {
      setCmdLoading(null);
    }
  };

  // ── Modal: agente creado ──────────────────────────────────────────────────
  const handleCreated = (nuevo) => {
    showToast(`Agente "${nuevo.nombre}" enviado al Orquestador.`);
    setAgents(prev => {
      if (prev.some(a => a.nombre === nuevo.nombre)) return prev;
      return [...prev, { ...nuevo, status: "stopped" }];
    });
  };

  // ── Limpiar logs de un agente ─────────────────────────────────────────────
  const clearLogs = (id) => {
    setLogs(prev => ({ ...prev, [id]: [] }));
  };

  // ── Descargar PDF de reporte ──────────────────────────────────────────────
  const handleDownloadPdf = async (id) => {
    try {
      const res = await fetch(`${API_BASE}/agentes/${encodeURIComponent(id)}/reporte`);
      if (res.status === 404) {
        showToast(
          "Sin reporte PDF para este agente. Ejecuta el pipeline completo primero.",
          "error",
        );
        return;
      }
      if (!res.ok) throw new Error(`Error ${res.status}`);

      const blob     = await res.blob();
      const blobUrl  = URL.createObjectURL(blob);
      const filename = res.headers.get("Content-Disposition")?.match(/filename="?([^"]+)"?/)?.[1]
                    ?? `reporte_${id}.pdf`;
      const a = document.createElement("a");
      a.href     = blobUrl;
      a.download = filename;
      a.click();
      URL.revokeObjectURL(blobUrl);
      showToast(`PDF descargado: ${filename}`);
    } catch (e) {
      showToast(`Error al descargar PDF: ${e.message}`, "error");
    }
  };

  // ── Agrupar por área ──────────────────────────────────────────────────────
  const grupos = useMemo(() => {
    const mapa = new Map();
    for (const a of agents) {
      const key = a.area ?? "General";
      if (!mapa.has(key)) mapa.set(key, []);
      mapa.get(key).push(a);
    }
    return Array.from(mapa.entries());
  }, [agents]);

  const totalActivos = agents.filter(a => a.status === "running").length;
  const selectedLogs = selectedAgent ? (logs[selectedAgent] ?? []) : [];

  return (
    <div className="min-h-screen bg-cyber-900 text-gray-100 font-mono flex flex-col">

      {/* Header ──────────────────────────────────────────────────────────── */}
      <header className="flex items-center gap-3 px-6 py-3
                         border-b border-cyber-600 bg-cyber-800 shrink-0">
        <div className="w-2 h-2 rounded-full bg-neon-blue animate-pulse" />
        <h1 className="text-sm font-semibold tracking-widest uppercase text-neon-blue">
          Orchestrator Hub
        </h1>

        <div className="flex items-center gap-3 ml-auto">
          <div className={`flex items-center gap-1.5 text-xs ${wsOnline ? "text-neon-green" : "text-gray-600"}`}>
            {wsOnline ? <Wifi size={12} /> : <WifiOff size={12} />}
            {wsOnline ? "WS conectado" : "WS desconectado"}
          </div>

          <span className="text-xs text-gray-600">
            {totalActivos} activo{totalActivos !== 1 ? "s" : ""} / {agents.length}
          </span>

          <button onClick={cargarAgentes}
                  className="p-1.5 text-gray-600 hover:text-gray-300
                             hover:bg-cyber-700 rounded-lg transition-colors">
            <RefreshCw size={13} />
          </button>

          <button
            onClick={() => setModalOpen(true)}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold
                       bg-neon-blue/15 hover:bg-neon-blue/30
                       border border-neon-blue/40 hover:border-neon-blue
                       text-neon-blue rounded-lg transition-all"
          >
            <Plus size={13} />
            Nuevo Agente
          </button>
        </div>
      </header>

      {/* Contenido ───────────────────────────────────────────────────────── */}
      <div className="flex-1 overflow-y-auto p-5 flex flex-col gap-6">

        {/* Toast */}
        {toast && (
          <div className={`fixed bottom-6 right-6 z-40 px-4 py-3 rounded-xl text-sm
                           shadow-xl border transition-all
                           ${toast.type === "error"
                             ? "bg-red-900/80 border-red-500/50 text-red-300"
                             : "bg-neon-blue/10 border-neon-blue/50 text-neon-blue"
                           }`}>
            {toast.msg}
          </div>
        )}

        {/* Banner API offline */}
        {apiDown && (
          <div className="flex items-center gap-3 px-4 py-2.5 rounded-xl
                          bg-yellow-950/60 border border-yellow-500/30 text-yellow-400 text-xs">
            <ServerCrash size={14} className="shrink-0" />
            <span>
              Servidor Python no disponible en{" "}
              <code className="text-yellow-300">localhost:8000</code>.
              Inicia el backend con{" "}
              <code className="text-yellow-300">python main.py</code>.
            </span>
            <button
              onClick={cargarAgentes}
              className="ml-auto shrink-0 px-2.5 py-1 rounded-lg bg-yellow-500/20
                         hover:bg-yellow-500/30 border border-yellow-500/40 transition-colors"
            >
              Reintentar
            </button>
          </div>
        )}

        {/* Fila 1: Mapa + Embeddings 3D */}
        <div className="grid grid-cols-1 xl:grid-cols-5 gap-5">
          <div className="xl:col-span-3">
            <ErrorBoundary>
              <AgentMap agents={agents.map(a => ({ ...a, lat: a.lat ?? 0, lng: a.lng ?? 0 }))} />
            </ErrorBoundary>
          </div>
          <div className="xl:col-span-2">
            <ErrorBoundary>
              <Suspense fallback={
                <div className="flex items-center justify-center h-72 bg-cyber-900
                                rounded-2xl border border-cyber-600 text-gray-600 text-xs">
                  Cargando visualización 3D...
                </div>
              }>
                <EmbeddingView3D />
              </Suspense>
            </ErrorBoundary>
          </div>
        </div>

        {/* Fila 2: Consola + Métricas */}
        <div className="grid grid-cols-1 lg:grid-cols-5 gap-5">
          <div className="lg:col-span-3">
            <AgentConsole
              agentId={selectedAgent}
              logs={selectedLogs}
              onClear={selectedAgent ? () => clearLogs(selectedAgent) : undefined}
              onDownloadPdf={selectedAgent ? () => handleDownloadPdf(selectedAgent) : undefined}
            />
          </div>
          <div className="lg:col-span-2">
            <AgentMetrics />
          </div>
        </div>

        {/* Fila 3: Agentes por área */}
        <section className="flex flex-col gap-6">
          <div className="flex items-center gap-2">
            <Activity size={14} className="text-neon-blue" />
            <span className="text-xs tracking-widest uppercase text-gray-600">
              Agentes por Área
            </span>
            {selectedAgent && (
              <span className="ml-auto text-xs text-gray-700">
                Haz clic en una tarjeta para ver sus logs
              </span>
            )}
          </div>

          {loading ? (
            <div className="flex items-center gap-3 text-gray-600 text-sm py-8 justify-center">
              <svg className="animate-spin w-4 h-4" viewBox="0 0 24 24" fill="none">
                <circle cx="12" cy="12" r="10" stroke="currentColor"
                        strokeWidth="3" strokeDasharray="30 70" />
              </svg>
              Conectando con el Orquestador...
            </div>
          ) : grupos.length === 0 ? (
            <p className="text-gray-700 text-sm text-center py-8">
              Sin agentes. Crea el primero con "Nuevo Agente".
            </p>
          ) : (
            grupos.map(([area, areaAgents]) => (
              <AreaGroup
                key={area}
                area={area}
                agents={areaAgents}
                logs={logs}
                selectedAgent={selectedAgent}
                onSelect={setSelectedAgent}
                onStart={handleStart}
                onStop={handleStop}
                cmdLoading={cmdLoading}
              />
            ))
          )}
        </section>
      </div>

      <NewAgentModal
        isOpen={modalOpen}
        onClose={() => setModalOpen(false)}
        onCreated={handleCreated}
      />
    </div>
  );
}
