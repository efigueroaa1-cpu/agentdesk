/**
 * ProvidersPanel.jsx — Pestaña "Proveedores IA": configura las API keys de
 * los proveedores soportados (`GET /proveedores`, `PUT /proveedores/apikey`).
 *
 * Reconstruido desde el bundle de producción (react_dist/assets/index-CRDO1T5r.js,
 * función `qw`): el fuente original de este componente no estaba versionado.
 */
import { useState, useEffect } from "react";
import { RefreshCw, CheckCircle2, XCircle, Eye, EyeOff } from "../../icons.js";
import { API_BASE } from "../../services/agent.service";
import { addNotification } from "../ui/NotificationSystem";

const PROVEEDORES = [
  {
    id: "groq",
    nombre: "Groq",
    logo: "⚡",
    desc: "LLaMA 3.3, Mixtral, Gemma2 — GRATUITO y ultrarrápido",
    url: "https://console.groq.com/keys",
    modelos: ["LLaMA 3.3 70B", "LLaMA 3.1 8B", "Mixtral 8x7B", "Gemma2 9B"],
    gratis: true,
    color: "#f59e0b",
  },
  {
    id: "gemini",
    nombre: "Google Gemini",
    logo: "🔷",
    desc: "Gemini 2.5 Flash/Pro — cuota gratuita diaria, pago por uso",
    url: "https://aistudio.google.com/apikey",
    modelos: ["Gemini 2.5 Flash", "Gemini 1.5 Flash", "Gemini 1.5 Pro"],
    gratis: false,
    color: "#4285f4",
  },
  {
    id: "deepseek",
    nombre: "DeepSeek",
    logo: "🔍",
    desc: "DeepSeek Chat V3, R1 — muy económico, compatible OpenAI",
    url: "https://platform.deepseek.com/api_keys",
    modelos: ["DeepSeek Chat V3", "DeepSeek R1"],
    gratis: false,
    color: "#00d4ff",
  },
  {
    id: "openai",
    nombre: "OpenAI (ChatGPT)",
    logo: "🤖",
    desc: "GPT-4o, GPT-4o Mini, o1 — el más conocido",
    url: "https://platform.openai.com/api-keys",
    modelos: ["GPT-4o", "GPT-4o Mini", "o1 Mini"],
    gratis: false,
    color: "#00ff9d",
  },
  {
    id: "anthropic",
    nombre: "Anthropic (Claude)",
    logo: "🧠",
    desc: "Claude Opus, Sonnet, Haiku — muy capaz en análisis",
    url: "https://console.anthropic.com/settings/keys",
    modelos: ["Claude Opus", "Claude Sonnet", "Claude Haiku"],
    gratis: false,
    color: "#a78bfa",
  },
];

export default function ProvidersPanel() {
  const [configurados, setConfigurados] = useState({});
  const [valores, setValores] = useState({});
  const [verKey, setVerKey] = useState({});
  const [guardando, setGuardando] = useState({});
  const [cargando, setCargando] = useState(true);

  useEffect(() => {
    fetch(`${API_BASE}/proveedores`)
      .then((r) => r.json())
      .then((d) => {
        setConfigurados(d.proveedores ?? {});
        setCargando(false);
      })
      .catch(() => setCargando(false));
  }, []);

  async function guardar(id) {
    const key = (valores[id] ?? "").trim();
    if (!key) return;
    setGuardando((g) => ({ ...g, [id]: true }));
    try {
      const r = await fetch(`${API_BASE}/proveedores/apikey`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ proveedor: id, api_key: key }),
      }).then((res) => res.json());
      if (r.ok) {
        setConfigurados((c) => ({ ...c, [id]: true }));
        addNotification({
          message: `API key de ${id} guardada correctamente`,
          type: "success",
        });
        setValores((v) => ({ ...v, [id]: "" }));
      }
    } catch {
      addNotification({
        message: "Error al guardar la API key",
        type: "error",
      });
    } finally {
      setGuardando((g) => ({ ...g, [id]: false }));
    }
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
      <div
        style={{
          padding: "10px 14px",
          borderRadius: 10,
          background: "rgba(0,212,255,.07)",
          border: "1px solid rgba(0,212,255,.2)",
          fontSize: ".82rem",
          color: "var(--t-text-muted)",
        }}
      >
        Configura las API keys de los proveedores de IA que quieres usar. Cada
        agente puede usar un proveedor diferente — elige en la pestaña Agentes.{" "}
        <strong style={{ color: "#00ff9d" }}>
          Groq es completamente gratuito
        </strong>{" "}
        y muy rápido.
      </div>

      {cargando ? (
        <div
          style={{
            padding: "2rem",
            textAlign: "center",
            color: "var(--t-text-muted)",
          }}
        >
          <RefreshCw
            size={20}
            style={{ animation: "spin .8s linear infinite" }}
          />
          <style>{"@keyframes spin{to{transform:rotate(360deg)}}"}</style>
        </div>
      ) : (
        PROVEEDORES.map((p) => {
          const activo = configurados[p.id];
          return (
            <div
              key={p.id}
              style={{
                padding: "1.1rem 1.3rem",
                borderRadius: 12,
                transition: "all .2s",
                border: `1px solid ${activo ? p.color + "50" : "var(--t-border)"}`,
                background: activo ? `${p.color}08` : "var(--t-bg-card)",
              }}
            >
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  marginBottom: ".7rem",
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                  <span style={{ fontSize: 22 }}>{p.logo}</span>
                  <div>
                    <div
                      style={{ display: "flex", alignItems: "center", gap: 7 }}
                    >
                      <span
                        style={{
                          fontWeight: 700,
                          fontSize: ".9rem",
                          color: "var(--t-text)",
                        }}
                      >
                        {p.nombre}
                      </span>
                      {p.gratis && (
                        <span
                          style={{
                            padding: "1px 7px",
                            borderRadius: 20,
                            fontSize: ".62rem",
                            background: "rgba(0,255,157,.15)",
                            color: "#00ff9d",
                            fontWeight: 700,
                          }}
                        >
                          GRATIS
                        </span>
                      )}
                    </div>
                    <div
                      style={{
                        fontSize: ".72rem",
                        color: "var(--t-text-muted)",
                        marginTop: 2,
                      }}
                    >
                      {p.desc}
                    </div>
                  </div>
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
                  {activo ? (
                    <>
                      <CheckCircle2 size={16} color="#00ff9d" />
                      <span
                        style={{
                          fontSize: ".72rem",
                          color: "#00ff9d",
                          fontWeight: 600,
                        }}
                      >
                        Configurado
                      </span>
                    </>
                  ) : (
                    <>
                      <XCircle size={16} color="#64748b" />
                      <span style={{ fontSize: ".72rem", color: "#64748b" }}>
                        Sin configurar
                      </span>
                    </>
                  )}
                </div>
              </div>

              <div
                style={{
                  display: "flex",
                  gap: ".4rem",
                  flexWrap: "wrap",
                  marginBottom: ".8rem",
                }}
              >
                {p.modelos.map((m) => (
                  <span
                    key={m}
                    style={{
                      padding: "2px 9px",
                      borderRadius: 20,
                      fontSize: ".65rem",
                      background: `${p.color}15`,
                      color: p.color,
                      fontWeight: 500,
                    }}
                  >
                    {m}
                  </span>
                ))}
              </div>

              <div
                style={{ display: "flex", gap: ".5rem", alignItems: "center" }}
              >
                <div style={{ flex: 1, position: "relative" }}>
                  <input
                    type={verKey[p.id] ? "text" : "password"}
                    value={valores[p.id] ?? ""}
                    onChange={(e) =>
                      setValores((v) => ({ ...v, [p.id]: e.target.value }))
                    }
                    onKeyDown={(e) => e.key === "Enter" && guardar(p.id)}
                    placeholder={
                      activo
                        ? "••••••••••••  (ya configurada — pega nueva para actualizar)"
                        : "Pega aquí tu API key"
                    }
                    style={{
                      width: "100%",
                      padding: "8px 38px 8px 12px",
                      borderRadius: 8,
                      border: "1px solid var(--t-border)",
                      background: "var(--t-bg)",
                      color: "var(--t-text)",
                      fontSize: ".8rem",
                      outline: "none",
                      fontFamily: "inherit",
                      boxSizing: "border-box",
                    }}
                  />
                  <button
                    onClick={() =>
                      setVerKey((v) => ({ ...v, [p.id]: !v[p.id] }))
                    }
                    style={{
                      position: "absolute",
                      right: 8,
                      top: "50%",
                      transform: "translateY(-50%)",
                      background: "none",
                      border: "none",
                      color: "#64748b",
                      cursor: "pointer",
                      padding: 2,
                    }}
                  >
                    {verKey[p.id] ? <EyeOff size={15} /> : <Eye size={15} />}
                  </button>
                </div>
                <button
                  onClick={() => guardar(p.id)}
                  disabled={!valores[p.id]?.trim() || guardando[p.id]}
                  style={{
                    padding: "8px 16px",
                    borderRadius: 8,
                    border: "none",
                    cursor: "pointer",
                    background: valores[p.id]?.trim()
                      ? `linear-gradient(135deg, ${p.color}, ${p.color}bb)`
                      : "var(--t-border)",
                    color: valores[p.id]?.trim()
                      ? "#0a0e1a"
                      : "var(--t-text-muted)",
                    fontWeight: 600,
                    fontSize: ".78rem",
                    fontFamily: "inherit",
                    whiteSpace: "nowrap",
                  }}
                >
                  {guardando[p.id] ? "Guardando..." : "Guardar"}
                </button>
                <a
                  href={p.url}
                  target="_blank"
                  rel="noreferrer"
                  style={{
                    padding: "8px 12px",
                    borderRadius: 8,
                    border: "1px solid var(--t-border)",
                    color: p.color,
                    fontSize: ".75rem",
                    textDecoration: "none",
                    whiteSpace: "nowrap",
                  }}
                >
                  Obtener key →
                </a>
              </div>
            </div>
          );
        })
      )}
    </div>
  );
}
