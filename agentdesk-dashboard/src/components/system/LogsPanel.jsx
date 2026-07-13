/**
 * LogsPanel.jsx — Pestaña "Visor de Logs": lee `sistema.log` vía `GET /logs`,
 * con filtro por nivel, agente y texto libre, auto-refresco opcional y
 * refresco automático al recibir eventos de tareas por WebSocket.
 *
 * Reconstruido desde el bundle de producción (react_dist/assets/index-CRDO1T5r.js,
 * función `Vw`): el fuente original de este componente no estaba versionado.
 */
import { useState, useEffect, useCallback, useRef } from "react";
import { RefreshCw } from "../../icons.js";
import { API_BASE, AgentService } from "../../services/agent.service";

const NIVEL_COLOR = {
  DEBUG: "#475569",
  INFO: "#00d4ff",
  WARNING: "#f59e0b",
  ERROR: "#ff2d55",
  CRITICAL: "#ff2d55",
};
const NIVELES = ["todos", "DEBUG", "INFO", "WARNING", "ERROR"];
const LINEAS = [50, 100, 200, 500];

export default function LogsPanel() {
  const [entradas, setEntradas] = useState([]);
  const [cargando, setCargando] = useState(false);
  const [auto, setAuto] = useState(false);
  const [nivel, setNivel] = useState("todos");
  const [agenteFiltro, setAgenteFiltro] = useState("");
  const [busqueda, setBusqueda] = useState("");
  const [n, setN] = useState(100);
  const intervalRef = useRef(null);

  const cargar = useCallback(() => {
    setCargando(true);
    const url =
      nivel !== "todos"
        ? `${API_BASE}/logs?n=${n}&nivel=${nivel}`
        : `${API_BASE}/logs?n=${n}`;
    fetch(url)
      .then((r) => r.json())
      .then((d) => {
        setEntradas(d.entradas ?? []);
        setCargando(false);
      })
      .catch(() => setCargando(false));
  }, [n, nivel]);

  useEffect(() => {
    cargar();
  }, [cargar]);
  useEffect(() => {
    clearInterval(intervalRef.current);
    if (auto) intervalRef.current = setInterval(cargar, 3000);
    return () => clearInterval(intervalRef.current);
  }, [auto, cargar]);
  useEffect(
    () =>
      AgentService.onWsMessage((msg) => {
        if (
          [
            "tarea_completada",
            "tarea_abortada",
            "tarea_error",
            "agente_ejecutando",
            "todos_completados",
          ].includes(msg.tipo)
        ) {
          setTimeout(cargar, 500);
        }
      }),
    [cargar],
  );

  const filtradas = entradas.filter((e) => {
    if (agenteFiltro && (e.agente || "") !== agenteFiltro) return false;
    if (
      busqueda &&
      !JSON.stringify(e).toLowerCase().includes(busqueda.toLowerCase())
    )
      return false;
    return true;
  });
  const agentes = [...new Set(entradas.map((e) => e.agente).filter(Boolean))];

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: "1rem",
        height: "100%",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          flexWrap: "wrap",
          gap: ".5rem",
        }}
      >
        <div style={{ display: "flex", gap: ".35rem", flexWrap: "wrap" }}>
          {NIVELES.map((lvl) => (
            <button
              key={lvl}
              onClick={() => setNivel(lvl)}
              style={{
                padding: "3px 10px",
                borderRadius: 20,
                fontSize: ".7rem",
                fontWeight: 600,
                cursor: "pointer",
                fontFamily: "inherit",
                border:
                  nivel === lvl
                    ? `1px solid ${NIVEL_COLOR[lvl] || "var(--t-accent)"}`
                    : "1px solid var(--t-border)",
                background:
                  nivel === lvl
                    ? `${NIVEL_COLOR[lvl] || "var(--t-accent)"}18`
                    : "transparent",
                color:
                  nivel === lvl
                    ? NIVEL_COLOR[lvl] || "var(--t-accent)"
                    : "var(--t-text-muted)",
              }}
            >
              {lvl}
            </button>
          ))}
        </div>
        <div style={{ display: "flex", gap: ".4rem", alignItems: "center" }}>
          {agentes.length > 0 && (
            <select
              value={agenteFiltro}
              onChange={(e) => setAgenteFiltro(e.target.value)}
              style={selectStyle}
            >
              <option value="">Todos los agentes</option>
              {agentes.map((a) => (
                <option key={a} value={a}>
                  {a}
                </option>
              ))}
            </select>
          )}
          <input
            value={busqueda}
            onChange={(e) => setBusqueda(e.target.value)}
            placeholder="Buscar en logs..."
            style={{ ...selectStyle, width: 150 }}
          />
          <select
            value={n}
            onChange={(e) => setN(Number(e.target.value))}
            style={selectStyle}
          >
            {LINEAS.map((v) => (
              <option key={v} value={v}>
                {v} líneas
              </option>
            ))}
          </select>
          <button
            onClick={() => setAuto((a) => !a)}
            style={{
              padding: "4px 10px",
              borderRadius: 8,
              cursor: "pointer",
              fontFamily: "inherit",
              border: auto
                ? "1px solid var(--t-accent)"
                : "1px solid var(--t-border)",
              background: auto ? "rgba(0,212,255,.12)" : "transparent",
              color: auto ? "var(--t-accent)" : "var(--t-text-muted)",
              fontSize: ".72rem",
              fontWeight: 600,
            }}
          >
            {auto ? "⏸ Auto" : "▶ Auto"}
          </button>
          <button
            onClick={cargar}
            style={{
              padding: "4px 8px",
              borderRadius: 8,
              border: "1px solid var(--t-border)",
              background: "transparent",
              color: "var(--t-text-muted)",
              cursor: "pointer",
            }}
          >
            <RefreshCw
              size={14}
              style={{
                animation: cargando ? "spin .8s linear infinite" : "none",
              }}
            />
          </button>
        </div>
      </div>

      <div style={{ fontSize: ".7rem", color: "var(--t-text-muted)" }}>
        {filtradas.length} entradas
        {auto && (
          <span style={{ color: "var(--t-accent)", marginLeft: 8 }}>
            ● actualizando
          </span>
        )}
      </div>

      <div
        style={{
          flex: 1,
          overflowY: "auto",
          fontFamily: "monospace",
          fontSize: ".72rem",
          background: "var(--t-bg)",
          borderRadius: 10,
          border: "1px solid var(--t-border)",
          padding: ".5rem",
          minHeight: 300,
          maxHeight: "60vh",
        }}
      >
        {filtradas.length === 0 ? (
          <div
            style={{
              padding: "2rem",
              textAlign: "center",
              color: "var(--t-text-muted)",
            }}
          >
            {cargando ? "Cargando..." : "Sin entradas de log."}
          </div>
        ) : (
          filtradas.map((e, i) => {
            const color = NIVEL_COLOR[e.level] ?? "#64748b";
            return (
              <div
                key={i}
                style={{
                  padding: "3px 6px",
                  borderRadius: 4,
                  marginBottom: 2,
                  display: "grid",
                  gridTemplateColumns: "120px 60px 140px 1fr",
                  gap: ".4rem",
                  alignItems: "start",
                  background:
                    e.level === "ERROR"
                      ? "rgba(255,45,85,.06)"
                      : e.level === "WARNING"
                        ? "rgba(245,158,11,.04)"
                        : "transparent",
                }}
              >
                <span style={{ color: "#475569" }}>
                  {e.timestamp
                    ? new Date(e.timestamp).toLocaleTimeString("es", {
                        hour12: false,
                      })
                    : ""}
                </span>
                <span style={{ color, fontWeight: 700 }}>{e.level}</span>
                <span
                  style={{
                    color: "var(--t-accent)",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                >
                  {e.agente || e.logger || ""}
                </span>
                <span
                  style={{ color: "var(--t-text)", wordBreak: "break-word" }}
                >
                  {e.message}
                  {e.filtro && (
                    <span style={{ color, marginLeft: 6 }}>[{e.filtro}]</span>
                  )}
                  {e.duracion_s != null && (
                    <span style={{ color: "#64748b", marginLeft: 6 }}>
                      {e.duracion_s.toFixed(4)}s
                    </span>
                  )}
                </span>
              </div>
            );
          })
        )}
      </div>
      <style>{"@keyframes spin{to{transform:rotate(360deg)}}"}</style>
    </div>
  );
}

const selectStyle = {
  padding: "4px 8px",
  borderRadius: 8,
  border: "1px solid var(--t-border)",
  background: "var(--t-bg-card)",
  color: "var(--t-text)",
  fontSize: ".75rem",
  outline: "none",
  fontFamily: "inherit",
};
