/**
 * AgentStatusSection.jsx — Sección de estado de agentes en el Dashboard.
 *
 * Muestra una tarjeta por agente con su área, un botón "Ejecutar" (dispara
 * `onRunAgent`) y un indicador de actividad alimentado por el WebSocket de
 * telemetría. También lleva contadores de tareas OK / abortadas / en curso.
 *
 * Reconstruido desde el bundle de producción (react_dist/assets/index-CRDO1T5r.js,
 * función `Rb`): el fuente original de este componente no estaba versionado.
 */
import { useState, useEffect } from "react";
import {
  Activity,
  CheckCircle2,
  XCircle,
  RefreshCw,
  Bot,
  Play,
} from "../../icons.js";
import { AgentService } from "../../services/agent.service";

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
  const key = area
    ? area.charAt(0).toUpperCase() + area.slice(1).toLowerCase()
    : "General";
  return AREA_COLOR[key] ?? "#64748b";
}

function Contador({ icon, label, value, color }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
      {icon}
      <span style={{ color, fontWeight: 700 }}>{value}</span>
      <span style={{ color: "var(--t-text-muted)" }}>{label}</span>
    </div>
  );
}

export default function AgentStatusSection({ onRunAgent }) {
  const [agentes, setAgentes] = useState([]);
  const [stats, setStats] = useState({
    ok: 0,
    abortados: 0,
    running: new Set(),
  });
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    AgentService.getAll()
      .then((d) => setAgentes(d.agentes ?? []))
      .catch(() => {})
      .finally(() => setLoading(false));
    return AgentService.onWsMessage((msg) => {
      if (msg.tipo === "agente_creado" || msg.tipo === "agente_eliminado") {
        AgentService.getAll()
          .then((d) => setAgentes(d.agentes ?? []))
          .catch(() => {});
      }
      if (msg.tipo === "agente_ejecutando") {
        setStats((s) => ({
          ...s,
          running: new Set([...s.running, msg.agente_id]),
        }));
      }
      if (msg.tipo === "tarea_completada") {
        setStats((s) => {
          const r = new Set(s.running);
          r.delete(msg.agente_id);
          return { ...s, ok: s.ok + 1, running: r };
        });
      }
      if (msg.tipo === "tarea_abortada") {
        setStats((s) => {
          const r = new Set(s.running);
          r.delete(msg.agente_id);
          return { ...s, abortados: s.abortados + 1, running: r };
        });
      }
      if (msg.tipo === "pipeline_abortado") {
        setStats((s) => ({ ...s, abortados: s.abortados + 1 }));
      }
    });
  }, []);

  return (
    <div
      style={{
        borderRadius: 14,
        border: "1px solid var(--t-border)",
        background: "var(--t-bg-card)",
        overflow: "hidden",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "12px 16px",
          borderBottom: "1px solid var(--t-border)",
          background: "var(--t-bg)",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <Activity size={15} color="var(--t-accent)" />
          <span
            style={{
              fontWeight: 700,
              fontSize: ".82rem",
              color: "var(--t-text)",
            }}
          >
            Estado de Agentes
          </span>
          <span
            style={{
              padding: "1px 7px",
              borderRadius: 20,
              fontSize: ".65rem",
              background: "rgba(0,212,255,.1)",
              color: "var(--t-accent)",
              fontWeight: 600,
            }}
          >
            {agentes.length} activos
          </span>
        </div>
        <div style={{ display: "flex", gap: "1rem", fontSize: ".72rem" }}>
          <Contador
            icon={<CheckCircle2 size={12} color="#00ff9d" />}
            label="OK"
            value={stats.ok}
            color="#00ff9d"
          />
          <Contador
            icon={<XCircle size={12} color="#ff2d55" />}
            label="Abortados"
            value={stats.abortados}
            color="#ff2d55"
          />
          <Contador
            icon={<RefreshCw size={12} color="#f59e0b" />}
            label="Corriendo"
            value={stats.running.size}
            color="#f59e0b"
          />
        </div>
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))",
          gap: ".8rem",
          padding: "1rem",
        }}
      >
        {loading ? (
          <div
            style={{
              gridColumn: "1/-1",
              textAlign: "center",
              padding: "1.5rem",
              color: "var(--t-text-muted)",
              fontSize: ".8rem",
            }}
          >
            <RefreshCw
              size={14}
              style={{ animation: "spin .8s linear infinite", marginRight: 6 }}
            />
            Cargando agentes...
            <style>{"@keyframes spin{to{transform:rotate(360deg)}}"}</style>
          </div>
        ) : agentes.length === 0 ? (
          <div
            style={{
              gridColumn: "1/-1",
              textAlign: "center",
              padding: "1.5rem",
              color: "var(--t-text-muted)",
              fontSize: ".8rem",
            }}
          >
            Sin agentes. Ve a <strong>Agentes → Agregar</strong> para crear uno.
          </div>
        ) : (
          agentes.map((a) => {
            const color = areaColor(a.area);
            const activo = stats.running.has(a.id);
            return (
              <div
                key={a.id}
                style={{
                  padding: "12px 14px",
                  borderRadius: 10,
                  border: `1px solid ${activo ? color : "var(--t-border)"}`,
                  background: activo ? `${color}10` : "var(--t-bg)",
                  transition: "all .2s",
                  display: "flex",
                  flexDirection: "column",
                  gap: 8,
                }}
              >
                <div
                  style={{
                    display: "flex",
                    alignItems: "flex-start",
                    justifyContent: "space-between",
                  }}
                >
                  <div
                    style={{ display: "flex", alignItems: "center", gap: 8 }}
                  >
                    <div
                      style={{
                        width: 30,
                        height: 30,
                        borderRadius: 7,
                        background: `${color}20`,
                        border: `1px solid ${color}40`,
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                      }}
                    >
                      <Bot size={13} color={color} />
                    </div>
                    <div>
                      <div
                        style={{
                          fontWeight: 700,
                          fontSize: ".78rem",
                          color: "var(--t-text)",
                          lineHeight: 1.2,
                        }}
                      >
                        {a.nombre}
                      </div>
                      <div
                        style={{
                          fontSize: ".63rem",
                          color: "var(--t-text-muted)",
                        }}
                      >
                        {(a.modelo || "")
                          .replace("models/", "")
                          .replace("gemini-", "g-")}
                      </div>
                    </div>
                  </div>
                  <div
                    style={{
                      width: 7,
                      height: 7,
                      borderRadius: "50%",
                      background: activo ? "#f59e0b" : "#00ff9d",
                      boxShadow: activo ? "0 0 6px #f59e0b" : "none",
                      marginTop: 4,
                    }}
                  />
                </div>
                <div
                  style={{
                    display: "inline-block",
                    padding: "2px 8px",
                    borderRadius: 20,
                    background: `${color}18`,
                    color,
                    fontSize: ".65rem",
                    fontWeight: 600,
                    border: `1px solid ${color}30`,
                    alignSelf: "flex-start",
                  }}
                >
                  {a.area || "General"}
                </div>
                {onRunAgent && (
                  <button
                    onClick={() => onRunAgent(a.id, a.nombre)}
                    disabled={activo}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      gap: 5,
                      padding: "5px 0",
                      border: "none",
                      borderRadius: 7,
                      cursor: activo ? "default" : "pointer",
                      background: activo ? `${color}20` : `${color}25`,
                      color: activo ? `${color}80` : color,
                      fontSize: ".7rem",
                      fontWeight: 600,
                      fontFamily: "inherit",
                    }}
                  >
                    {activo ? (
                      <>
                        <RefreshCw
                          size={11}
                          style={{ animation: "spin .8s linear infinite" }}
                        />{" "}
                        Ejecutando...
                      </>
                    ) : (
                      <>
                        <Play size={11} /> Ejecutar
                      </>
                    )}
                  </button>
                )}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
