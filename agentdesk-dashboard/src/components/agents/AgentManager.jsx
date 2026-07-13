/**
 * AgentManager.jsx — Pestaña "Tabla CRUD" dentro de Agentes.
 *
 * Tabla con todos los agentes registrados: buscar, crear, editar y eliminar
 * (con confirmación inline). Reutiliza el modal de creación/edición.
 *
 * Reconstruido desde el bundle de producción (react_dist/assets/index-CRDO1T5r.js,
 * función `r5`): el fuente original de este componente no estaba versionado.
 */
import { useState, useEffect, useCallback } from "react";
import {
  Search,
  RefreshCw,
  Plus,
  Edit2,
  Trash2,
  AlertCircle,
  Bot,
  X,
  Save,
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

const rowGrid = {
  display: "grid",
  gridTemplateColumns: "2fr 1fr 1.6fr .6fr .8fr 1fr",
  alignItems: "center",
  padding: "12px 16px",
  gap: ".8rem",
};
const btnBase = {
  border: "none",
  cursor: "pointer",
  fontFamily: "inherit",
  borderRadius: 7,
};
const btnGhost = {
  ...btnBase,
  background: "var(--t-bg)",
  border: "1px solid var(--t-border)",
  color: "var(--t-text-muted)",
  padding: "6px 8px",
  display: "flex",
  alignItems: "center",
};
const btnPrimary = {
  ...btnBase,
  background:
    "linear-gradient(90deg,var(--t-accent),var(--t-accent2,var(--t-accent)))",
  color: "#fff",
  padding: "7px 14px",
  fontWeight: 600,
  fontSize: ".82rem",
  display: "flex",
  alignItems: "center",
  gap: 5,
};
const btnDanger = {
  ...btnBase,
  background: "#ff2d55",
  color: "#fff",
  fontWeight: 600,
  padding: "3px 10px",
  fontSize: ".72rem",
};
const btnCancel = {
  ...btnBase,
  background: "var(--t-bg)",
  border: "1px solid var(--t-border)",
  color: "var(--t-text-muted)",
  fontWeight: 500,
  padding: "3px 10px",
  fontSize: ".72rem",
};
const inputStyle = {
  width: "100%",
  boxSizing: "border-box",
  padding: "8px 10px",
  borderRadius: 8,
  border: "1px solid var(--t-border)",
  background: "var(--t-bg)",
  color: "var(--t-text)",
  fontSize: ".85rem",
  outline: "none",
  fontFamily: "inherit",
};

function Th({ children, center }) {
  return (
    <div
      style={{
        fontSize: ".7rem",
        fontWeight: 700,
        letterSpacing: ".06em",
        textTransform: "uppercase",
        color: "var(--t-text-muted)",
        textAlign: center ? "center" : "left",
      }}
    >
      {children}
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

function AgentModal({ agente, onClose, onSaved }) {
  const isEdit = !!agente;
  const [form, setForm] = useState(
    isEdit ? { ...emptyForm, ...agente } : emptyForm,
  );
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
      if (isEdit) await AgentService.update(agente.id, form);
      else await AgentService.create(form);
      onSaved?.();
      onClose();
    } catch (err) {
      setError(typeof err === "string" ? err : "Error al guardar el agente.");
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
              {isEdit ? `Editar · ${agente.nombre}` : "Nuevo Agente"}
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
          <label
            style={{
              fontSize: ".75rem",
              fontWeight: 600,
              color: "var(--t-text-muted)",
              display: "block",
            }}
          >
            Nombre / Apodo
            <input
              value={form.nombre}
              onChange={(e) => set("nombre", e.target.value)}
              placeholder="Ej: Analista Financiero"
              style={{ ...inputStyle, marginTop: 5 }}
            />
          </label>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "1fr 1fr",
              gap: ".8rem",
            }}
          >
            <label
              style={{
                fontSize: ".75rem",
                fontWeight: 600,
                color: "var(--t-text-muted)",
                display: "block",
              }}
            >
              Área
              <select
                value={form.area}
                onChange={(e) => set("area", e.target.value)}
                style={{ ...inputStyle, marginTop: 5 }}
              >
                {AREAS.map((a) => (
                  <option key={a} value={a}>
                    {a}
                  </option>
                ))}
              </select>
            </label>
            <label
              style={{
                fontSize: ".75rem",
                fontWeight: 600,
                color: "var(--t-text-muted)",
                display: "block",
              }}
            >
              Modelo
              <input
                value={form.modelo}
                onChange={(e) => set("modelo", e.target.value)}
                style={{ ...inputStyle, marginTop: 5 }}
              />
            </label>
          </div>
          <label
            style={{
              fontSize: ".75rem",
              fontWeight: 600,
              color: "var(--t-text-muted)",
              display: "block",
            }}
          >
            Temperatura · {Number(form.temperatura).toFixed(1)}
            <input
              type="range"
              min={0}
              max={1}
              step={0.1}
              value={form.temperatura}
              onChange={(e) => set("temperatura", parseFloat(e.target.value))}
              style={{ width: "100%", accentColor: "var(--t-accent)" }}
            />
          </label>
          <label
            style={{
              fontSize: ".75rem",
              fontWeight: 600,
              color: "var(--t-text-muted)",
              display: "block",
            }}
          >
            Prompt base (rol del agente)
            <textarea
              value={form.prompt_base}
              onChange={(e) => set("prompt_base", e.target.value)}
              rows={3}
              placeholder="Ej: Eres un analista financiero senior experto en..."
              style={{
                ...inputStyle,
                marginTop: 5,
                resize: "vertical",
                minHeight: 72,
              }}
            />
          </label>
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
              <Save size={14} />{" "}
              {saving
                ? "Guardando..."
                : isEdit
                  ? "Guardar cambios"
                  : "Crear agente"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

export default function AgentManager() {
  const [agentes, setAgentes] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busqueda, setBusqueda] = useState("");
  const [showModal, setShowModal] = useState(false);
  const [editando, setEditando] = useState(null);
  const [confirmando, setConfirmando] = useState(null);
  const [eliminando, setEliminando] = useState(null);

  const cargar = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const data = await AgentService.getAll();
      setAgentes(data.agentes ?? []);
    } catch (e) {
      setError(
        typeof e === "string" ? e : "No se pudo conectar con el backend.",
      );
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
      )
        cargar();
    });
  }, [cargar]);

  async function eliminar(id) {
    setEliminando(id);
    try {
      await AgentService.delete(id);
      setAgentes((list) => list.filter((a) => a.id !== id));
    } catch (e) {
      setError(typeof e === "string" ? e : "Error al eliminar el agente.");
    } finally {
      setEliminando(null);
      setConfirmando(null);
    }
  }

  const filtrados = agentes.filter(
    (a) =>
      (a.nombre || "").toLowerCase().includes(busqueda.toLowerCase()) ||
      (a.area || "").toLowerCase().includes(busqueda.toLowerCase()) ||
      (a.id || "").toLowerCase().includes(busqueda.toLowerCase()),
  );

  return (
    <div style={{ padding: "1.2rem 0" }}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          marginBottom: "1.2rem",
          flexWrap: "wrap",
          gap: ".6rem",
        }}
      >
        <div>
          <h2
            style={{
              margin: 0,
              fontSize: "1.05rem",
              fontWeight: 700,
              color: "var(--t-text)",
            }}
          >
            Gestión de Agentes
          </h2>
          <p
            style={{
              margin: "2px 0 0",
              fontSize: ".75rem",
              color: "var(--t-text-muted)",
            }}
          >
            {agentes.length} agente{agentes.length !== 1 ? "s" : ""} registrado
            {agentes.length !== 1 ? "s" : ""}
          </p>
        </div>
        <div style={{ display: "flex", gap: ".5rem", alignItems: "center" }}>
          <div style={{ position: "relative" }}>
            <Search
              size={14}
              style={{
                position: "absolute",
                left: 9,
                top: "50%",
                transform: "translateY(-50%)",
                color: "var(--t-text-muted)",
              }}
            />
            <input
              value={busqueda}
              onChange={(e) => setBusqueda(e.target.value)}
              placeholder="Buscar agente..."
              style={{
                paddingLeft: 28,
                paddingRight: 10,
                paddingTop: 7,
                paddingBottom: 7,
                borderRadius: 8,
                border: "1px solid var(--t-border)",
                background: "var(--t-bg-card)",
                color: "var(--t-text)",
                fontSize: ".82rem",
                outline: "none",
                width: 180,
                fontFamily: "inherit",
              }}
            />
          </div>
          <button onClick={cargar} title="Recargar" style={btnGhost}>
            <RefreshCw size={15} />
          </button>
          <button
            onClick={() => {
              setEditando(null);
              setShowModal(true);
            }}
            style={btnPrimary}
          >
            <Plus size={15} /> Agregar
          </button>
        </div>
      </div>

      {error && (
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            padding: "10px 14px",
            background: "rgba(255,45,85,.1)",
            border: "1px solid rgba(255,45,85,.3)",
            borderRadius: 8,
            marginBottom: "1rem",
            color: "#ff2d55",
            fontSize: ".82rem",
          }}
        >
          <AlertCircle size={15} /> {error}
        </div>
      )}

      <div
        style={{
          border: "1px solid var(--t-border)",
          borderRadius: 12,
          overflow: "hidden",
          background: "var(--t-bg-card)",
        }}
      >
        <div
          style={{
            ...rowGrid,
            background: "var(--t-bg)",
            borderBottom: "1px solid var(--t-border)",
          }}
        >
          <Th>Agente</Th>
          <Th>Área</Th>
          <Th>Modelo</Th>
          <Th center>Temp.</Th>
          <Th>Idioma</Th>
          <Th center>Acciones</Th>
        </div>

        {loading ? (
          <div
            style={{
              padding: "2rem",
              textAlign: "center",
              color: "var(--t-text-muted)",
              fontSize: ".85rem",
            }}
          >
            Cargando agentes...
          </div>
        ) : filtrados.length === 0 ? (
          <div
            style={{
              padding: "2.5rem",
              textAlign: "center",
              color: "var(--t-text-muted)",
              fontSize: ".85rem",
            }}
          >
            {busqueda
              ? `Sin resultados para "${busqueda}"`
              : "No hay agentes registrados. Haz clic en Agregar para crear el primero."}
          </div>
        ) : (
          filtrados.map((a, i) => (
            <div
              key={a.id}
              style={{
                ...rowGrid,
                borderTop: i > 0 ? "1px solid var(--t-border)" : "none",
                background:
                  confirmando === a.id ? "rgba(255,45,85,.06)" : "transparent",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <div
                  style={{
                    width: 32,
                    height: 32,
                    borderRadius: 8,
                    background: `${areaColor(a.area)}22`,
                    border: `1px solid ${areaColor(a.area)}44`,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    flexShrink: 0,
                  }}
                >
                  <Bot size={14} color={areaColor(a.area)} />
                </div>
                <div>
                  <div
                    style={{
                      fontWeight: 600,
                      fontSize: ".85rem",
                      color: "var(--t-text)",
                    }}
                  >
                    {a.nombre}
                  </div>
                  <div
                    style={{ fontSize: ".7rem", color: "var(--t-text-muted)" }}
                  >
                    {a.id}
                  </div>
                </div>
              </div>
              <div>
                <span
                  style={{
                    padding: "3px 10px",
                    borderRadius: 20,
                    background: `${areaColor(a.area)}22`,
                    border: `1px solid ${areaColor(a.area)}44`,
                    color: areaColor(a.area),
                    fontSize: ".72rem",
                    fontWeight: 600,
                  }}
                >
                  {a.area || "General"}
                </span>
              </div>
              <div style={{ fontSize: ".78rem", color: "var(--t-text-muted)" }}>
                {(a.modelo || "").replace("models/", "")}
              </div>
              <div
                style={{
                  textAlign: "center",
                  fontSize: ".82rem",
                  color: "var(--t-accent)",
                  fontWeight: 600,
                }}
              >
                {a.temperatura ?? "-"}
              </div>
              <div style={{ fontSize: ".78rem", color: "var(--t-text-muted)" }}>
                {a.idioma || "español"}
              </div>
              <div
                style={{
                  display: "flex",
                  gap: ".4rem",
                  justifyContent: "center",
                  alignItems: "center",
                }}
              >
                {confirmando === a.id ? (
                  <div
                    style={{
                      display: "flex",
                      gap: ".3rem",
                      alignItems: "center",
                    }}
                  >
                    <span
                      style={{
                        fontSize: ".72rem",
                        color: "#ff2d55",
                        whiteSpace: "nowrap",
                      }}
                    >
                      ¿Eliminar?
                    </span>
                    <button
                      onClick={() => eliminar(a.id)}
                      disabled={eliminando === a.id}
                      style={btnDanger}
                    >
                      {eliminando === a.id ? "..." : "Sí"}
                    </button>
                    <button
                      onClick={() => setConfirmando(null)}
                      style={btnCancel}
                    >
                      No
                    </button>
                  </div>
                ) : (
                  <>
                    <button
                      onClick={() => {
                        setEditando(a);
                        setShowModal(true);
                      }}
                      title="Editar"
                      style={btnGhost}
                    >
                      <Edit2 size={14} />
                    </button>
                    <button
                      onClick={() => setConfirmando(a.id)}
                      title="Eliminar"
                      style={{ ...btnGhost, color: "#ff2d55" }}
                    >
                      <Trash2 size={14} />
                    </button>
                  </>
                )}
              </div>
            </div>
          ))
        )}
      </div>

      {showModal && (
        <AgentModal
          agente={editando}
          onClose={() => {
            setShowModal(false);
            setEditando(null);
          }}
          onSaved={cargar}
        />
      )}
    </div>
  );
}
