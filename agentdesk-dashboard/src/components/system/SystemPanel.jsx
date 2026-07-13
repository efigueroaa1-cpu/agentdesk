/**
 * SystemPanel.jsx — Pestaña "Control del Sistema": estado del backend
 * (`GET /health`), ejecución masiva de agentes (`POST /agentes/ejecutar-todos`),
 * recarga en caliente de la configuración (`POST /reload`) y lista de
 * agentes activos en el Orquestador.
 *
 * Reconstruido desde el bundle de producción (react_dist/assets/index-CRDO1T5r.js,
 * función `Hw`): el fuente original de este componente no estaba versionado.
 * El Kill Switch remoto (`/kill-switch`) que aparecía aquí en el bundle viejo
 * ya está implementado — con los endpoints reales y protegido por rol admin —
 * en `settings/SecurityPanel.jsx`, así que no se duplica en este panel.
 */
import { useState, useEffect } from "react";
import { RefreshCw, CheckCircle2, XCircle, Play, Server } from "../../icons.js";
import { API_BASE, AgentService } from "../../services/agent.service";
import { addNotification } from "../ui/NotificationSystem";

function Card({ title, icon, children }) {
  return (
    <div
      style={{
        padding: "1.1rem 1.3rem",
        borderRadius: 12,
        border: "1px solid var(--t-border)",
        background: "var(--t-bg-card)",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 7,
          marginBottom: ".8rem",
          fontSize: ".72rem",
          fontWeight: 700,
          textTransform: "uppercase",
          letterSpacing: ".06em",
          color: "var(--t-text-muted)",
        }}
      >
        <span>{icon}</span>
        {title}
      </div>
      {children}
    </div>
  );
}
function Stat({ label, value, color }) {
  return (
    <div
      style={{
        padding: "10px 14px",
        borderRadius: 8,
        border: `1px solid ${color}25`,
        background: `${color}08`,
      }}
    >
      <div
        style={{
          fontSize: ".66rem",
          color: "var(--t-text-muted)",
          textTransform: "uppercase",
          letterSpacing: ".05em",
          marginBottom: 4,
        }}
      >
        {label}
      </div>
      <div style={{ fontSize: "1.2rem", fontWeight: 800, color }}>{value}</div>
    </div>
  );
}
const btnGhost = {
  cursor: "pointer",
  fontFamily: "inherit",
  borderRadius: 8,
  padding: "6px 12px",
  background: "transparent",
};

export default function SystemPanel() {
  const [health, setHealth] = useState(null);
  const [ejecutando, setEjecutando] = useState(false);
  const [resultados, setResultados] = useState(null);

  const cargarHealth = () =>
    AgentService.health()
      .then(setHealth)
      .catch(() => {});
  useEffect(() => {
    cargarHealth();
  }, []);

  async function ejecutarTodos() {
    setEjecutando(true);
    setResultados(null);
    try {
      const r = await fetch(`${API_BASE}/agentes/ejecutar-todos`, {
        method: "POST",
      }).then((res) => res.json());
      setResultados(r.resultados ?? {});
      const ok = Object.values(r.resultados ?? {}).filter((x) => x.ok).length;
      const total = Object.keys(r.resultados ?? {}).length;
      addNotification({
        message: `${ok}/${total} agentes completados`,
        type: ok === total ? "success" : "info",
      });
    } catch (e) {
      addNotification({
        message: "Error al ejecutar agentes: " + (e?.message ?? e),
        type: "error",
      });
    } finally {
      setEjecutando(false);
    }
  }

  async function recargarConfig() {
    try {
      await fetch(`${API_BASE}/reload`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      addNotification({ message: "Configuración recargada", type: "success" });
    } catch {
      addNotification({ message: "Error al recargar", type: "error" });
    }
  }

  const agentesActivos = health?.agentes ? Object.entries(health.agentes) : [];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "1.2rem" }}>
      <Card title="Estado del Sistema" icon="🖥">
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill,minmax(200px,1fr))",
            gap: ".7rem",
          }}
        >
          <Stat
            label="Backend"
            value={health ? "Activo" : "Sin datos"}
            color={health ? "#00ff9d" : "#ff2d55"}
          />
          <Stat
            label="Agentes registrados"
            value={agentesActivos.length}
            color="var(--t-accent)"
          />
          <Stat
            label="Clientes WebSocket"
            value={health?.clientes_ws ?? 0}
            color="#f59e0b"
          />
        </div>
        <div style={{ display: "flex", gap: ".5rem", marginTop: ".8rem" }}>
          <button
            onClick={cargarHealth}
            style={{
              ...btnGhost,
              border: "1px solid var(--t-border)",
              color: "var(--t-text-muted)",
              fontSize: ".75rem",
              display: "flex",
              alignItems: "center",
              gap: 5,
            }}
          >
            <RefreshCw size={13} /> Actualizar estado
          </button>
          <button
            onClick={recargarConfig}
            style={{
              ...btnGhost,
              border: "1px solid var(--t-border)",
              color: "var(--t-text-muted)",
              fontSize: ".75rem",
            }}
          >
            ↺ Recargar config del orquestador
          </button>
        </div>
      </Card>

      <Card title="Ejecutar Todos los Agentes" icon="⚡">
        <p
          style={{
            fontSize: ".78rem",
            color: "var(--t-text-muted)",
            margin: "0 0 .8rem",
          }}
        >
          Ejecuta <strong>realizar_tarea()</strong> en todos los agentes
          simultáneamente. Los resultados pasan por el pipeline completo
          (RecursionGuard → ToneGuard → GroundingGuard → LogicIntegrity).
        </p>
        <button
          onClick={ejecutarTodos}
          disabled={ejecutando}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            padding: "10px 20px",
            border: "none",
            borderRadius: 10,
            cursor: ejecutando ? "default" : "pointer",
            background: ejecutando
              ? "#1e3a5f"
              : "linear-gradient(90deg,var(--t-accent),var(--t-accent2,var(--t-accent)))",
            color: "#fff",
            fontWeight: 700,
            fontSize: ".85rem",
            fontFamily: "inherit",
            opacity: ejecutando ? 0.7 : 1,
          }}
        >
          {ejecutando ? (
            <>
              <RefreshCw
                size={15}
                style={{ animation: "spin .8s linear infinite" }}
              />{" "}
              Ejecutando...
            </>
          ) : (
            <>
              <Play size={15} /> Ejecutar Todos los Agentes
            </>
          )}
          <style>{"@keyframes spin{to{transform:rotate(360deg)}}"}</style>
        </button>

        {resultados && (
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              gap: ".5rem",
              marginTop: ".8rem",
            }}
          >
            {Object.entries(resultados).map(([id, r]) => (
              <div
                key={id}
                style={{
                  display: "flex",
                  alignItems: "flex-start",
                  gap: 10,
                  padding: "8px 12px",
                  borderRadius: 8,
                  background: r.ok
                    ? "rgba(0,255,157,.06)"
                    : "rgba(255,45,85,.06)",
                  border: `1px solid ${r.ok ? "#00ff9d30" : "#ff2d5530"}`,
                }}
              >
                {r.ok ? (
                  <CheckCircle2
                    size={15}
                    color="#00ff9d"
                    style={{ flexShrink: 0, marginTop: 1 }}
                  />
                ) : (
                  <XCircle
                    size={15}
                    color="#ff2d55"
                    style={{ flexShrink: 0, marginTop: 1 }}
                  />
                )}
                <div>
                  <div
                    style={{
                      fontWeight: 600,
                      fontSize: ".8rem",
                      color: "var(--t-text)",
                    }}
                  >
                    {id}
                  </div>
                  {r.resumen && (
                    <div
                      style={{
                        fontSize: ".72rem",
                        color: "var(--t-text-muted)",
                        marginTop: 2,
                      }}
                    >
                      {r.resumen}
                    </div>
                  )}
                  {r.error && (
                    <div
                      style={{
                        fontSize: ".72rem",
                        color: "#ff2d55",
                        marginTop: 2,
                      }}
                    >
                      {r.error}
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>

      {agentesActivos.length > 0 && (
        <Card title="Agentes Activos en el Orquestador" icon="🤖">
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fill,minmax(220px,1fr))",
              gap: ".5rem",
            }}
          >
            {agentesActivos.map(([id, a]) => (
              <div
                key={id}
                style={{
                  padding: "8px 12px",
                  borderRadius: 8,
                  border: "1px solid var(--t-border)",
                  background: "var(--t-bg)",
                }}
              >
                <div
                  style={{
                    fontWeight: 600,
                    fontSize: ".8rem",
                    color: "var(--t-text)",
                  }}
                >
                  {a.nombre}
                </div>
                <div
                  style={{
                    fontSize: ".68rem",
                    color: "var(--t-text-muted)",
                    marginTop: 2,
                  }}
                >
                  {(a.modelo || "").replace("models/", "")} · {a.area}
                </div>
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 5,
                    marginTop: 4,
                  }}
                >
                  <div
                    style={{
                      width: 7,
                      height: 7,
                      borderRadius: "50%",
                      background: "#00ff9d",
                    }}
                  />
                  <span style={{ fontSize: ".66rem", color: "#00ff9d" }}>
                    Disponible
                  </span>
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}

      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          fontSize: ".72rem",
          color: "var(--t-text-muted)",
        }}
      >
        <Server size={13} /> El Kill Switch remoto se administra desde{" "}
        <strong>Seguridad → Kill Switch</strong>.
      </div>
    </div>
  );
}
