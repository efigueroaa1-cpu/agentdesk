/**
 * ErrorPanel.jsx — Pestaña "Feed de Errores" dentro de Pipeline: eventos de
 * telemetría en vivo (WebSocket), filtrables por agente, con un resumen de
 * salud por agente basado en los últimos eventos.
 *
 * Reconstruido desde el bundle de producción (react_dist/assets/index-CRDO1T5r.js,
 * función `v5`): el fuente original de este componente no estaba versionado.
 */
import { useState, useEffect } from "react";
import {
  Wifi,
  WifiOff,
  Trash2,
  Activity,
  CheckCircle2,
  AlertTriangle,
  ChevronDown,
  ChevronUp,
  Zap,
} from "../../icons.js";
import { AgentService } from "../../services/agent.service";

const GUARD_INFO = {
  "Recursion Guard": { color: "#f59e0b", icon: "🔄" },
  "Tone Guard": { color: "#ef4444", icon: "🗣️" },
  "Grounding Guard": { color: "#8b5cf6", icon: "🎯" },
  "Logic Integrity Filter": { color: "#06b6d4", icon: "⚖️" },
};
function guardInfo(filtro) {
  return GUARD_INFO[filtro] ?? { color: "#64748b", icon: "⚡" };
}

function saludDe(eventos) {
  const nFallos = eventos.slice(-10).filter((e) => e.status !== "ok").length;
  return nFallos === 0 ? "ok" : nFallos <= 2 ? "warning" : "error";
}
const SALUD_COLOR = { ok: "#00ff9d", warning: "#f59e0b", error: "#ff2d55" };
const SALUD_LABEL = { ok: "OK", warning: "Alerta", error: "Error" };

function Contador({ color, label, count }) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 7,
        padding: "6px 12px",
        borderRadius: 8,
        background: `${color}12`,
        border: `1px solid ${color}30`,
      }}
    >
      <div
        style={{ width: 8, height: 8, borderRadius: "50%", background: color }}
      />
      <span style={{ fontSize: ".72rem", fontWeight: 700, color }}>
        {label}
      </span>
      <span style={{ fontSize: ".9rem", fontWeight: 800, color }}>{count}</span>
    </div>
  );
}

function BarraMini({ value, max, color }) {
  const pct = Math.min((value / max) * 100, 100);
  return (
    <div
      style={{
        flex: 1,
        height: 4,
        background: "var(--t-border)",
        borderRadius: 2,
      }}
    >
      <div
        style={{
          width: `${pct}%`,
          height: "100%",
          background: color,
          borderRadius: 2,
        }}
      />
    </div>
  );
}

function EventoCard({ event, onDismiss }) {
  const [expandido, setExpandido] = useState(false);
  const info = guardInfo(event.filtro);
  const hora = event.timestamp
    ? new Date(event.timestamp * 1000).toLocaleTimeString()
    : "";
  const abortado = event.tipo === "pipeline_abortado";
  return (
    <div
      style={{
        border: `1px solid ${info.color}40`,
        borderLeft: `3px solid ${info.color}`,
        borderRadius: "0 8px 8px 0",
        background: `${info.color}08`,
        padding: "10px 12px",
        display: "flex",
        flexDirection: "column",
        gap: 6,
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "flex-start",
          justifyContent: "space-between",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
          <span style={{ fontSize: 14 }}>{info.icon}</span>
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <span
                style={{
                  fontWeight: 700,
                  fontSize: ".8rem",
                  color: info.color,
                }}
              >
                {abortado ? "ABORTADO" : event.status?.toUpperCase()}
              </span>
              <span style={{ fontSize: ".7rem", color: "var(--t-text-muted)" }}>
                {event.filtro || "Pipeline"}
              </span>
            </div>
            <div
              style={{
                fontSize: ".72rem",
                color: "var(--t-text-muted)",
                marginTop: 1,
              }}
            >
              Agente:{" "}
              <strong style={{ color: "var(--t-text)" }}>{event.agente}</strong>
              <span style={{ marginLeft: 8, opacity: 0.6 }}>{hora}</span>
            </div>
          </div>
        </div>
        <div style={{ display: "flex", gap: 4 }}>
          {event.motivo && (
            <button onClick={() => setExpandido((v) => !v)} style={btnIcon}>
              {expandido ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
            </button>
          )}
          <button onClick={onDismiss} style={btnIcon}>
            <Trash2 size={12} />
          </button>
        </div>
      </div>
      {event.duracion_s != null && (
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <Zap size={11} color="var(--t-text-muted)" />
          <span style={{ fontSize: ".68rem", color: "var(--t-text-muted)" }}>
            {event.duracion_s.toFixed(4)}s
          </span>
          <BarraMini value={event.duracion_s} max={5} color={info.color} />
        </div>
      )}
      {expandido && event.motivo && (
        <div
          style={{
            marginTop: 2,
            padding: "6px 8px",
            borderRadius: 6,
            background: "var(--t-bg)",
            fontSize: ".7rem",
            color: "var(--t-text-muted)",
            fontFamily: "monospace",
            lineHeight: 1.5,
            wordBreak: "break-word",
          }}
        >
          {event.motivo}
        </div>
      )}
    </div>
  );
}

function SaludAgente({ agente, events }) {
  const salud = saludDe(events);
  const color = SALUD_COLOR[salud];
  const ultimoFallo = events.filter((e) => e.status !== "ok").pop();
  const porFiltro = {};
  events.forEach((e) => {
    if (e.filtro) {
      porFiltro[e.filtro] = porFiltro[e.filtro] || [];
      if (e.duracion_s != null) porFiltro[e.filtro].push(e.duracion_s);
    }
  });
  return (
    <div
      style={{
        padding: "10px 12px",
        borderRadius: 10,
        border: `1px solid ${color}30`,
        background: `${color}08`,
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          marginBottom: 6,
        }}
      >
        <span
          style={{ fontWeight: 700, fontSize: ".8rem", color: "var(--t-text)" }}
        >
          {agente}
        </span>
        <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
          <div
            style={{
              width: 7,
              height: 7,
              borderRadius: "50%",
              background: color,
              boxShadow: salud !== "ok" ? `0 0 6px ${color}` : "none",
            }}
          />
          <span style={{ fontSize: ".68rem", color, fontWeight: 600 }}>
            {SALUD_LABEL[salud]}
          </span>
        </div>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
        {Object.entries(porFiltro).map(([nombre, arr]) => {
          const prom = arr.length
            ? arr.reduce((a, b) => a + b, 0) / arr.length
            : 0;
          const info = guardInfo(nombre);
          return (
            <div
              key={nombre}
              style={{ display: "flex", alignItems: "center", gap: 6 }}
            >
              <span
                style={{
                  fontSize: ".6rem",
                  width: 110,
                  color: "var(--t-text-muted)",
                  flexShrink: 0,
                }}
              >
                {nombre.replace(" Guard", "").replace(" Filter", "")}
              </span>
              <BarraMini value={prom} max={1} color={info.color} />
              <span
                style={{
                  fontSize: ".6rem",
                  color: "var(--t-text-muted)",
                  width: 38,
                  textAlign: "right",
                }}
              >
                {prom.toFixed(3)}s
              </span>
            </div>
          );
        })}
      </div>
      {ultimoFallo && (
        <div
          style={{
            marginTop: 6,
            fontSize: ".66rem",
            color: "#ff2d55",
            display: "flex",
            alignItems: "center",
            gap: 4,
          }}
        >
          <AlertTriangle size={10} /> Último fallo:{" "}
          {ultimoFallo.filtro || "Pipeline"}
        </div>
      )}
    </div>
  );
}

export default function ErrorPanel() {
  const [eventos, setEventos] = useState([]);
  const [filtro, setFiltro] = useState("Todos");
  const [conectado, setConectado] = useState(false);
  const [nombresAgentes, setNombresAgentes] = useState([]);

  useEffect(() => {
    AgentService.getAll()
      .then((d) => setNombresAgentes((d.agentes ?? []).map((a) => a.nombre)))
      .catch(() => {});
    return AgentService.onWsMessage((msg) => {
      if (msg.tipo === "telemetria" || msg.tipo === "pipeline_abortado") {
        setConectado(true);
        setEventos((e) =>
          [...e, { ...msg, id: Date.now() + Math.random() }].slice(-200),
        );
      }
      if (msg.tipo === "conexion") setConectado(true);
    });
  }, []);

  const porAgente = eventos.reduce((acc, e) => {
    if (e.agente) {
      acc[e.agente] = acc[e.agente] || [];
      acc[e.agente].push(e);
    }
    return acc;
  }, {});
  const errores = eventos.filter(
    (e) =>
      e.status === "error" ||
      e.status === "timeout" ||
      e.tipo === "pipeline_abortado",
  );
  const agentesConEventos = [
    ...new Set(eventos.map((e) => e.agente).filter(Boolean)),
  ];
  const visibles =
    filtro === "Todos"
      ? [...eventos].reverse()
      : filtro === "Errores"
        ? [...errores].reverse()
        : [...eventos].reverse().filter((e) => e.agente === filtro);

  const ok = Object.values(porAgente).filter((e) => saludDe(e) === "ok").length;
  const warning = Object.values(porAgente).filter(
    (e) => saludDe(e) === "warning",
  ).length;
  const error = Object.values(porAgente).filter(
    (e) => saludDe(e) === "error",
  ).length;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "1.2rem" }}>
      <div style={{ display: "flex", gap: ".8rem", flexWrap: "wrap" }}>
        <Contador color="#00ff9d" label="OK" count={ok} />
        <Contador color="#f59e0b" label="Alerta" count={warning} />
        <Contador color="#ff2d55" label="Error" count={error} />
        <div
          style={{
            marginLeft: "auto",
            display: "flex",
            alignItems: "center",
            gap: 6,
            fontSize: ".72rem",
            color: conectado ? "#00ff9d" : "#ff2d55",
          }}
        >
          {conectado ? <Wifi size={13} /> : <WifiOff size={13} />}
          {conectado ? "WebSocket conectado" : "Sin conexión WS"}
        </div>
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 340px",
          gap: "1rem",
          minHeight: 0,
        }}
      >
        <div>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              marginBottom: ".8rem",
              flexWrap: "wrap",
              gap: ".4rem",
            }}
          >
            <div style={{ display: "flex", gap: ".4rem", flexWrap: "wrap" }}>
              {[
                "Todos",
                "Errores",
                ...(agentesConEventos.length
                  ? agentesConEventos
                  : nombresAgentes),
              ].map((f) => (
                <button
                  key={f}
                  onClick={() => setFiltro(f)}
                  style={{
                    padding: "3px 10px",
                    borderRadius: 20,
                    fontSize: ".7rem",
                    fontWeight: 600,
                    cursor: "pointer",
                    fontFamily: "inherit",
                    border:
                      filtro === f
                        ? "1px solid var(--t-accent)"
                        : "1px solid var(--t-border)",
                    background:
                      filtro === f ? "rgba(0,212,255,.1)" : "transparent",
                    color:
                      filtro === f ? "var(--t-accent)" : "var(--t-text-muted)",
                  }}
                >
                  {f}
                </button>
              ))}
            </div>
            <div
              style={{ display: "flex", gap: ".4rem", alignItems: "center" }}
            >
              <span style={{ fontSize: ".7rem", color: "var(--t-text-muted)" }}>
                {visibles.length} evento{visibles.length !== 1 ? "s" : ""}
              </span>
              <button
                onClick={() => setEventos([])}
                style={btnIconBig}
                title="Limpiar feed"
              >
                <Trash2 size={13} />
              </button>
            </div>
          </div>

          <div
            style={{
              display: "flex",
              flexDirection: "column",
              gap: ".5rem",
              maxHeight: "calc(100vh - 320px)",
              overflowY: "auto",
            }}
          >
            {visibles.length === 0 ? (
              <div
                style={{
                  padding: "3rem",
                  textAlign: "center",
                  color: "var(--t-text-muted)",
                  fontSize: ".84rem",
                  border: "1px dashed var(--t-border)",
                  borderRadius: 10,
                }}
              >
                <Activity size={28} style={{ marginBottom: 8, opacity: 0.4 }} />
                <div>Sin eventos todavía.</div>
                <div style={{ fontSize: ".72rem", marginTop: 4 }}>
                  Ejecuta un agente para ver el feed en tiempo real.
                </div>
              </div>
            ) : (
              visibles.map((evt) =>
                evt.status !== "ok" || filtro === "Todos" ? (
                  <EventoCard
                    key={evt.id}
                    event={evt}
                    onDismiss={() =>
                      setEventos((list) => list.filter((e) => e.id !== evt.id))
                    }
                  />
                ) : (
                  <div
                    key={evt.id}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 8,
                      padding: "5px 10px",
                      borderRadius: 6,
                      background: "var(--t-bg-card)",
                      border: "1px solid var(--t-border)",
                      fontSize: ".7rem",
                      color: "var(--t-text-muted)",
                    }}
                  >
                    <CheckCircle2 size={11} color="#00ff9d" />
                    <span style={{ color: "#00ff9d", fontWeight: 600 }}>
                      OK
                    </span>
                    <span>{evt.filtro}</span>
                    <span style={{ opacity: 0.6 }}>·</span>
                    <span>{evt.agente}</span>
                    <span
                      style={{ marginLeft: "auto", fontFamily: "monospace" }}
                    >
                      {evt.duracion_s?.toFixed(4)}s
                    </span>
                  </div>
                ),
              )
            )}
          </div>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: ".8rem" }}>
          <div
            style={{
              fontSize: ".68rem",
              fontWeight: 700,
              letterSpacing: ".07em",
              textTransform: "uppercase",
              color: "var(--t-text-muted)",
              paddingBottom: ".3rem",
              borderBottom: "1px solid var(--t-border)",
            }}
          >
            Salud por Agente
          </div>
          {Object.keys(porAgente).length === 0 ? (
            <div
              style={{
                fontSize: ".75rem",
                color: "var(--t-text-muted)",
                textAlign: "center",
                padding: "1rem",
              }}
            >
              Sin datos de ejecución aún.
            </div>
          ) : (
            Object.entries(porAgente).map(([agente, eventos]) => (
              <SaludAgente key={agente} agente={agente} events={eventos} />
            ))
          )}
        </div>
      </div>
    </div>
  );
}

const btnIcon = {
  background: "none",
  border: "1px solid var(--t-border)",
  borderRadius: 5,
  cursor: "pointer",
  color: "var(--t-text-muted)",
  padding: "3px 5px",
  display: "flex",
  alignItems: "center",
};
const btnIconBig = {
  background: "var(--t-bg-card)",
  border: "1px solid var(--t-border)",
  borderRadius: 7,
  cursor: "pointer",
  color: "var(--t-text-muted)",
  padding: "5px 8px",
  display: "flex",
  alignItems: "center",
};
