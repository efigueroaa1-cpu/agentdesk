/**
 * PipelineControl.jsx — Pestaña "Control Pipeline": ejecuta un agente contra
 * una tarea, visualiza el flujo de guardrails (RecursionGuard → ToneGuard →
 * GroundingGuard → LogicIntegrity), el estado del Orquestador y permite
 * ajustar los umbrales de los guardrails (`GET/PUT /pipeline/config`).
 *
 * Reconstruido desde el bundle de producción (react_dist/assets/index-CRDO1T5r.js,
 * función `u5`): el fuente original de este componente no estaba versionado.
 */
import { useState, useEffect } from "react";
import {
  Play,
  RefreshCw,
  Bot,
  Cpu,
  Zap,
  Thermometer,
  MessageSquare,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  ArrowRight,
} from "../../icons.js";
import { AgentService, API_BASE } from "../../services/agent.service";

const GUARDRAILS = [
  {
    id: "recursion",
    nombre: "RecursionGuard",
    icono: "🔄",
    color: "#f59e0b",
    desc: "Detecta respuestas idénticas repetidas. Aborta en el 3er intento.",
    accion: "Aborta",
  },
  {
    id: "tone",
    nombre: "ToneGuard",
    icono: "🗣️",
    color: "#ef4444",
    desc: "Filtra lenguaje no profesional. Aborta si detecta coloquial.",
    accion: "Aborta",
  },
  {
    id: "grounding",
    nombre: "GroundingGuard",
    icono: "🎯",
    color: "#8b5cf6",
    desc: "Verifica que la evidencia cite datos del corpus original.",
    accion: "Aborta",
  },
  {
    id: "integrity",
    nombre: "LogicIntegrity",
    icono: "⚖️",
    color: "#06b6d4",
    desc: "Compara KPIs con datos crudos. Si excede el máximo, anota _integridad.",
    accion: "Anota",
  },
];
const FILTRO_A_STEP = {
  "Recursion Guard": "recursion",
  "Tone Guard": "tone",
  "Grounding Guard": "grounding",
  "Logic Integrity Filter": "integrity",
};
const TAREAS = [
  { id: "reporte_ventas", label: "Reporte de Ventas" },
  { id: "analisis_sistema", label: "Análisis de Sistema" },
  { id: "estado_flota", label: "Estado de Flota" },
  { id: "resumen_rrhh", label: "Resumen RRHH" },
  { id: "control_calidad", label: "Control de Calidad" },
];
const DEFAULT_CFG = {
  recursion_umbral: 3,
  grounding_min: 1000,
  logic_factor: 100,
  timeout_s: 5,
};

function SectionTitle({ icon, children }) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 7,
        marginBottom: ".7rem",
        fontSize: ".72rem",
        fontWeight: 700,
        textTransform: "uppercase",
        letterSpacing: ".06em",
        color: "var(--t-text-muted)",
      }}
    >
      {icon} {children}
    </div>
  );
}
function Dato({ icon, label, value }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
      <span style={{ color: "var(--t-text-muted)" }}>{icon}</span>
      <span style={{ color: "var(--t-text-muted)" }}>{label}:</span>
      <span style={{ fontWeight: 600, color: "var(--t-text)" }}>{value}</span>
    </div>
  );
}

function Step({ step, isLast, activeStep }) {
  const activo = activeStep === step.id;
  const hecho = activeStep === "done";
  return (
    <div style={{ display: "flex", alignItems: "center" }}>
      <div
        style={{
          padding: "10px 14px",
          borderRadius: 10,
          minWidth: 130,
          display: "flex",
          flexDirection: "column",
          gap: 4,
          transition: "all .2s",
          border: `1.5px solid ${activo ? step.color : hecho ? "#00ff9d" : "var(--t-border)"}`,
          background: activo
            ? `${step.color}15`
            : hecho
              ? "rgba(0,255,157,.08)"
              : "var(--t-bg-card)",
          boxShadow: activo ? `0 0 14px ${step.color}30` : "none",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
          <span style={{ fontSize: 16 }}>{step.icono}</span>
          <span
            style={{
              fontWeight: 700,
              fontSize: ".75rem",
              color: activo ? step.color : "var(--t-text)",
            }}
          >
            {step.nombre}
          </span>
        </div>
        <div
          style={{
            fontSize: ".66rem",
            color: "var(--t-text-muted)",
            lineHeight: 1.4,
          }}
        >
          {step.desc.slice(0, 60)}...
        </div>
        <div style={{ fontSize: ".62rem", fontWeight: 700 }}>
          <span
            style={{
              padding: "1px 6px",
              borderRadius: 10,
              background:
                step.accion === "Aborta"
                  ? "rgba(239,68,68,.15)"
                  : "rgba(6,182,212,.15)",
              color: step.accion === "Aborta" ? "#ef4444" : "#06b6d4",
            }}
          >
            {step.accion}
          </span>
        </div>
      </div>
      {!isLast && (
        <ArrowRight
          size={16}
          color="var(--t-text-muted)"
          style={{ flexShrink: 0, margin: "0 4px" }}
        />
      )}
    </div>
  );
}

function ResultadoTarea({ result, agente }) {
  if (!result) return null;
  const ok = result.ok !== false;
  return (
    <div
      style={{
        padding: "14px 16px",
        borderRadius: 10,
        border: `1px solid ${ok ? "#00ff9d40" : "#ff2d5540"}`,
        background: ok ? "rgba(0,255,157,.06)" : "rgba(255,45,85,.06)",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          marginBottom: 8,
        }}
      >
        {ok ? (
          <CheckCircle2 size={16} color="#00ff9d" />
        ) : (
          <XCircle size={16} color="#ff2d55" />
        )}
        <span
          style={{
            fontWeight: 700,
            fontSize: ".84rem",
            color: ok ? "#00ff9d" : "#ff2d55",
          }}
        >
          {ok ? "Tarea completada" : "Tarea abortada / error"}
        </span>
        <span
          style={{
            marginLeft: "auto",
            fontSize: ".7rem",
            color: "var(--t-text-muted)",
          }}
        >
          {agente}
        </span>
      </div>
      {ok && result.resultado ? (
        <>
          {result.resultado._integridad && (
            <div
              style={{
                padding: "6px 10px",
                borderRadius: 7,
                marginBottom: 8,
                background: "rgba(245,158,11,.1)",
                border: "1px solid rgba(245,158,11,.3)",
                fontSize: ".72rem",
                color: "#f59e0b",
                display: "flex",
                gap: 6,
              }}
            >
              <AlertTriangle size={13} /> {result.resultado._integridad}
            </div>
          )}
          <div
            style={{
              fontSize: ".8rem",
              color: "var(--t-text)",
              lineHeight: 1.6,
              marginBottom: 8,
            }}
          >
            {result.resultado.resumen}
          </div>
          {result.resultado.kpis && (
            <div style={{ display: "flex", gap: ".5rem", flexWrap: "wrap" }}>
              {Object.entries(result.resultado.kpis).map(([k, v]) => (
                <div
                  key={k}
                  style={{
                    padding: "4px 10px",
                    borderRadius: 7,
                    background: "var(--t-bg)",
                    border: "1px solid var(--t-border)",
                    fontSize: ".7rem",
                  }}
                >
                  <span style={{ color: "var(--t-text-muted)" }}>{k}: </span>
                  <span style={{ fontWeight: 700, color: "var(--t-accent)" }}>
                    {v}
                  </span>
                </div>
              ))}
            </div>
          )}
        </>
      ) : (
        <div style={{ fontSize: ".78rem", color: "var(--t-text-muted)" }}>
          {result.motivo ?? result.error ?? "Sin detalles."}
        </div>
      )}
    </div>
  );
}

function GuardrailsConfig() {
  const [cfg, setCfg] = useState({ ...DEFAULT_CFG });
  const [guardado, setGuardado] = useState(false);
  const [editando, setEditando] = useState(false);

  useEffect(() => {
    fetch(`${API_BASE}/pipeline/config`)
      .then((r) => r.json())
      .then((d) => {
        if (d.config) setCfg({ ...DEFAULT_CFG, ...d.config });
      })
      .catch(() => {});
  }, []);

  function guardar() {
    fetch(`${API_BASE}/pipeline/config`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(cfg),
    }).catch(() => {});
    setGuardado(true);
    setEditando(false);
    setTimeout(() => setGuardado(false), 2000);
  }

  const campos = [
    {
      key: "recursion_umbral",
      label: "RecursionGuard — Intentos idénticos para abortar",
      min: 2,
      max: 10,
      step: 1,
      unit: " intentos",
      desc: "Si la misma respuesta se repite N veces → aborta. Valor actual: ",
    },
    {
      key: "grounding_min",
      label: "GroundingGuard — Valor mínimo a verificar",
      min: 100,
      max: 10000,
      step: 100,
      unit: "",
      desc: "Números menores que este se ignoran. Actual: ",
    },
    {
      key: "logic_factor",
      label: "LogicIntegrity — Factor máximo KPI/datos crudos",
      min: 10,
      max: 1000,
      step: 10,
      unit: "×",
      desc: "Si un KPI excede N× el máximo del corpus → se anota _integridad. Actual: ",
    },
    {
      key: "timeout_s",
      label: "Timeout por filtro",
      min: 2,
      max: 30,
      step: 1,
      unit: "s",
      desc: "Tiempo máximo de ejecución de cada guardrail antes de abortar. Actual: ",
    },
  ];

  return (
    <div
      style={{
        padding: "1.1rem 1.4rem",
        borderRadius: 12,
        border: "1px solid var(--t-border)",
        background: "var(--t-bg-card)",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          marginBottom: ".8rem",
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 7,
            fontSize: ".72rem",
            fontWeight: 700,
            textTransform: "uppercase",
            letterSpacing: ".06em",
            color: "var(--t-text-muted)",
          }}
        >
          <Zap size={13} /> Configuración de Guardrails
        </div>
        <div style={{ display: "flex", gap: ".5rem" }}>
          {editando ? (
            <>
              <button
                onClick={guardar}
                style={{
                  padding: "4px 12px",
                  borderRadius: 8,
                  border: "none",
                  cursor: "pointer",
                  background:
                    "linear-gradient(90deg,var(--t-accent),var(--t-accent2,var(--t-accent)))",
                  color: "#fff",
                  fontSize: ".72rem",
                  fontWeight: 700,
                  fontFamily: "inherit",
                }}
              >
                {guardado ? "Guardado" : "Guardar"}
              </button>
              <button
                onClick={() => setEditando(false)}
                style={{
                  padding: "4px 10px",
                  borderRadius: 8,
                  border: "1px solid var(--t-border)",
                  background: "transparent",
                  color: "var(--t-text-muted)",
                  cursor: "pointer",
                  fontSize: ".72rem",
                  fontFamily: "inherit",
                }}
              >
                Cancelar
              </button>
            </>
          ) : (
            <button
              onClick={() => setEditando(true)}
              style={{
                padding: "4px 12px",
                borderRadius: 8,
                border: "1px solid var(--t-border)",
                background: "transparent",
                color: "var(--t-accent)",
                cursor: "pointer",
                fontSize: ".72rem",
                fontWeight: 600,
                fontFamily: "inherit",
              }}
            >
              Configurar
            </button>
          )}
        </div>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: ".9rem" }}>
        {campos.map((c) => (
          <div key={c.key}>
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                fontSize: ".72rem",
                marginBottom: 4,
              }}
            >
              <span style={{ color: "var(--t-text)", fontWeight: 600 }}>
                {c.label}
              </span>
              <span
                style={{
                  color: "var(--t-accent)",
                  fontWeight: 700,
                  fontFamily: "monospace",
                }}
              >
                {cfg[c.key]}
                {c.unit}
              </span>
            </div>
            <input
              type="range"
              min={c.min}
              max={c.max}
              step={c.step}
              value={cfg[c.key]}
              disabled={!editando}
              onChange={(e) =>
                setCfg((f) => ({ ...f, [c.key]: Number(e.target.value) }))
              }
              style={{
                width: "100%",
                accentColor: "var(--t-accent)",
                opacity: editando ? 1 : 0.5,
              }}
            />
            <div
              style={{
                fontSize: ".64rem",
                color: "var(--t-text-muted)",
                marginTop: 2,
              }}
            >
              {c.desc}
              <strong style={{ color: "var(--t-text)" }}>
                {cfg[c.key]}
                {c.unit}
              </strong>
              {!editando && (
                <span style={{ color: "#475569" }}>
                  {" "}
                  · Haz clic en Configurar para editar
                </span>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function PipelineControl() {
  const [agentes, setAgentes] = useState([]);
  const [agenteId, setAgenteId] = useState("");
  const [tarea, setTarea] = useState("reporte_ventas");
  const [ejecutando, setEjecutando] = useState(false);
  const [resultado, setResultado] = useState(null);
  const [activeStep, setActiveStep] = useState(null);
  const [telemetria, setTelemetria] = useState([]);
  const [health, setHealth] = useState(null);

  useEffect(() => {
    (async () => {
      try {
        const [lista, h] = await Promise.all([
          AgentService.getAll(),
          AgentService.health(),
        ]);
        const agentesLista = lista.agentes ?? [];
        setAgentes(agentesLista);
        if (agentesLista.length > 0 && !agenteId)
          setAgenteId(agentesLista[0].id);
        setHealth(h);
      } catch {
        /* sin conexión */
      }
    })();
    const unsub = AgentService.onWsMessage((msg) => {
      if (msg.tipo === "telemetria") {
        const step = FILTRO_A_STEP[msg.filtro];
        if (step) {
          setActiveStep(
            msg.status === "error" || msg.status === "timeout"
              ? `error_${step}`
              : step,
          );
        }
        setTelemetria((t) => [{ ...msg, id: Date.now() }, ...t].slice(0, 20));
      }
      if (msg.tipo === "tarea_completada" || msg.tipo === "tarea_abortada") {
        setActiveStep(msg.tipo === "tarea_completada" ? "done" : null);
        setEjecutando(false);
      }
    });
    return () => {
      unsub();
    };
  }, [agenteId]);

  async function ejecutar() {
    if (!agenteId) return;
    setEjecutando(true);
    setResultado(null);
    setActiveStep("recursion");
    setTelemetria([]);
    try {
      const r = await AgentService.ejecutar(agenteId, tarea);
      setResultado(r);
      setActiveStep(r.ok ? "done" : null);
    } catch (e) {
      setResultado({ ok: false, error: String(e) });
      setActiveStep(null);
    } finally {
      setEjecutando(false);
    }
  }

  const agenteActual = agentes.find((a) => a.id === agenteId);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "1.4rem" }}>
      <div
        style={{
          padding: "1.2rem 1.4rem",
          borderRadius: 12,
          border: "1px solid var(--t-border)",
          background: "var(--t-bg-card)",
        }}
      >
        <SectionTitle icon={<Play size={14} />}>Ejecutar Agente</SectionTitle>
        <div
          style={{
            display: "flex",
            gap: "1rem",
            flexWrap: "wrap",
            alignItems: "flex-end",
          }}
        >
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              gap: 5,
              flex: 1,
              minWidth: 200,
            }}
          >
            <label
              htmlFor="pipeline-select-agente"
              style={{
                fontSize: ".72rem",
                fontWeight: 600,
                color: "var(--t-text-muted)",
                textTransform: "uppercase",
                letterSpacing: ".05em",
              }}
            >
              Agente
            </label>
            <select
              id="pipeline-select-agente"
              value={agenteId}
              onChange={(e) => setAgenteId(e.target.value)}
              style={selectStyle}
            >
              {agentes.length === 0 ? (
                <option value="">— Sin agentes —</option>
              ) : (
                agentes.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.nombre} ({a.area || "General"})
                  </option>
                ))
              )}
            </select>
          </div>
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              gap: 5,
              flex: 1,
              minWidth: 180,
            }}
          >
            <label
              htmlFor="pipeline-select-tarea"
              style={{
                fontSize: ".72rem",
                fontWeight: 600,
                color: "var(--t-text-muted)",
                textTransform: "uppercase",
                letterSpacing: ".05em",
              }}
            >
              Tarea
            </label>
            <select
              id="pipeline-select-tarea"
              value={tarea}
              onChange={(e) => setTarea(e.target.value)}
              style={selectStyle}
            >
              {TAREAS.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.label}
                </option>
              ))}
            </select>
          </div>
          <button
            onClick={ejecutar}
            disabled={ejecutando || !agenteId}
            style={{
              ...btnEjecutar,
              opacity: ejecutando || !agenteId ? 0.5 : 1,
              cursor: ejecutando || !agenteId ? "default" : "pointer",
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
                <Play size={15} /> Ejecutar
              </>
            )}
            <style>{"@keyframes spin{to{transform:rotate(360deg)}}"}</style>
          </button>
        </div>

        {agenteActual && (
          <div
            style={{
              marginTop: ".8rem",
              padding: "8px 12px",
              borderRadius: 8,
              background: "var(--t-bg)",
              border: "1px solid var(--t-border)",
              display: "flex",
              gap: "1rem",
              flexWrap: "wrap",
              fontSize: ".73rem",
            }}
          >
            <Dato
              icon={<Bot size={11} />}
              label="Modelo"
              value={(agenteActual.modelo || "").replace("models/", "")}
            />
            <Dato
              icon={<Cpu size={11} />}
              label="Área"
              value={agenteActual.area || "General"}
            />
            <Dato
              icon={<Thermometer size={11} />}
              label="Temp."
              value={agenteActual.temperatura ?? "-"}
            />
            <Dato
              icon={<MessageSquare size={11} />}
              label="Prompt"
              value={agenteActual.prompt_base ? "Configurado" : "Vacío"}
            />
          </div>
        )}

        {resultado && (
          <div style={{ marginTop: "1rem" }}>
            <ResultadoTarea
              result={resultado}
              agente={agenteActual?.nombre ?? agenteId}
            />
          </div>
        )}
      </div>

      <div
        style={{
          padding: "1.2rem 1.4rem",
          borderRadius: 12,
          border: "1px solid var(--t-border)",
          background: "var(--t-bg-card)",
        }}
      >
        <SectionTitle icon={<Zap size={14} />}>
          Flujo del Pipeline — Guardrails
        </SectionTitle>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            flexWrap: "wrap",
            gap: ".3rem",
            padding: ".8rem 0",
          }}
        >
          <div
            style={{
              padding: "8px 12px",
              borderRadius: 8,
              background: "rgba(0,212,255,.1)",
              border: "1px solid rgba(0,212,255,.3)",
              fontSize: ".72rem",
              fontWeight: 700,
              color: "var(--t-accent)",
            }}
          >
            📥 Respuesta Gemini
          </div>
          <ArrowRight size={15} color="var(--t-text-muted)" />
          {GUARDRAILS.map((g, i) => (
            <Step
              key={g.id}
              step={g}
              isLast={i === GUARDRAILS.length - 1}
              activeStep={activeStep}
            />
          ))}
          <ArrowRight size={15} color="var(--t-text-muted)" />
          <div
            style={{
              padding: "8px 12px",
              borderRadius: 8,
              background:
                activeStep === "done" ? "rgba(0,255,157,.1)" : "var(--t-bg)",
              border:
                activeStep === "done"
                  ? "1px solid rgba(0,255,157,.4)"
                  : "1px solid var(--t-border)",
              fontSize: ".72rem",
              fontWeight: 700,
              color: activeStep === "done" ? "#00ff9d" : "var(--t-text-muted)",
            }}
          >
            {activeStep === "done" ? "✅ Reporte OK" : "📤 Reporte"}
          </div>
        </div>
        <div
          style={{
            display: "flex",
            gap: "1rem",
            marginTop: ".5rem",
            flexWrap: "wrap",
          }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 6,
              fontSize: ".68rem",
            }}
          >
            <div
              style={{
                width: 10,
                height: 10,
                borderRadius: 3,
                background: "#ef4444",
                flexShrink: 0,
              }}
            />
            <span style={{ color: "var(--t-text-muted)" }}>
              Aborta → ningún reporte generado
            </span>
          </div>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 6,
              fontSize: ".68rem",
            }}
          >
            <div
              style={{
                width: 10,
                height: 10,
                borderRadius: 3,
                background: "#06b6d4",
                flexShrink: 0,
              }}
            />
            <span style={{ color: "var(--t-text-muted)" }}>
              Anota → reporte con flag _integridad
            </span>
          </div>
        </div>
      </div>

      <div
        style={{
          padding: "1.2rem 1.4rem",
          borderRadius: 12,
          border: "1px solid var(--t-border)",
          background: "var(--t-bg-card)",
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            marginBottom: ".8rem",
          }}
        >
          <SectionTitle icon={<Cpu size={14} />}>
            Estado del Orquestador
          </SectionTitle>
          <button
            onClick={() =>
              AgentService.health()
                .then(setHealth)
                .catch(() => {})
            }
            style={{
              background: "var(--t-bg)",
              border: "1px solid var(--t-border)",
              borderRadius: 7,
              cursor: "pointer",
              color: "var(--t-text-muted)",
              padding: "5px 7px",
              display: "flex",
            }}
          >
            <RefreshCw size={12} />
          </button>
        </div>
        {health ? (
          <div
            style={{ display: "flex", flexDirection: "column", gap: ".6rem" }}
          >
            <div style={{ fontSize: ".74rem", color: "var(--t-text-muted)" }}>
              Agentes registrados:{" "}
              <strong style={{ color: "var(--t-text)" }}>
                {Object.keys(health.agentes ?? {}).length}
              </strong>
              <span style={{ marginLeft: 12 }}>
                WebSocket clients:{" "}
                <strong style={{ color: "var(--t-accent)" }}>
                  {health.clientes_ws}
                </strong>
              </span>
            </div>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))",
                gap: ".5rem",
              }}
            >
              {Object.entries(health.agentes ?? {}).map(([id, a]) => (
                <div
                  key={id}
                  style={{
                    padding: "8px 12px",
                    borderRadius: 8,
                    background: "var(--t-bg)",
                    border: "1px solid var(--t-border)",
                    display: "flex",
                    alignItems: "center",
                    gap: 8,
                  }}
                >
                  <div
                    style={{
                      width: 8,
                      height: 8,
                      borderRadius: "50%",
                      background: "#00ff9d",
                      flexShrink: 0,
                    }}
                  />
                  <div>
                    <div
                      style={{
                        fontSize: ".78rem",
                        fontWeight: 600,
                        color: "var(--t-text)",
                      }}
                    >
                      {a.nombre}
                    </div>
                    <div
                      style={{
                        fontSize: ".66rem",
                        color: "var(--t-text-muted)",
                      }}
                    >
                      {(a.modelo || "").replace("models/", "")} · {a.area}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        ) : (
          <div style={{ fontSize: ".8rem", color: "var(--t-text-muted)" }}>
            Sin datos del orquestador. ¿Está activo el backend Python?
          </div>
        )}
      </div>

      {telemetria.length > 0 && (
        <div
          style={{
            padding: "1rem 1.2rem",
            borderRadius: 12,
            border: "1px solid var(--t-border)",
            background: "var(--t-bg-card)",
          }}
        >
          <SectionTitle icon={<Cpu size={14} />}>
            Telemetría en vivo
          </SectionTitle>
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              gap: 3,
              marginTop: ".5rem",
            }}
          >
            {telemetria.map((t) => (
              <div
                key={t.id}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  fontSize: ".7rem",
                  padding: "3px 0",
                  color: t.status === "ok" ? "var(--t-text-muted)" : "#ef4444",
                }}
              >
                <Zap size={10} />
                <span>{t.filtro}</span>
                <span style={{ opacity: 0.5 }}>·</span>
                <span>{t.agente}</span>
                <span style={{ marginLeft: "auto", fontFamily: "monospace" }}>
                  {t.duracion_s?.toFixed(4)}s
                </span>
                <span
                  style={{
                    padding: "1px 6px",
                    borderRadius: 10,
                    fontSize: ".6rem",
                    background:
                      t.status === "ok"
                        ? "rgba(0,255,157,.1)"
                        : "rgba(239,68,68,.1)",
                    color: t.status === "ok" ? "#00ff9d" : "#ef4444",
                  }}
                >
                  {t.status}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      <GuardrailsConfig />
    </div>
  );
}

const selectStyle = {
  padding: "8px 10px",
  borderRadius: 8,
  border: "1px solid var(--t-border)",
  background: "var(--t-bg)",
  color: "var(--t-text)",
  fontSize: ".84rem",
  outline: "none",
  fontFamily: "inherit",
  width: "100%",
};
const btnEjecutar = {
  display: "flex",
  alignItems: "center",
  gap: 7,
  padding: "9px 18px",
  border: "none",
  borderRadius: 8,
  background:
    "linear-gradient(90deg,var(--t-accent),var(--t-accent2,var(--t-accent)))",
  color: "#fff",
  fontWeight: 700,
  fontSize: ".84rem",
  fontFamily: "inherit",
  whiteSpace: "nowrap",
};
