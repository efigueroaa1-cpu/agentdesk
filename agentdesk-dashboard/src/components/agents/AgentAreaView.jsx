/**
 * AgentAreaView.jsx — Pestaña "Configurar por Área" dentro de Agentes.
 *
 * Agrupa los agentes por área en columnas de tarjetas. Al hacer clic en un
 * agente se abre un panel lateral de detalle/edición (nombre, área, idioma,
 * modelo, temperatura, prompt base y encadenamiento). También permite crear
 * agentes nuevos.
 *
 * Reconstruido desde el bundle de producción (react_dist/assets/index-CRDO1T5r.js,
 * función `Jb` + subcomponentes `Hb`/`Zb`/`dm`): el fuente original de este
 * componente no estaba versionado.
 */
import { useState, useEffect, useCallback } from "react";
import {
  RefreshCw,
  Plus,
  X,
  Save,
  CheckCircle2,
  AlertCircle,
  ArrowRight,
  Bot,
} from "../../icons.js";
import { AgentService } from "../../services/agent.service";

const AREA_STYLE = {
  Finanzas: { color: "#00d4ff", bg: "rgba(0,212,255,.1)", icon: "💰" },
  Mecánica: { color: "#00ff9d", bg: "rgba(0,255,157,.1)", icon: "⚙️" },
  RRHH: { color: "#f59e0b", bg: "rgba(245,158,11,.1)", icon: "👥" },
  Logística: { color: "#8b5cf6", bg: "rgba(139,92,246,.1)", icon: "🚚" },
  Marketing: { color: "#ef4444", bg: "rgba(239,68,68,.1)", icon: "📣" },
  Legal: { color: "#f97316", bg: "rgba(249,115,22,.1)", icon: "⚖️" },
  Tecnología: { color: "#06b6d4", bg: "rgba(6,182,212,.1)", icon: "💻" },
  Operaciones: { color: "#84cc16", bg: "rgba(132,204,22,.1)", icon: "🏭" },
  General: { color: "#64748b", bg: "rgba(100,116,139,.1)", icon: "🤖" },
};
function areaInfo(area) {
  const key = area
    ? area.charAt(0).toUpperCase() + area.slice(1).toLowerCase()
    : "General";
  return AREA_STYLE[key] ?? AREA_STYLE.General;
}

const AREAS = [
  "General",
  "Finanzas",
  "Mecánica",
  "RRHH",
  "Logística",
  "Marketing",
  "Legal",
  "Tecnología",
  "Operaciones",
];
const IDIOMAS = ["español", "inglés", "portugués", "francés", "alemán"];

const inputStyle = {
  width: "100%",
  boxSizing: "border-box",
  padding: "7px 9px",
  borderRadius: 7,
  border: "1px solid var(--t-border)",
  background: "var(--t-bg)",
  color: "var(--t-text)",
  fontSize: ".82rem",
  outline: "none",
  fontFamily: "inherit",
};
const btnBase = {
  border: "none",
  cursor: "pointer",
  fontFamily: "inherit",
  borderRadius: 7,
};
const btnGhost = {
  ...btnBase,
  background: "var(--t-bg-card)",
  border: "1px solid var(--t-border)",
  color: "var(--t-text-muted)",
  padding: "6px 8px",
  display: "flex",
};
const btnPrimary = {
  ...btnBase,
  background:
    "linear-gradient(90deg,var(--t-accent),var(--t-accent2,var(--t-accent)))",
  color: "#fff",
  padding: "6px 13px",
  fontWeight: 600,
  fontSize: ".8rem",
  display: "flex",
  alignItems: "center",
  gap: 5,
};

function AgentCard({ agente, selected, onClick }) {
  const a = areaInfo(agente.area);
  return (
    <div
      onClick={onClick}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onClick?.();
        }
      }}
      style={{
        padding: "12px 14px",
        borderRadius: 10,
        cursor: "pointer",
        transition: "all .15s",
        border: selected ? `2px solid ${a.color}` : "1px solid var(--t-border)",
        background: selected ? a.bg : "var(--t-bg-card)",
        display: "flex",
        flexDirection: "column",
        gap: 8,
        boxShadow: selected ? `0 0 12px ${a.color}25` : "none",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "flex-start",
          justifyContent: "space-between",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <div
            style={{
              width: 36,
              height: 36,
              borderRadius: 9,
              background: a.bg,
              border: `1px solid ${a.color}40`,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontSize: 16,
            }}
          >
            {a.icon}
          </div>
          <div>
            <div
              style={{
                fontWeight: 700,
                fontSize: ".83rem",
                color: "var(--t-text)",
                lineHeight: 1.2,
              }}
            >
              {agente.nombre}
            </div>
            <div
              style={{
                fontSize: ".67rem",
                color: "var(--t-text-muted)",
                marginTop: 1,
              }}
            >
              {agente.id}
            </div>
          </div>
        </div>
      </div>
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
        <span
          style={{
            padding: "2px 7px",
            borderRadius: 20,
            fontSize: ".65rem",
            fontWeight: 600,
            background: `${a.color}18`,
            color: a.color,
            border: `1px solid ${a.color}30`,
          }}
        >
          {(agente.modelo || "").replace("models/", "")}
        </span>
        <span
          style={{
            padding: "2px 7px",
            borderRadius: 20,
            fontSize: ".65rem",
            fontWeight: 600,
            background: "rgba(100,116,139,.14)",
            color: "#64748b",
            border: "1px solid rgba(100,116,139,.3)",
          }}
        >
          temp {agente.temperatura ?? "-"}
        </span>
      </div>
      {agente.prompt_base && (
        <div
          style={{
            fontSize: ".68rem",
            color: "var(--t-text-muted)",
            overflow: "hidden",
            display: "-webkit-box",
            WebkitLineClamp: 2,
            WebkitBoxOrient: "vertical",
            lineHeight: 1.45,
          }}
        >
          {agente.prompt_base}
        </div>
      )}
      {agente.siguiente_agente_id && (
        <div
          style={{
            fontSize: ".67rem",
            color: "var(--t-accent)",
            display: "flex",
            alignItems: "center",
            gap: 4,
          }}
        >
          ⛓️ → {agente.siguiente_agente_id}
        </div>
      )}
    </div>
  );
}

function Section({ icon, title, children }) {
  return (
    <div>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
          marginBottom: ".5rem",
          fontSize: ".68rem",
          fontWeight: 700,
          letterSpacing: ".07em",
          textTransform: "uppercase",
          color: "var(--t-text-muted)",
          borderBottom: "1px solid var(--t-border)",
          paddingBottom: ".35rem",
        }}
      >
        {icon} {title}
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: ".6rem" }}>
        {children}
      </div>
    </div>
  );
}
function Field({ label, children }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      <label
        style={{
          fontSize: ".7rem",
          fontWeight: 600,
          color: "var(--t-text-muted)",
        }}
      >
        {label}
      </label>
      {children}
    </div>
  );
}

function AgentDetail({ agente, allAgentes, onClose, onSaved }) {
  const [form, setForm] = useState({ ...agente });
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState(null);

  useEffect(() => {
    setForm({ ...agente });
    setMsg(null);
  }, [agente]);

  function set(key, value) {
    setForm((f) => ({ ...f, [key]: value }));
    setMsg(null);
  }

  async function guardar() {
    setSaving(true);
    setMsg(null);
    try {
      await AgentService.update(agente.id, form);
      setMsg({ type: "ok", text: "Configuración guardada correctamente." });
      onSaved?.();
    } catch (e) {
      setMsg({
        type: "err",
        text: typeof e === "string" ? e : "Error al guardar.",
      });
    } finally {
      setSaving(false);
    }
  }

  return (
    <div
      style={{
        width: 380,
        flexShrink: 0,
        background: "var(--t-bg-card)",
        border: "1px solid var(--t-border)",
        borderRadius: 14,
        display: "flex",
        flexDirection: "column",
        overflow: "hidden",
        height: "100%",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "1rem 1.1rem",
          borderBottom: "1px solid var(--t-border)",
          background: "var(--t-bg)",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <Bot size={16} color="var(--t-accent)" />
          <div>
            <div
              style={{
                fontWeight: 700,
                fontSize: ".88rem",
                color: "var(--t-text)",
              }}
            >
              {agente.nombre}
            </div>
            <div style={{ fontSize: ".68rem", color: "var(--t-text-muted)" }}>
              {agente.id}
            </div>
          </div>
        </div>
        <button onClick={onClose} style={btnGhost}>
          <X size={16} />
        </button>
      </div>

      <div
        style={{
          flex: 1,
          overflowY: "auto",
          padding: "1rem 1.1rem",
          display: "flex",
          flexDirection: "column",
          gap: "1.1rem",
        }}
      >
        <Section icon={<Bot size={13} />} title="Identidad">
          <Field label="Nombre / Apodo">
            <input
              value={form.nombre ?? ""}
              onChange={(e) => set("nombre", e.target.value)}
              style={inputStyle}
            />
          </Field>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "1fr 1fr",
              gap: ".7rem",
            }}
          >
            <Field label="Área">
              <select
                value={form.area ?? "General"}
                onChange={(e) => set("area", e.target.value)}
                style={inputStyle}
              >
                {AREAS.map((a) => (
                  <option key={a}>{a}</option>
                ))}
              </select>
            </Field>
            <Field label="Idioma">
              <select
                value={form.idioma ?? "español"}
                onChange={(e) => set("idioma", e.target.value)}
                style={inputStyle}
              >
                {IDIOMAS.map((l) => (
                  <option key={l}>{l}</option>
                ))}
              </select>
            </Field>
          </div>
        </Section>

        <Section icon={<Bot size={13} />} title="Modelo IA">
          <Field label="Modelo">
            <input
              value={form.modelo ?? ""}
              onChange={(e) => set("modelo", e.target.value)}
              style={inputStyle}
              placeholder="models/gemini-2.5-flash"
            />
          </Field>
          <Field
            label={`Temperatura · ${(form.temperatura ?? 0.4).toFixed(1)}`}
          >
            <input
              type="range"
              min={0}
              max={1}
              step={0.1}
              value={form.temperatura ?? 0.4}
              onChange={(e) => set("temperatura", parseFloat(e.target.value))}
              style={{ width: "100%", accentColor: "var(--t-accent)" }}
            />
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                fontSize: ".62rem",
                color: "var(--t-text-muted)",
              }}
            >
              <span>0.0 · Preciso</span>
              <span>1.0 · Creativo</span>
            </div>
          </Field>
        </Section>

        <Section icon={<Bot size={13} />} title="Personalidad">
          <Field label="Prompt base (rol del agente)">
            <textarea
              value={form.prompt_base ?? ""}
              onChange={(e) => set("prompt_base", e.target.value)}
              placeholder="Ej: Eres un analista financiero senior..."
              rows={4}
              style={{ ...inputStyle, resize: "vertical", minHeight: 90 }}
            />
          </Field>
        </Section>

        <Section icon={<ArrowRight size={13} />} title="Encadenamiento">
          <Field label="Siguiente agente en la cadena">
            <select
              value={form.siguiente_agente_id ?? ""}
              onChange={(e) =>
                set("siguiente_agente_id", e.target.value || null)
              }
              style={inputStyle}
            >
              <option value="">— Ninguno (último de la cadena) —</option>
              {allAgentes
                .filter((a) => a.id !== agente.id)
                .map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.nombre} ({a.id})
                  </option>
                ))}
            </select>
          </Field>
        </Section>
      </div>

      <div
        style={{
          padding: "1rem 1.1rem",
          borderTop: "1px solid var(--t-border)",
          background: "var(--t-bg)",
          display: "flex",
          flexDirection: "column",
          gap: ".6rem",
        }}
      >
        {msg && (
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 6,
              fontSize: ".75rem",
              color: msg.type === "ok" ? "#00ff9d" : "#ff2d55",
            }}
          >
            {msg.type === "ok" ? (
              <CheckCircle2 size={13} />
            ) : (
              <AlertCircle size={13} />
            )}
            {msg.text}
          </div>
        )}
        <button
          onClick={guardar}
          disabled={saving}
          style={{
            ...btnPrimary,
            width: "100%",
            justifyContent: "center",
            padding: "9px 0",
            opacity: saving ? 0.6 : 1,
          }}
        >
          <Save size={14} /> {saving ? "Guardando..." : "Guardar configuración"}
        </button>
      </div>
    </div>
  );
}

const emptyForm = {
  nombre: "",
  area: "General",
  modelo: "models/gemini-2.5-flash",
  temperatura: 0.4,
  idioma: "español",
  prompt_base: "",
};

function NewAgentModal({ onClose, onSaved }) {
  const [form, setForm] = useState(emptyForm);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  function set(k, v) {
    setForm((f) => ({ ...f, [k]: v }));
    setError("");
  }

  async function submit(e) {
    e.preventDefault();
    if (!form.nombre.trim()) {
      setError("El nombre es obligatorio.");
      return;
    }
    setSaving(true);
    try {
      await AgentService.create(form);
      onSaved?.();
      onClose();
    } catch (err) {
      setError(typeof err === "string" ? err : "Error al crear el agente.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 9999,
        background: "rgba(0,0,0,.65)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: "1rem",
      }}
    >
      <div
        style={{
          background: "var(--t-bg-card)",
          border: "1px solid var(--t-border)",
          borderRadius: 14,
          width: "100%",
          maxWidth: 520,
          boxShadow: "0 24px 64px rgba(0,0,0,.5)",
          overflow: "hidden",
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "1.1rem 1.4rem",
            borderBottom: "1px solid var(--t-border)",
            background: "var(--t-bg)",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <Bot size={18} color="var(--t-accent)" />
            <span
              style={{
                fontWeight: 700,
                color: "var(--t-text)",
                fontSize: ".95rem",
              }}
            >
              Nuevo Agente
            </span>
          </div>
          <button onClick={onClose} style={btnGhost}>
            <X size={18} />
          </button>
        </div>
        <form
          onSubmit={submit}
          style={{
            padding: "1.4rem",
            display: "flex",
            flexDirection: "column",
            gap: "1rem",
          }}
        >
          <Field label="Nombre / Apodo">
            <input
              value={form.nombre}
              onChange={(e) => set("nombre", e.target.value)}
              placeholder="Ej: Analista Financiero"
              style={inputStyle}
            />
          </Field>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "1fr 1fr",
              gap: ".8rem",
            }}
          >
            <Field label="Área">
              <select
                value={form.area}
                onChange={(e) => set("area", e.target.value)}
                style={inputStyle}
              >
                {AREAS.map((a) => (
                  <option key={a} value={a}>
                    {a}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Idioma">
              <select
                value={form.idioma}
                onChange={(e) => set("idioma", e.target.value)}
                style={inputStyle}
              >
                {IDIOMAS.map((l) => (
                  <option key={l} value={l}>
                    {l}
                  </option>
                ))}
              </select>
            </Field>
          </div>
          <Field label="Modelo de IA">
            <input
              value={form.modelo}
              onChange={(e) => set("modelo", e.target.value)}
              style={inputStyle}
            />
          </Field>
          <Field label={`Temperatura · ${form.temperatura.toFixed(1)}`}>
            <input
              type="range"
              min={0}
              max={1}
              step={0.1}
              value={form.temperatura}
              onChange={(e) => set("temperatura", parseFloat(e.target.value))}
              style={{ width: "100%", accentColor: "var(--t-accent)" }}
            />
          </Field>
          <Field label="Prompt base (rol del agente)">
            <textarea
              value={form.prompt_base}
              onChange={(e) => set("prompt_base", e.target.value)}
              placeholder="Ej: Eres un analista financiero senior experto en..."
              rows={3}
              style={{ ...inputStyle, resize: "vertical", minHeight: 72 }}
            />
          </Field>
          {error && (
            <div
              style={{
                padding: "8px 12px",
                borderRadius: 8,
                background: "rgba(255,45,85,.12)",
                color: "#ff2d55",
                fontSize: ".78rem",
              }}
            >
              {error}
            </div>
          )}
          <div
            style={{
              display: "flex",
              gap: ".6rem",
              justifyContent: "flex-end",
              paddingTop: ".4rem",
            }}
          >
            <button
              type="button"
              onClick={onClose}
              style={{
                padding: "8px 20px",
                borderRadius: 8,
                border: "1px solid var(--t-border)",
                background: "var(--t-bg)",
                color: "var(--t-text-muted)",
                cursor: "pointer",
                fontSize: ".84rem",
                fontWeight: 600,
                fontFamily: "inherit",
              }}
            >
              Cancelar
            </button>
            <button
              type="submit"
              disabled={saving}
              style={{
                ...btnPrimary,
                padding: "8px 20px",
                opacity: saving ? 0.6 : 1,
              }}
            >
              {saving ? "Guardando..." : "Crear agente"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

export default function AgentAreaView() {
  const [agentes, setAgentes] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState(null);
  const [showNew, setShowNew] = useState(false);
  const [filtroArea, setFiltroArea] = useState("Todas");

  const cargar = useCallback(async () => {
    setLoading(true);
    try {
      const data = await AgentService.getAll();
      setAgentes(data.agentes ?? []);
    } catch {
      setAgentes([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    cargar();
    return AgentService.onWsMessage((msg) => {
      if (
        ["agente_creado", "agente_eliminado", "agente_actualizado"].includes(
          msg.tipo,
        )
      ) {
        cargar();
        if (msg.tipo === "agente_eliminado" && selected?.id === msg.agente_id)
          setSelected(null);
      }
    });
  }, [cargar, selected]);

  const areas = [...new Set(agentes.map((a) => a.area || "General"))].sort();
  const visibles =
    filtroArea === "Todas"
      ? agentes
      : agentes.filter((a) => (a.area || "General") === filtroArea);
  const porArea = areas.reduce((acc, area) => {
    const lista = visibles.filter((a) => (a.area || "General") === area);
    if (lista.length > 0) acc[area] = lista;
    return acc;
  }, {});

  return (
    <div style={{ display: "flex", gap: "1.2rem", minHeight: 500 }}>
      <div
        style={{
          flex: 1,
          display: "flex",
          flexDirection: "column",
          gap: "1rem",
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
          <div style={{ display: "flex", gap: ".4rem", flexWrap: "wrap" }}>
            {["Todas", ...areas].map((a) => {
              const info = areaInfo(a === "Todas" ? null : a);
              const active = filtroArea === a;
              return (
                <button
                  key={a}
                  onClick={() => setFiltroArea(a)}
                  style={{
                    padding: "4px 12px",
                    borderRadius: 20,
                    fontSize: ".72rem",
                    fontWeight: 600,
                    cursor: "pointer",
                    fontFamily: "inherit",
                    border: `1px solid ${active ? info.color : "var(--t-border)"}`,
                    background: active ? `${info.color}18` : "transparent",
                    color: active ? info.color : "var(--t-text-muted)",
                  }}
                >
                  {a}
                </button>
              );
            })}
          </div>
          <div style={{ display: "flex", gap: ".4rem" }}>
            <button onClick={cargar} style={btnGhost} title="Refrescar">
              <RefreshCw size={14} />
            </button>
            <button onClick={() => setShowNew(true)} style={btnPrimary}>
              <Plus size={14} /> Agregar
            </button>
          </div>
        </div>

        {loading ? (
          <div
            style={{
              textAlign: "center",
              padding: "2rem",
              color: "var(--t-text-muted)",
              fontSize: ".84rem",
            }}
          >
            Cargando agentes...
          </div>
        ) : Object.keys(porArea).length === 0 ? (
          <div
            style={{
              textAlign: "center",
              padding: "2rem",
              color: "var(--t-text-muted)",
              fontSize: ".84rem",
            }}
          >
            No hay agentes en esta área. Haz clic en Agregar.
          </div>
        ) : (
          Object.entries(porArea).map(([area, lista]) => {
            const info = areaInfo(area);
            return (
              <div key={area}>
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 8,
                    marginBottom: ".6rem",
                    padding: "6px 10px",
                    borderRadius: 8,
                    background: info.bg,
                    border: `1px solid ${info.color}25`,
                  }}
                >
                  <span style={{ fontSize: 15 }}>{info.icon}</span>
                  <span
                    style={{
                      fontWeight: 700,
                      fontSize: ".78rem",
                      color: info.color,
                      letterSpacing: ".04em",
                    }}
                  >
                    {area.toUpperCase()}
                  </span>
                  <span
                    style={{
                      marginLeft: "auto",
                      fontSize: ".65rem",
                      fontWeight: 600,
                      padding: "1px 7px",
                      borderRadius: 20,
                      background: `${info.color}25`,
                      color: info.color,
                    }}
                  >
                    {lista.length} agente{lista.length !== 1 ? "s" : ""}
                  </span>
                </div>
                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns:
                      "repeat(auto-fill, minmax(240px, 1fr))",
                    gap: ".6rem",
                  }}
                >
                  {lista.map((a) => (
                    <AgentCard
                      key={a.id}
                      agente={a}
                      selected={selected?.id === a.id}
                      onClick={() =>
                        setSelected(a.id === selected?.id ? null : a)
                      }
                    />
                  ))}
                </div>
              </div>
            );
          })
        )}
      </div>

      {selected && (
        <AgentDetail
          agente={selected}
          allAgentes={agentes}
          onClose={() => setSelected(null)}
          onSaved={() => {
            cargar();
            AgentService.getAll()
              .then((d) => {
                const actualizado = (d.agentes ?? []).find(
                  (a) => a.id === selected.id,
                );
                if (actualizado) setSelected(actualizado);
              })
              .catch(() => {});
          }}
        />
      )}

      {showNew && (
        <NewAgentModal onClose={() => setShowNew(false)} onSaved={cargar} />
      )}
    </div>
  );
}
