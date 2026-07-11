/**
 * AgentPerformancePanel.jsx — Rendimiento por agente + estado de tareas en tiempo real.
 *
 * Muestra dos tablas en el dashboard:
 *   1. "Rendimiento por Agente": tasa de éxito, latencia promedio, tendencia y estado.
 *   2. "Estado de Tareas en Tiempo Real": tarea en curso, progreso estimado y tiempo.
 *
 * Las estadísticas se acumulan escuchando el WebSocket del backend
 * (agente_ejecutando / tarea_completada / tarea_abortada / tarea_error /
 * todos_ejecutando) y se persisten en localStorage.
 *
 * Reconstruido desde el bundle de producción (react_dist/assets/index-CRDO1T5r.js,
 * función `Db`): el fuente original de este componente no estaba versionado.
 */
import { useState, useEffect, useRef } from "react";
import { RefreshCw } from "../../icons.js";
import { AgentService, API_BASE } from "../../services/agent.service";

const STATS_KEY = "agentdesk-agent-stats-v2";

function cargarStats() {
  try {
    return JSON.parse(localStorage.getItem(STATS_KEY) ?? "{}");
  } catch {
    return {};
  }
}

function guardarStats(stats) {
  try {
    localStorage.setItem(STATS_KEY, JSON.stringify(stats));
  } catch { /* almacenamiento no disponible */ }
}

function statsVacias() {
  return {
    ok: 0,
    fail: 0,
    latencias: [],
    ultimasTareas: [],
    ultima_ts: null,
    tarea_inicio: null,
  };
}

/* Tasa de éxito en % (null si no hay tareas registradas) */
function tasaExito(s) {
  const total = s.ok + s.fail;
  return total === 0 ? null : Math.round((s.ok / total) * 100);
}

/* Latencia promedio (s) de las últimas 10 tareas */
function latenciaProm(s) {
  return s.latencias.length
    ? (
        s.latencias.slice(-10).reduce((acc, l) => acc + l, 0) /
        Math.min(s.latencias.length, 10)
      ).toFixed(3)
    : null;
}

/* Tendencia según las últimas 5 tareas */
function tendencia(s) {
  const ultimas = s.ultimasTareas.slice(-5);
  if (ultimas.length < 2) return "nueva";
  const score = ultimas.reduce((acc, t) => acc + (t === "ok" ? 1 : -1), 0);
  return score >= 3 ? "mejora" : score <= -2 ? "empeora" : "estable";
}

function estadoDeTasa(tasa) {
  return tasa === null
    ? { emoji: "❓", label: "Sin datos", color: "#64748b" }
    : tasa >= 95
      ? { emoji: "😊", label: "Excelente", color: "#00ff9d" }
      : tasa >= 80
        ? { emoji: "😐", label: "Aceptable", color: "#f59e0b" }
        : { emoji: "😟", label: "Revisar", color: "#ff2d55" };
}

function displayTendencia(t) {
  const MAP = {
    mejora:  { icon: "↑", label: "Mejorando",     color: "#00ff9d" },
    estable: { icon: "=", label: "Estable",       color: "#f59e0b" },
    empeora: { icon: "↓", label: "Empeorando",    color: "#ff2d55" },
    nueva:   { icon: "✦", label: "Sin historial", color: "#64748b" },
  };
  return MAP[t] ?? MAP.nueva;
}

/* ms transcurridos → "42s" / "2m 5s" */
function fmtTiempo(ms) {
  if (!ms) return "—";
  const s = Math.floor(ms / 1000);
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${s % 60}s`;
}

export default function AgentPerformancePanel() {
  const [agentes, setAgentes] = useState([]);
  const [stats,   setStats]   = useState(cargarStats);
  const [running, setRunning] = useState({});
  const [now,     setNow]     = useState(Date.now());
  const statsRef   = useRef(stats);
  const runningRef = useRef(running);
  statsRef.current   = stats;
  runningRef.current = running;

  // Reloj para el tiempo transcurrido de tareas activas
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  // Carga inicial de agentes + inicialización de stats para ids nuevos
  useEffect(() => {
    fetch(`${API_BASE}/agentes`)
      .then(r => r.json())
      .then(data => {
        const lista = data.agentes ?? [];
        setAgentes(lista);
        setStats(prev => {
          const next = { ...prev };
          lista.forEach(a => { if (!next[a.id]) next[a.id] = statsVacias(); });
          guardarStats(next);
          return next;
        });
      })
      .catch(() => {});
  }, []);

  // Eventos del WebSocket del backend
  useEffect(() =>
    AgentService.onWsMessage(msg => {
      const id = msg.agente_id;
      if (!id) return;

      if (msg.tipo === "agente_ejecutando") {
        setRunning(prev => ({
          ...prev,
          [id]: { tarea: msg.tarea || "Tarea en curso", inicio: Date.now(), estado: "ACTIVO" },
        }));
        setStats(prev => {
          const next = { ...prev, [id]: { ...(prev[id] || statsVacias()), tarea_inicio: Date.now() } };
          guardarStats(next);
          return next;
        });
      }

      if (msg.tipo === "tarea_completada") {
        const inicio = runningRef.current[id]?.inicio ?? statsRef.current[id]?.tarea_inicio;
        const durMs  = inicio ? Date.now() - inicio : null;
        setRunning(prev => {
          const next = { ...prev };
          delete next[id];
          return next;
        });
        setStats(prev => {
          const s = { ...(prev[id] || statsVacias()) };
          s.ok++;
          s.ultima_ts = Date.now();
          s.ultimasTareas = [...(s.ultimasTareas || []).slice(-14), "ok"];
          if (durMs && durMs > 100 && durMs < 300000) {
            s.latencias = [...(s.latencias || []).slice(-19), durMs / 1000];
          }
          const next = { ...prev, [id]: s };
          guardarStats(next);
          return next;
        });
      }

      if (msg.tipo === "tarea_abortada" || msg.tipo === "tarea_error") {
        setRunning(prev => {
          const next = { ...prev };
          delete next[id];
          return next;
        });
        setStats(prev => {
          const s = { ...(prev[id] || statsVacias()) };
          s.fail++;
          s.ultima_ts = Date.now();
          s.ultimasTareas = [...(s.ultimasTareas || []).slice(-14), "fail"];
          const next = { ...prev, [id]: s };
          guardarStats(next);
          return next;
        });
      }

      if (msg.tipo === "todos_ejecutando") {
        const ids = msg.agentes ?? [];
        setRunning(prev => {
          const next = { ...prev };
          ids.forEach(aid => {
            next[aid] = { tarea: "Pipeline completo", inicio: Date.now(), estado: "ACTIVO" };
          });
          return next;
        });
      }
    }),
  []);

  function resetear() {
    const limpio = {};
    agentes.forEach(a => { limpio[a.id] = statsVacias(); });
    guardarStats(limpio);
    setStats(limpio);
    setRunning({});
  }

  if (agentes.length === 0) return null;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
      {/* ── Tabla 1: Rendimiento por Agente ─────────────────────────────── */}
      <div style={{
        borderRadius: 14, border: "1px solid var(--t-border)",
        overflow: "hidden", background: "var(--t-bg-surface)",
      }}>
        <div style={{
          display: "flex", alignItems: "center", justifyContent: "space-between",
          padding: "12px 16px", borderBottom: "1px solid var(--t-border)",
          background: "rgba(0,212,255,.04)",
        }}>
          <div style={{ fontWeight: 700, fontSize: ".85rem", color: "var(--t-text)" }}>
            📊 Rendimiento por Agente
          </div>
          <button onClick={resetear} style={{
            padding: "3px 10px", borderRadius: 20, border: "1px solid var(--t-border)",
            background: "transparent", color: "#64748b", cursor: "pointer",
            fontSize: ".7rem", fontFamily: "inherit",
            display: "flex", alignItems: "center", gap: 5,
          }}>
            <RefreshCw size={11} /> Resetear
          </button>
        </div>

        <div style={{
          display: "grid", gridTemplateColumns: "1.6fr .8fr .9fr 1.1fr .7fr",
          padding: "8px 16px", borderBottom: "1px solid var(--t-border)",
          fontSize: ".68rem", fontWeight: 700, textTransform: "uppercase",
          letterSpacing: ".05em", color: "var(--t-text-muted)",
          background: "var(--t-bg-base)",
        }}>
          <span>Agente</span><span>Tasa Éxito</span><span>Latencia prom.</span>
          <span>Tendencia</span><span>Estado</span>
        </div>

        {agentes.map((ag, idx) => {
          const s      = stats[ag.id] || statsVacias();
          const tasa   = tasaExito(s);
          const lat    = latenciaProm(s);
          const tend   = tendencia(s);
          const estado = estadoDeTasa(tasa);
          const dTend  = displayTendencia(tend);
          const total  = s.ok + s.fail;
          const activo = !!running[ag.id];
          return (
            <div key={ag.id} style={{
              display: "grid", gridTemplateColumns: "1.6fr .8fr .9fr 1.1fr .7fr",
              padding: "14px 16px", alignItems: "center",
              borderBottom: idx < agentes.length - 1 ? "1px solid var(--t-border)" : "none",
              background: activo ? "rgba(0,212,255,.03)" : "transparent",
              transition: "background .2s",
            }}>
              {/* Agente */}
              <div style={{ display: "flex", alignItems: "center", gap: 9 }}>
                <div style={{
                  width: 32, height: 32, borderRadius: "50%", flexShrink: 0,
                  background: "rgba(0,212,255,.12)", border: "1px solid rgba(0,212,255,.3)",
                  display: "flex", alignItems: "center", justifyContent: "center", fontSize: 15,
                }}>🤖</div>
                <div>
                  <div style={{ fontWeight: 700, fontSize: ".82rem", color: "var(--t-text)" }}>
                    {ag.nombre}
                  </div>
                  <div style={{ fontSize: ".66rem", color: "var(--t-text-muted)" }}>
                    {ag.area} · {total} tareas
                  </div>
                </div>
              </div>

              {/* Tasa de éxito */}
              <div>
                <div style={{ fontWeight: 800, fontSize: ".95rem", color: estado.color }}>
                  {tasa !== null ? `${tasa}%` : "—"}
                </div>
                {total > 0 && (
                  <div style={{ marginTop: 4, height: 4, borderRadius: 4, background: "var(--t-border)", width: 60 }}>
                    <div style={{
                      height: "100%", borderRadius: 4, width: `${tasa}%`,
                      background: tasa >= 95 ? "#00ff9d" : tasa >= 80 ? "#f59e0b" : "#ff2d55",
                      transition: "width .4s",
                    }} />
                  </div>
                )}
                <div style={{ fontSize: ".63rem", color: "#475569", marginTop: 2 }}>
                  {s.ok}✓ {s.fail}✗
                </div>
              </div>

              {/* Latencia promedio + mini-barras */}
              <div>
                <div style={{ fontWeight: 700, fontSize: ".88rem", color: "var(--t-text)" }}>
                  {lat ? `${lat}s` : "—"}
                </div>
                <div style={{ display: "flex", gap: 1, marginTop: 4, alignItems: "flex-end", height: 14 }}>
                  {(s.latencias.slice(-8) || []).map((l, i) => {
                    const max = Math.max(...s.latencias.slice(-8), 1);
                    const h   = Math.max(2, (l / max) * 14);
                    return (
                      <div key={i} style={{
                        width: 4, height: h, borderRadius: 1,
                        background: l > 2 ? "#ff2d55" : l > 0.5 ? "#f59e0b" : "#00ff9d",
                        opacity: 0.8,
                      }} />
                    );
                  })}
                </div>
              </div>

              {/* Tendencia */}
              <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
                <div style={{
                  width: 28, height: 28, borderRadius: "50%", flexShrink: 0,
                  background: `${dTend.color}18`, border: `1.5px solid ${dTend.color}50`,
                  display: "flex", alignItems: "center", justifyContent: "center",
                  fontSize: 14, fontWeight: 800, color: dTend.color,
                }}>{dTend.icon}</div>
                <div>
                  <div style={{ fontSize: ".78rem", fontWeight: 600, color: dTend.color }}>
                    {dTend.label}
                  </div>
                  <div style={{ display: "flex", gap: 2, marginTop: 3 }}>
                    {(s.ultimasTareas.slice(-5) || []).map((t, i) => (
                      <div key={i} style={{
                        width: 6, height: 6, borderRadius: "50%",
                        background: t === "ok" ? "#00ff9d" : "#ff2d55",
                      }} />
                    ))}
                    {Array.from({ length: Math.max(0, 5 - (s.ultimasTareas?.length ?? 0)) }).map((_, i) => (
                      <div key={`e${i}`} style={{
                        width: 6, height: 6, borderRadius: "50%", background: "#1e293b",
                      }} />
                    ))}
                  </div>
                </div>
              </div>

              {/* Estado */}
              <div style={{ textAlign: "center" }}>
                <div style={{ fontSize: 22 }}>{estado.emoji}</div>
                <div style={{ fontSize: ".62rem", color: estado.color, fontWeight: 600, marginTop: 2 }}>
                  {estado.label}
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* ── Tabla 2: Estado de Tareas en Tiempo Real ────────────────────── */}
      <div style={{
        borderRadius: 14, border: "1px solid var(--t-border)",
        overflow: "hidden", background: "var(--t-bg-surface)",
      }}>
        <div style={{
          padding: "12px 16px", borderBottom: "1px solid var(--t-border)",
          background: "rgba(0,255,157,.04)", fontWeight: 700,
          fontSize: ".85rem", color: "var(--t-text)",
        }}>
          ⚡ Estado de Tareas en Tiempo Real
        </div>

        <div style={{
          display: "grid", gridTemplateColumns: "1.6fr 1.4fr .8fr 1.4fr .8fr",
          padding: "8px 16px", borderBottom: "1px solid var(--t-border)",
          fontSize: ".68rem", fontWeight: 700, textTransform: "uppercase",
          letterSpacing: ".05em", color: "var(--t-text-muted)",
          background: "var(--t-bg-base)",
        }}>
          <span>Agente</span><span>Tarea</span><span>Estado</span>
          <span>Progreso</span><span>Tiempo</span>
        </div>

        {agentes.map((ag, idx) => {
          const s       = stats[ag.id] || statsVacias();
          const tarea   = running[ag.id];
          const activo  = !!tarea;
          const elapsed = tarea ? now - tarea.inicio : null;
          // Duración estimada (ms) = promedio de las últimas 5 latencias
          const estMs = s.latencias.length
            ? (s.latencias.slice(-5).reduce((acc, l) => acc + l, 0) /
               Math.min(s.latencias.length, 5)) * 1000
            : null;
          const progreso = activo && estMs && elapsed
            ? Math.min(95, Math.round((elapsed / estMs) * 100))
            : null;
          const ultimaHora = s.ultima_ts
            ? new Date(s.ultima_ts).toLocaleTimeString("es", { hour: "2-digit", minute: "2-digit" })
            : null;
          return (
            <div key={ag.id} style={{
              display: "grid", gridTemplateColumns: "1.6fr 1.4fr .8fr 1.4fr .8fr",
              padding: "13px 16px", alignItems: "center",
              borderBottom: idx < agentes.length - 1 ? "1px solid var(--t-border)" : "none",
              background: activo ? "rgba(0,255,157,.025)" : "transparent",
              transition: "background .2s",
            }}>
              {/* Agente + indicador de actividad */}
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <div style={{ position: "relative" }}>
                  <div style={{
                    width: 10, height: 10, borderRadius: "50%",
                    background: activo ? "#00ff9d" : "#334155",
                    boxShadow: activo ? "0 0 8px #00ff9d" : "none",
                    transition: "all .3s",
                  }} />
                  {activo && (
                    <div style={{
                      position: "absolute", top: -2, left: -2, width: 14, height: 14,
                      borderRadius: "50%", border: "1.5px solid #00ff9d", opacity: 0.5,
                      animation: "ping 1.2s ease-out infinite",
                    }} />
                  )}
                </div>
                <div>
                  <div style={{ fontWeight: 600, fontSize: ".82rem", color: "var(--t-text)" }}>
                    {ag.nombre}
                  </div>
                  <div style={{ fontSize: ".65rem", color: "#475569" }}>{ag.area}</div>
                </div>
              </div>

              {/* Tarea */}
              <div>
                <div style={{
                  fontSize: ".78rem",
                  color: activo ? "var(--t-text)" : "#475569",
                  fontWeight: activo ? 600 : 400,
                  overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                }}>
                  {activo ? tarea.tarea : ultimaHora ? `Última: ${ultimaHora}` : "Sin tareas aún"}
                </div>
              </div>

              {/* Estado */}
              <div>
                <span style={{
                  padding: "3px 9px", borderRadius: 20, fontSize: ".68rem", fontWeight: 700,
                  background: activo ? "rgba(0,255,157,.15)" : "rgba(100,116,139,.1)",
                  color: activo ? "#00ff9d" : "#64748b",
                  border: activo ? "1px solid rgba(0,255,157,.3)" : "1px solid rgba(100,116,139,.2)",
                }}>
                  {activo ? "ACTIVO" : "LISTO"}
                </span>
              </div>

              {/* Progreso */}
              <div>
                {activo ? (
                  <>
                    <div style={{
                      display: "flex", alignItems: "center",
                      justifyContent: "space-between", marginBottom: 4,
                    }}>
                      <span style={{ fontSize: ".7rem", color: "#00ff9d", fontWeight: 700 }}>
                        {progreso !== null ? `${progreso}%` : "Procesando..."}
                      </span>
                    </div>
                    <div style={{ height: 6, borderRadius: 6, background: "var(--t-border)", overflow: "hidden" }}>
                      {progreso !== null ? (
                        <div style={{
                          height: "100%", borderRadius: 6, width: `${progreso}%`,
                          background: "linear-gradient(90deg,#00ff9d,#00d4ff)",
                          transition: "width .5s",
                        }} />
                      ) : (
                        <div style={{
                          height: "100%", width: "30%", borderRadius: 6,
                          background: "linear-gradient(90deg,#00ff9d,#00d4ff)",
                          animation: "slide 1.2s ease-in-out infinite alternate",
                        }} />
                      )}
                    </div>
                  </>
                ) : (
                  <div style={{ height: 6, borderRadius: 6, background: "var(--t-border)" }}>
                    <div style={{ height: "100%", borderRadius: 6, width: "100%", background: "#1e293b" }} />
                  </div>
                )}
              </div>

              {/* Tiempo */}
              <div style={{
                fontSize: ".78rem",
                color: activo ? "#00d4ff" : "#475569",
                fontWeight: activo ? 600 : 400,
              }}>
                {activo ? fmtTiempo(elapsed) : "—"}
              </div>
            </div>
          );
        })}
      </div>

      <style>{`
        @keyframes ping   { 0%{transform:scale(1);opacity:.6} 100%{transform:scale(2.2);opacity:0} }
        @keyframes slide  { from{margin-left:0} to{margin-left:70%} }
        @keyframes spin   { to{transform:rotate(360deg)} }
      `}</style>
    </div>
  );
}
