/**
 * AgentFlowEditor.jsx — Pestaña "Editor de Flujo" dentro de Agentes.
 *
 * Editor visual (SVG) de encadenamiento de agentes: arrastrar nodos, conectar
 * uno con otro (define `siguiente_agente_id`) y desconectar haciendo clic en
 * la flecha. Los cambios se guardan llamando a `AgentService.update`.
 *
 * Reconstruido desde el bundle de producción (react_dist/assets/index-CRDO1T5r.js,
 * función `d6`): el fuente original de este componente no estaba versionado.
 * A diferencia del bundle original (que leía el estado de un store zustand
 * `agentes`/`actualizarAgente` ya no presente en el código fuente actual), esta
 * reconstrucción obtiene y guarda los agentes directamente vía `AgentService`.
 */
import { useState, useEffect, useCallback, useRef } from "react";
import { RefreshCw, Save } from "../../icons.js";
import { AgentService } from "../../services/agent.service";
import { addNotification } from "../ui/NotificationSystem";

const AREA_COLOR = {
  Finanzas: "#00d4ff",
  Mecánica: "#00ff9d",
  RRHH: "#f59e0b",
  Logística: "#8b5cf6",
  Marketing: "#ef4444",
  Legal: "#f97316",
  Tecnología: "#06b6d4",
  Operaciones: "#84cc16",
  General: "#64748b",
};
function areaColor(area) {
  return AREA_COLOR[area] ?? "#64748b";
}

const NODE_W = 180,
  NODE_H = 72,
  GAP = 60;

export default function AgentFlowEditor() {
  const [agentesRemotos, setAgentesRemotos] = useState([]);
  const [nodos, setNodos] = useState([]);
  const [arrastrando, setArrastrando] = useState(null);
  const [conectando, setConectando] = useState(null);
  const [hover, setHover] = useState(null);
  const [guardando, setGuardando] = useState(false);
  const [sucio, setSucio] = useState(false);
  const svgRef = useRef(null);

  const cargarAgentes = useCallback(async () => {
    try {
      const data = await AgentService.getAll();
      setAgentesRemotos(data.agentes ?? []);
    } catch {
      /* sin conexión */
    }
  }, []);

  useEffect(() => {
    cargarAgentes();
  }, [cargarAgentes]);

  useEffect(() => {
    if (agentesRemotos.length) {
      setNodos(
        agentesRemotos.map((a, i) => ({
          id: a.id,
          nombre: a.nombre,
          area: a.area || "General",
          modelo: (a.modelo || "").replace("models/", ""),
          siguiente: a.siguiente_agente_id || null,
          x: 60 + (i % 3) * (NODE_W + GAP),
          y: 80 + Math.floor(i / 3) * (NODE_H + GAP + 20),
        })),
      );
      setSucio(false);
    }
  }, [agentesRemotos]);

  function onNodeMouseDown(e, id) {
    if (conectando) return;
    e.preventDefault();
    const nodo = nodos.find((n) => n.id === id);
    setArrastrando({ id, ox: e.clientX - nodo.x, oy: e.clientY - nodo.y });
  }
  const onSvgMouseMove = useCallback(
    (e) => {
      if (!arrastrando) return;
      setNodos((list) =>
        list.map((n) =>
          n.id === arrastrando.id
            ? {
                ...n,
                x: Math.max(0, e.clientX - arrastrando.ox),
                y: Math.max(0, e.clientY - arrastrando.oy),
              }
            : n,
        ),
      );
    },
    [arrastrando],
  );
  const onSvgMouseUp = () => setArrastrando(null);

  function iniciarConexion(e, id) {
    e.stopPropagation();
    setConectando(id);
  }
  function completarConexion(id) {
    if (!conectando || conectando === id) {
      setConectando(null);
      return;
    }
    setNodos((list) =>
      list.map((n) => (n.id === conectando ? { ...n, siguiente: id } : n)),
    );
    setConectando(null);
    setSucio(true);
  }
  function desconectar(id) {
    setNodos((list) =>
      list.map((n) => (n.id === id ? { ...n, siguiente: null } : n)),
    );
    setSucio(true);
  }

  async function guardarFlujo() {
    setGuardando(true);
    try {
      for (const nodo of nodos) {
        const original = agentesRemotos.find((a) => a.id === nodo.id);
        const antes = original?.siguiente_agente_id || null;
        if (nodo.siguiente !== antes) {
          await AgentService.update(nodo.id, {
            siguiente_agente_id: nodo.siguiente || "",
          });
        }
      }
      setSucio(false);
      addNotification({
        message: "Flujo de agentes guardado",
        type: "success",
      });
      cargarAgentes();
    } catch (e) {
      addNotification({
        message: "Error al guardar: " + (e?.message ?? e),
        type: "error",
      });
    } finally {
      setGuardando(false);
    }
  }

  const salida = (n) => ({ x: n.x + NODE_W, y: n.y + NODE_H / 2 });
  const entrada = (n) => ({ x: n.x, y: n.y + NODE_H / 2 });

  if (!agentesRemotos.length) {
    return (
      <div
        style={{
          padding: "3rem",
          textAlign: "center",
          color: "var(--t-text-muted)",
        }}
      >
        <RefreshCw size={24} style={{ animation: "spin 1s linear infinite" }} />
        <div style={{ marginTop: "1rem" }}>Cargando agentes...</div>
        <style>{"@keyframes spin{to{transform:rotate(360deg)}}"}</style>
      </div>
    );
  }

  const width = Math.max(...nodos.map((n) => n.x + NODE_W + 60), 600);
  const height = Math.max(...nodos.map((n) => n.y + NODE_H + 60), 400);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "10px 14px",
          borderRadius: 12,
          border: "1px solid var(--t-border)",
          background: "var(--t-bg-card)",
          flexWrap: "wrap",
          gap: ".5rem",
        }}
      >
        <div>
          <div
            style={{
              fontWeight: 700,
              fontSize: ".88rem",
              color: "var(--t-text)",
            }}
          >
            🔗 Editor de Flujo de Agentes
          </div>
          <div
            style={{
              fontSize: ".72rem",
              color: "var(--t-text-muted)",
              marginTop: 2,
            }}
          >
            Arrastra nodos · Clic en → para conectar · Clic en la flecha para
            desconectar
          </div>
        </div>
        <div style={{ display: "flex", gap: ".5rem", alignItems: "center" }}>
          {sucio && (
            <span
              style={{ fontSize: ".72rem", color: "#f59e0b", fontWeight: 600 }}
            >
              ● Cambios sin guardar
            </span>
          )}
          <button
            onClick={cargarAgentes}
            style={{
              padding: "6px 12px",
              borderRadius: 8,
              border: "1px solid var(--t-border)",
              background: "transparent",
              color: "var(--t-text-muted)",
              cursor: "pointer",
              fontFamily: "inherit",
              fontSize: ".75rem",
              display: "flex",
              alignItems: "center",
              gap: 5,
            }}
          >
            <RefreshCw size={13} /> Reset
          </button>
          <button
            onClick={guardarFlujo}
            disabled={!sucio || guardando}
            style={{
              padding: "6px 14px",
              borderRadius: 8,
              border: "none",
              background:
                sucio && !guardando
                  ? "linear-gradient(90deg,var(--t-accent),var(--t-accent2,var(--t-accent)))"
                  : "var(--t-border)",
              color: sucio && !guardando ? "#0a0e1a" : "var(--t-text-muted)",
              cursor: sucio && !guardando ? "pointer" : "default",
              fontFamily: "inherit",
              fontSize: ".78rem",
              fontWeight: 700,
              display: "flex",
              alignItems: "center",
              gap: 5,
            }}
          >
            <Save size={14} /> {guardando ? "Guardando..." : "Guardar Flujo"}
          </button>
        </div>
      </div>

      <div
        style={{
          borderRadius: 14,
          border: "1px solid var(--t-border)",
          overflow: "auto",
          background:
            "radial-gradient(circle at 50% 50%, #070f28 0%, #020610 100%)",
          cursor: conectando ? "crosshair" : "default",
          minHeight: 400,
        }}
      >
        <svg
          width={width}
          height={height}
          onMouseMove={onSvgMouseMove}
          onMouseUp={onSvgMouseUp}
          onClick={() => conectando && setConectando(null)}
          ref={svgRef}
        >
          <defs>
            <pattern
              id="grid"
              width="30"
              height="30"
              patternUnits="userSpaceOnUse"
            >
              <circle cx="1" cy="1" r="0.8" fill="rgba(255,255,255,.06)" />
            </pattern>
          </defs>
          <rect width="100%" height="100%" fill="url(#grid)" />

          {nodos.map((n) => {
            if (!n.siguiente) return null;
            const destino = nodos.find((x) => x.id === n.siguiente);
            if (!destino) return null;
            const p1 = salida(n),
              p2 = entrada(destino);
            const mx = (p1.x + p2.x) / 2;
            const d = `M${p1.x},${p1.y} C${mx},${p1.y} ${mx},${p2.y} ${p2.x},${p2.y}`;
            const color = areaColor(n.area);
            return (
              <g
                key={`conn_${n.id}`}
                style={{ cursor: "pointer" }}
                onClick={() => desconectar(n.id)}
              >
                <path
                  d={d}
                  fill="none"
                  stroke={color}
                  strokeWidth={2}
                  markerEnd={`url(#arrow_${n.id})`}
                  opacity={0.8}
                />
                <defs>
                  <marker
                    id={`arrow_${n.id}`}
                    markerWidth="8"
                    markerHeight="8"
                    refX="6"
                    refY="3"
                    orient="auto"
                  >
                    <path d="M0,0 L0,6 L8,3 Z" fill={color} />
                  </marker>
                </defs>
                <path d={d} fill="none" stroke="transparent" strokeWidth={12} />
                <circle
                  cx={mx}
                  cy={(p1.y + p2.y) / 2}
                  r={8}
                  fill={color}
                  opacity={0.8}
                />
                <text
                  x={mx}
                  y={(p1.y + p2.y) / 2 + 4}
                  textAnchor="middle"
                  fill="#fff"
                  fontSize={10}
                  fontFamily="monospace"
                >
                  ×
                </text>
              </g>
            );
          })}

          {nodos.map((n) => {
            const color = areaColor(n.area);
            const isHover = hover === n.id;
            const isConnecting = conectando === n.id;
            return (
              <g
                key={n.id}
                onMouseEnter={() => setHover(n.id)}
                onMouseLeave={() => setHover(null)}
              >
                {isHover && (
                  <rect
                    x={n.x - 4}
                    y={n.y - 4}
                    width={NODE_W + 8}
                    height={NODE_H + 8}
                    rx={14}
                    fill={color}
                    opacity={0.1}
                  />
                )}
                <rect
                  x={n.x}
                  y={n.y}
                  width={NODE_W}
                  height={NODE_H}
                  rx={10}
                  fill="rgba(7,15,40,.95)"
                  stroke={
                    isConnecting ? color : isHover ? color + "80" : "#1e3a5f"
                  }
                  strokeWidth={isConnecting ? 2.5 : 1.5}
                  style={{ cursor: "grab" }}
                  onMouseDown={(e) => onNodeMouseDown(e, n.id)}
                  onClick={() => conectando && completarConexion(n.id)}
                />
                <rect
                  x={n.x}
                  y={n.y}
                  width={4}
                  height={NODE_H}
                  rx={2}
                  fill={color}
                />
                <text
                  x={n.x + 14}
                  y={n.y + 24}
                  fontSize={13}
                  fontWeight={700}
                  fill="#e2e8f0"
                  fontFamily="sans-serif"
                >
                  {n.nombre.length > 18
                    ? n.nombre.slice(0, 18) + "…"
                    : n.nombre}
                </text>
                <text
                  x={n.x + 14}
                  y={n.y + 41}
                  fontSize={10}
                  fill={color}
                  fontFamily="sans-serif"
                >
                  {n.area}
                </text>
                <text
                  x={n.x + 14}
                  y={n.y + 57}
                  fontSize={9}
                  fill="#475569"
                  fontFamily="monospace"
                >
                  {n.modelo.slice(0, 22)}
                </text>
                <g
                  onClick={(e) => iniciarConexion(e, n.id)}
                  style={{ cursor: "pointer" }}
                >
                  <circle
                    cx={n.x + NODE_W}
                    cy={n.y + NODE_H / 2}
                    r={10}
                    fill={isConnecting ? color : "#1e3a5f"}
                    stroke={color}
                    strokeWidth={1.5}
                  />
                  <text
                    x={n.x + NODE_W}
                    y={n.y + NODE_H / 2 + 4}
                    textAnchor="middle"
                    fontSize={12}
                    fill={isConnecting ? "#0a0e1a" : color}
                    fontFamily="monospace"
                    fontWeight={700}
                  >
                    →
                  </text>
                </g>
                <circle
                  cx={n.x}
                  cy={n.y + NODE_H / 2}
                  r={5}
                  fill={conectando ? "#00ff9d" : "#1e3a5f"}
                  stroke={conectando ? "#00ff9d" : "#334155"}
                  strokeWidth={1.5}
                  style={{ cursor: conectando ? "pointer" : "default" }}
                  onClick={() => conectando && completarConexion(n.id)}
                />
              </g>
            );
          })}
        </svg>
      </div>

      <div
        style={{
          fontSize: ".72rem",
          color: "#475569",
          display: "flex",
          gap: "1.5rem",
          flexWrap: "wrap",
        }}
      >
        <span>🖱 Arrastra para mover</span>
        <span>→ para conectar agentes</span>
        <span>
          Clic en <strong style={{ color: "#ff2d55" }}>×</strong> en la flecha
          para desconectar
        </span>
        <span>
          El flujo se ejecuta en cadena al usar{" "}
          <strong>&quot;realizar_tarea_encadenada&quot;</strong>
        </span>
      </div>
      <style>{"@keyframes spin{to{transform:rotate(360deg)}}"}</style>
    </div>
  );
}
