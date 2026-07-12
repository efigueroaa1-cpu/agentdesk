/**
 * ProyectosModule.jsx — Kanban de gestión de proyectos (ID 14).
 * Nativización del antiguo proyectos.html (iframe): mismo modelo de datos y
 * clave localStorage "ad-proyectos-v1", por lo que los tableros existentes
 * de los usuarios se conservan sin migración.
 */
import { useState, useEffect, useRef, useCallback } from "react";
import { Plus, X, Trash2, Edit2, Calendar, Bot } from "../../icons.js";
import { API_BASE } from "../../services/agent.service";

const LS_KEY = "ad-proyectos-v1";

const COLS = [
  { id: "pendiente", label: "📋 Pendiente", color: "#4a6280" },
  { id: "en-proceso", label: "⚡ En Proceso", color: "var(--t-accent)" },
  { id: "revision", label: "🔍 Revisión", color: "#f59e0b" },
  { id: "completado", label: "✅ Completado", color: "#00ff9d" },
];

const PRIO_COLORS = { alta: "#ff2d55", media: "#f59e0b", baja: "#00ff9d" };

const uid = () =>
  Date.now().toString(36) + Math.random().toString(36).slice(2, 7);
const nowISO = () => new Date().toISOString();

function defaultData() {
  const pid = uid();
  return {
    projects: [
      {
        id: pid,
        name: "Proyecto Principal",
        desc: "Proyecto de gestión central",
        color: "#00d4ff",
        createdAt: nowISO(),
      },
    ],
    tasks: { [pid]: [] },
    currentProject: pid,
  };
}

function loadDB() {
  try {
    const d = JSON.parse(localStorage.getItem(LS_KEY) || "null");
    if (d && Array.isArray(d.projects) && d.projects.length) {
      if (!d.tasks) d.tasks = {};
      return d;
    }
  } catch {
    /* datos corruptos → tablero nuevo */
  }
  return defaultData();
}

const saveDB = (db) => localStorage.setItem(LS_KEY, JSON.stringify(db));

function formatAI(text) {
  return String(text || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(
      /^#+\s*(.+)$/gm,
      '<strong style="color:var(--t-accent)">$1</strong>',
    )
    .replace(/^(\d+\.\s)/gm, '<span style="color:var(--t-accent)">$1</span>')
    .replace(/^[-•]\s/gm, '<span style="color:var(--t-text-muted)">▸ </span>')
    .replace(/\n/g, "<br/>");
}

const inputStyle = {
  width: "100%",
  padding: "7px 10px",
  borderRadius: 6,
  border: "1px solid var(--t-border)",
  background: "var(--t-bg-surface)",
  color: "var(--t-text)",
  fontSize: ".8rem",
  fontFamily: "inherit",
};

const btnStyle = (variant) => ({
  padding: "6px 14px",
  border: "none",
  borderRadius: 6,
  cursor: "pointer",
  fontSize: ".78rem",
  fontWeight: 600,
  fontFamily: "inherit",
  ...(variant === "prim"
    ? { background: "var(--t-accent)", color: "#07101d" }
    : {
        background: "transparent",
        border: "1px solid var(--t-border)",
        color: "var(--t-text-muted)",
      }),
});

export default function ProyectosModule() {
  const [db, setDb] = useState(loadDB);
  const [projId, setProjId] = useState(() => loadDB().currentProject);
  const [agents, setAgents] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [taskModal, setTaskModal] = useState(null); // {task|null, defaultStatus}
  const [projModal, setProjModal] = useState(false);
  const [aiAgent, setAiAgent] = useState("");
  const [aiExtra, setAiExtra] = useState("");
  const [aiLoading, setAiLoading] = useState(false);
  const [toast, setToast] = useState("");
  const dragSrc = useRef(null);
  const toastTimer = useRef(null);

  const tasks = db.tasks[projId] || [];
  const selected = tasks.find((t) => t.id === selectedId) || null;

  const notify = useCallback((msg) => {
    setToast(msg);
    clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(""), 2500);
  }, []);

  const persist = useCallback((next) => {
    setDb(next);
    saveDB(next);
  }, []);

  useEffect(() => {
    fetch(`${API_BASE}/agentes`)
      .then((r) => r.json())
      .then((d) => setAgents(d.agentes || []))
      .catch(() => setAgents([]));
    return () => clearTimeout(toastTimer.current);
  }, []);

  const setTasks = (arr) =>
    persist({ ...db, tasks: { ...db.tasks, [projId]: arr } });

  const upsertTask = (t) => {
    const arr = tasks.some((x) => x.id === t.id)
      ? tasks.map((x) => (x.id === t.id ? t : x))
      : [...tasks, t];
    setTasks(arr);
  };

  const removeTask = (id) => {
    if (!window.confirm("¿Eliminar esta tarea?")) return;
    setTasks(tasks.filter((t) => t.id !== id));
    if (selectedId === id) setSelectedId(null);
    notify("Tarea eliminada");
  };

  const onDrop = (e, status) => {
    e.preventDefault();
    e.currentTarget.style.background = "";
    const id = dragSrc.current;
    dragSrc.current = null;
    const t = tasks.find((x) => x.id === id);
    if (!t || t.status === status) return;
    upsertTask({ ...t, status, updatedAt: nowISO() });
  };

  const runAI = async () => {
    if (!selected || !aiAgent) {
      notify("Selecciona un agente para el análisis");
      return;
    }
    setAiLoading(true);
    const prompt = `TAREA: ${selected.title}
DESCRIPCIÓN: ${selected.desc || "Sin descripción"}
PRIORIDAD: ${selected.priority}
ESTADO: ${selected.status}
ETIQUETAS: ${(selected.tags || []).join(", ") || "ninguna"}
${aiExtra.trim() ? "\nCONTEXTO ADICIONAL:\n" + aiExtra.trim() : ""}

Por favor analiza esta tarea y provee:
1. Evaluación del alcance y complejidad
2. Riesgos potenciales identificados
3. Recomendaciones de acción concretas
4. Próximos pasos sugeridos
5. Estimación de tiempo (si aplica)`;
    try {
      const r = await fetch(`${API_BASE}/ejecutar/${aiAgent}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tarea: prompt }),
      });
      const d = await r.json();
      const text =
        d.resultado ||
        d.respuesta ||
        d.output ||
        d.result ||
        JSON.stringify(d, null, 2);
      upsertTask({ ...selected, aiAnalysis: text, aiAgentId: aiAgent });
      notify("Análisis completado ✓");
    } catch {
      notify(
        "Error al conectar con el agente. Verifica que el backend esté activo.",
      );
    } finally {
      setAiLoading(false);
    }
  };

  const stats = {
    total: tasks.length,
    done: tasks.filter((t) => t.status === "completado").length,
    late: tasks.filter(
      (t) =>
        t.dueDate &&
        t.status !== "completado" &&
        new Date(t.dueDate + "T23:59:59").getTime() < Date.now(),
    ).length,
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "0.8rem" }}>
      {/* ── Header: proyecto + stats + acciones ── */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 10,
          flexWrap: "wrap",
          padding: "10px 14px",
          background: "var(--t-bg-surface)",
          border: "1px solid var(--t-border)",
          borderRadius: 10,
        }}
      >
        <span
          style={{
            fontSize: "1rem",
            fontWeight: 700,
            color: "var(--t-accent)",
          }}
        >
          Proyectos{" "}
          <span
            style={{
              fontSize: ".7rem",
              color: "var(--t-text-muted)",
              fontWeight: 400,
            }}
          >
            Kanban + IA
          </span>
        </span>
        <select
          value={projId}
          onChange={(e) => {
            setProjId(e.target.value);
            setSelectedId(null);
            persist({ ...db, currentProject: e.target.value });
          }}
          style={{
            ...inputStyle,
            width: "auto",
            minWidth: 160,
            cursor: "pointer",
          }}
        >
          {db.projects.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
        <button style={btnStyle("sec")} onClick={() => setProjModal(true)}>
          + Proyecto
        </button>
        <div style={{ flex: 1 }} />
        {[
          ["Total", stats.total, "var(--t-text)"],
          ["Completadas", stats.done, "#00ff9d"],
          ["Atrasadas", stats.late, "#ff2d55"],
        ].map(([l, v, c]) => (
          <div key={l} style={{ textAlign: "center", minWidth: 62 }}>
            <div style={{ fontSize: "1.1rem", fontWeight: 700, color: c }}>
              {v}
            </div>
            <div
              style={{
                fontSize: ".6rem",
                color: "var(--t-text-muted)",
                textTransform: "uppercase",
                letterSpacing: ".04em",
              }}
            >
              {l}
            </div>
          </div>
        ))}
        <button
          style={btnStyle("prim")}
          onClick={() =>
            setTaskModal({ task: null, defaultStatus: "pendiente" })
          }
        >
          <Plus size={13} style={{ verticalAlign: -2 }} /> Nueva tarea
        </button>
      </div>

      <div style={{ display: "flex", gap: 12, alignItems: "flex-start" }}>
        {/* ── Tablero ── */}
        <div
          style={{
            display: "flex",
            gap: 12,
            flex: 1,
            overflowX: "auto",
            alignItems: "flex-start",
          }}
        >
          {COLS.map((col) => {
            const colTasks = tasks.filter((t) => t.status === col.id);
            return (
              <div
                key={col.id}
                style={{
                  minWidth: 230,
                  flex: 1,
                  background: "var(--t-bg-surface)",
                  border: "1px solid var(--t-border)",
                  borderRadius: 10,
                  display: "flex",
                  flexDirection: "column",
                }}
                onDragOver={(e) => {
                  e.preventDefault();
                  e.currentTarget.style.background = "rgba(0,212,255,.05)";
                }}
                onDragLeave={(e) => {
                  e.currentTarget.style.background = "";
                }}
                onDrop={(e) => onDrop(e, col.id)}
              >
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 8,
                    padding: "9px 12px",
                    borderBottom: "1px solid var(--t-border)",
                  }}
                >
                  <span
                    style={{
                      width: 8,
                      height: 8,
                      borderRadius: "50%",
                      background: col.color,
                    }}
                  />
                  <span style={{ fontWeight: 600, fontSize: ".8rem", flex: 1 }}>
                    {col.label}
                  </span>
                  <span
                    style={{
                      background: "rgba(255,255,255,.06)",
                      borderRadius: 10,
                      padding: "1px 7px",
                      fontSize: ".65rem",
                      color: "var(--t-text-muted)",
                    }}
                  >
                    {colTasks.length}
                  </span>
                </div>
                <div
                  style={{
                    padding: 8,
                    display: "flex",
                    flexDirection: "column",
                    gap: 7,
                    minHeight: 80,
                  }}
                >
                  {colTasks.length === 0 && (
                    <div
                      style={{
                        textAlign: "center",
                        fontSize: ".7rem",
                        padding: "14px 4px",
                        color: "var(--t-text-muted)",
                      }}
                    >
                      Sin tareas — arrastra aquí o crea una nueva
                    </div>
                  )}
                  {colTasks.map((t) => {
                    const agent = agents.find((a) => a.id === t.agentId);
                    let due = null;
                    if (t.dueDate) {
                      const diff = Math.ceil(
                        (new Date(t.dueDate + "T23:59:59").getTime() -
                          Date.now()) /
                          86400000,
                      );
                      due = {
                        lbl:
                          diff < 0
                            ? `Venció hace ${-diff}d`
                            : diff === 0
                              ? "Vence hoy"
                              : `${diff}d restantes`,
                        color:
                          diff < 0
                            ? "#ff2d55"
                            : diff <= 2
                              ? "#f59e0b"
                              : "var(--t-text-muted)",
                      };
                    }
                    return (
                      <div
                        key={t.id}
                        draggable
                        onDragStart={() => {
                          dragSrc.current = t.id;
                        }}
                        onClick={() => setSelectedId(t.id)}
                        role="button"
                        tabIndex={0}
                        onKeyDown={(e) => {
                          if (e.key === "Enter" || e.key === " ") {
                            e.preventDefault();
                            setSelectedId(t.id);
                          }
                        }}
                        style={{
                          position: "relative",
                          padding: "9px 10px",
                          borderRadius: 8,
                          cursor: "grab",
                          background: "rgba(255,255,255,.03)",
                          border: `1px solid ${selectedId === t.id ? "var(--t-accent)" : "var(--t-border)"}`,
                        }}
                      >
                        <div style={{ display: "flex", gap: 8 }}>
                          <div
                            style={{
                              width: 3,
                              borderRadius: 2,
                              flexShrink: 0,
                              background:
                                PRIO_COLORS[t.priority] ||
                                "var(--t-text-muted)",
                            }}
                          />
                          <div style={{ minWidth: 0 }}>
                            <div
                              style={{
                                fontSize: ".78rem",
                                fontWeight: 600,
                                lineHeight: 1.3,
                              }}
                            >
                              {t.title}
                            </div>
                            {t.desc && (
                              <div
                                style={{
                                  fontSize: ".68rem",
                                  color: "var(--t-text-muted)",
                                  marginTop: 3,
                                  display: "-webkit-box",
                                  WebkitLineClamp: 2,
                                  WebkitBoxOrient: "vertical",
                                  overflow: "hidden",
                                }}
                              >
                                {t.desc}
                              </div>
                            )}
                          </div>
                        </div>
                        {(t.tags || []).length > 0 && (
                          <div
                            style={{
                              display: "flex",
                              gap: 4,
                              flexWrap: "wrap",
                              marginTop: 6,
                            }}
                          >
                            {t.tags.map((g) => (
                              <span
                                key={g}
                                style={{
                                  fontSize: ".6rem",
                                  padding: "1px 7px",
                                  borderRadius: 8,
                                  background: "rgba(0,212,255,.08)",
                                  color: "var(--t-accent)",
                                }}
                              >
                                {g}
                              </span>
                            ))}
                          </div>
                        )}
                        <div
                          style={{
                            display: "flex",
                            justifyContent: "space-between",
                            alignItems: "center",
                            marginTop: 6,
                            fontSize: ".62rem",
                          }}
                        >
                          <span style={{ color: "var(--t-text-muted)" }}>
                            {agent ? (
                              <>
                                <Bot size={10} style={{ verticalAlign: -1 }} />{" "}
                                {agent.nombre || agent.id}
                              </>
                            ) : (
                              ""
                            )}
                          </span>
                          {due && (
                            <span style={{ color: due.color }}>
                              <Calendar
                                size={10}
                                style={{ verticalAlign: -1 }}
                              />{" "}
                              {due.lbl}
                            </span>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
                <div
                  style={{
                    padding: "8px 12px",
                    borderTop: "1px solid var(--t-border)",
                  }}
                >
                  <button
                    onClick={() =>
                      setTaskModal({ task: null, defaultStatus: col.id })
                    }
                    style={{
                      width: "100%",
                      padding: 6,
                      borderRadius: 6,
                      cursor: "pointer",
                      border: "1px dashed var(--t-border)",
                      background: "transparent",
                      color: "var(--t-text-muted)",
                      fontSize: ".72rem",
                      fontFamily: "inherit",
                    }}
                  >
                    + Agregar tarea
                  </button>
                </div>
              </div>
            );
          })}
        </div>

        {/* ── Panel IA ── */}
        {selected && (
          <div
            style={{
              width: 320,
              flexShrink: 0,
              background: "var(--t-bg-surface)",
              border: "1px solid var(--t-border)",
              borderRadius: 10,
              padding: 12,
            }}
          >
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
              }}
            >
              <span
                style={{
                  fontWeight: 700,
                  fontSize: ".82rem",
                  color: "var(--t-accent)",
                }}
              >
                ✦ Análisis IA
              </span>
              <button
                onClick={() => setSelectedId(null)}
                style={{
                  background: "none",
                  border: "none",
                  cursor: "pointer",
                  color: "var(--t-text-muted)",
                }}
              >
                <X size={15} />
              </button>
            </div>
            <div
              style={{
                margin: "10px 0",
                padding: 10,
                borderRadius: 8,
                border: "1px solid var(--t-border)",
              }}
            >
              <div style={{ fontSize: ".8rem", fontWeight: 600 }}>
                {selected.title}
              </div>
              <div
                style={{
                  display: "flex",
                  gap: 6,
                  marginTop: 5,
                  alignItems: "center",
                }}
              >
                <span
                  style={{
                    fontSize: ".58rem",
                    fontWeight: 700,
                    padding: "2px 7px",
                    borderRadius: 4,
                    background: PRIO_COLORS[selected.priority],
                    color: "#07101d",
                  }}
                >
                  {selected.priority.toUpperCase()}
                </span>
                <span
                  style={{ fontSize: ".65rem", color: "var(--t-text-muted)" }}
                >
                  {COLS.find((c) => c.id === selected.status)?.label ||
                    selected.status}
                </span>
              </div>
              <div style={{ display: "flex", gap: 6, marginTop: 8 }}>
                <button
                  style={btnStyle("sec")}
                  onClick={() => setTaskModal({ task: selected })}
                >
                  <Edit2 size={11} style={{ verticalAlign: -1 }} /> Editar
                </button>
                <button
                  style={{
                    ...btnStyle("sec"),
                    color: "#ff2d55",
                    borderColor: "rgba(255,45,85,.3)",
                  }}
                  onClick={() => removeTask(selected.id)}
                >
                  <Trash2 size={11} style={{ verticalAlign: -1 }} /> Eliminar
                </button>
              </div>
            </div>
            <select
              value={aiAgent}
              onChange={(e) => setAiAgent(e.target.value)}
              style={inputStyle}
            >
              <option value="">— Seleccionar agente —</option>
              {agents.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.nombre || a.id}
                </option>
              ))}
            </select>
            <textarea
              value={aiExtra}
              onChange={(e) => setAiExtra(e.target.value)}
              placeholder="Contexto adicional (opcional)…"
              rows={2}
              style={{ ...inputStyle, marginTop: 8, resize: "vertical" }}
            />
            <button
              onClick={runAI}
              disabled={aiLoading || !aiAgent}
              style={{
                ...btnStyle("prim"),
                width: "100%",
                marginTop: 8,
                opacity: aiLoading || !aiAgent ? 0.55 : 1,
              }}
            >
              {aiLoading ? "Analizando con IA…" : "▷ Analizar"}
            </button>
            <div
              style={{
                marginTop: 10,
                fontSize: ".72rem",
                lineHeight: 1.5,
                maxHeight: 320,
                overflowY: "auto",
                color: "var(--t-text)",
              }}
            >
              {selected.aiAnalysis ? (
                <div
                  dangerouslySetInnerHTML={{
                    __html: formatAI(selected.aiAnalysis),
                  }}
                />
              ) : (
                <span style={{ color: "var(--t-text-muted)" }}>
                  Sin análisis aún. Selecciona un agente y pulsa Analizar.
                </span>
              )}
            </div>
          </div>
        )}
      </div>

      {/* ── Modal de tarea ── */}
      {taskModal && (
        <TaskModal
          task={taskModal.task}
          defaultStatus={taskModal.defaultStatus || "pendiente"}
          agents={agents}
          onCancel={() => setTaskModal(null)}
          onSave={(t) => {
            upsertTask(t);
            setTaskModal(null);
            notify(taskModal.task ? "Tarea actualizada ✓" : "Tarea creada ✓");
          }}
        />
      )}

      {/* ── Modal de proyecto ── */}
      {projModal && (
        <ProjModal
          onCancel={() => setProjModal(false)}
          onSave={({ name, desc }) => {
            const p = {
              id: uid(),
              name,
              desc,
              color: "#00d4ff",
              createdAt: nowISO(),
            };
            persist({
              ...db,
              projects: [...db.projects, p],
              tasks: { ...db.tasks, [p.id]: [] },
              currentProject: p.id,
            });
            setProjId(p.id);
            setProjModal(false);
            notify("Proyecto creado ✓");
          }}
        />
      )}

      {/* ── Toast ── */}
      {toast && (
        <div
          style={{
            position: "fixed",
            bottom: 24,
            right: 24,
            zIndex: 60,
            padding: "10px 16px",
            borderRadius: 8,
            background: "var(--t-bg-surface)",
            color: "var(--t-text)",
            border: "1px solid var(--t-accent)",
            fontSize: ".78rem",
            boxShadow: "0 4px 24px rgba(0,0,0,.45)",
          }}
        >
          {toast}
        </div>
      )}
    </div>
  );
}

function Overlay({ children, onClose }) {
  return (
    <div
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
      role="presentation"
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 50,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: "rgba(0,0,0,.6)",
        backdropFilter: "blur(3px)",
      }}
    >
      <div
        style={{
          width: 440,
          maxWidth: "92vw",
          maxHeight: "88vh",
          overflowY: "auto",
          background: "var(--t-bg-surface)",
          border: "1px solid var(--t-border)",
          borderRadius: 12,
          padding: 18,
        }}
      >
        {children}
      </div>
    </div>
  );
}

function TaskModal({ task, defaultStatus, agents, onCancel, onSave }) {
  const [title, setTitle] = useState(task?.title || "");
  const [desc, setDesc] = useState(task?.desc || "");
  const [status, setStatus] = useState(task?.status || defaultStatus);
  const [prio, setPrio] = useState(task?.priority || "media");
  const [agentId, setAgent] = useState(task?.agentId || "");
  const [owner, setOwner] = useState(task?.owner || "");
  const [due, setDue] = useState(task?.dueDate || "");
  const [tags, setTags] = useState(task?.tags ? [...task.tags] : []);
  const [tagInput, setTagInput] = useState("");
  const titleRef = useRef(null);

  useEffect(() => {
    titleRef.current?.focus();
  }, []);

  const addTag = () => {
    const val = tagInput
      .trim()
      .toLowerCase()
      .replace(/[^a-záéíóúüñ0-9-]/gi, "")
      .slice(0, 20);
    if (val && !tags.includes(val)) setTags([...tags, val]);
    setTagInput("");
  };

  const save = () => {
    if (!title.trim()) return;
    onSave({
      id: task?.id || uid(),
      projectId: task?.projectId,
      title: title.trim(),
      desc: desc.trim(),
      status,
      priority: prio,
      agentId,
      owner: owner.trim(),
      dueDate: due,
      tags,
      aiAnalysis: task?.aiAnalysis || null,
      createdAt: task?.createdAt || nowISO(),
      updatedAt: nowISO(),
    });
  };

  const label = {
    fontSize: ".68rem",
    color: "var(--t-text-muted)",
    margin: "10px 0 4px",
    display: "block",
  };

  return (
    <Overlay onClose={onCancel}>
      <div style={{ fontWeight: 700, fontSize: ".92rem", marginBottom: 4 }}>
        {task ? "Editar Tarea" : "Nueva Tarea"}
      </div>
      <label style={label} htmlFor="task-title-input">
        Título *
      </label>
      <input
        id="task-title-input"
        ref={titleRef}
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") save();
        }}
        style={inputStyle}
      />
      <label style={label} htmlFor="task-desc-input">
        Descripción
      </label>
      <textarea
        id="task-desc-input"
        value={desc}
        onChange={(e) => setDesc(e.target.value)}
        rows={3}
        style={{ ...inputStyle, resize: "vertical" }}
      />
      <div style={{ display: "flex", gap: 10 }}>
        <div style={{ flex: 1 }}>
          <label style={label} htmlFor="task-status-select">
            Estado
          </label>
          <select
            id="task-status-select"
            value={status}
            onChange={(e) => setStatus(e.target.value)}
            style={inputStyle}
          >
            {COLS.map((c) => (
              <option key={c.id} value={c.id}>
                {c.label}
              </option>
            ))}
          </select>
        </div>
        <div style={{ flex: 1 }}>
          <label style={label} htmlFor="task-due-input">
            Fecha límite
          </label>
          <input
            id="task-due-input"
            type="date"
            value={due}
            onChange={(e) => setDue(e.target.value)}
            style={inputStyle}
          />
        </div>
      </div>
      <span style={label} id="task-prio-label">
        Prioridad
      </span>
      <div
        role="group"
        aria-labelledby="task-prio-label"
        style={{ display: "flex", gap: 6 }}
      >
        {["alta", "media", "baja"].map((p) => (
          <button
            key={p}
            onClick={() => setPrio(p)}
            style={{
              ...btnStyle("sec"),
              flex: 1,
              ...(prio === p
                ? {
                    background: PRIO_COLORS[p],
                    color: "#07101d",
                    borderColor: PRIO_COLORS[p],
                  }
                : {}),
            }}
          >
            {p.charAt(0).toUpperCase() + p.slice(1)}
          </button>
        ))}
      </div>
      <div style={{ display: "flex", gap: 10 }}>
        <div style={{ flex: 1 }}>
          <label style={label} htmlFor="task-agent-select">
            Agente IA
          </label>
          <select
            id="task-agent-select"
            value={agentId}
            onChange={(e) => setAgent(e.target.value)}
            style={inputStyle}
          >
            <option value="">Sin asignar</option>
            {agents.map((a) => (
              <option key={a.id} value={a.id}>
                {a.nombre || a.id}
              </option>
            ))}
          </select>
        </div>
        <div style={{ flex: 1 }}>
          <label style={label} htmlFor="task-owner-input">
            Responsable
          </label>
          <input
            id="task-owner-input"
            value={owner}
            onChange={(e) => setOwner(e.target.value)}
            style={inputStyle}
          />
        </div>
      </div>
      <span style={label} id="task-tags-label">
        Etiquetas (Enter o coma para añadir)
      </span>
      <div
        aria-labelledby="task-tags-label"
        role="group"
        style={{
          display: "flex",
          gap: 4,
          flexWrap: "wrap",
          alignItems: "center",
        }}
      >
        {tags.map((g) => (
          <span
            key={g}
            style={{
              fontSize: ".65rem",
              padding: "2px 8px",
              borderRadius: 8,
              background: "rgba(0,212,255,.08)",
              color: "var(--t-accent)",
            }}
          >
            {g}{" "}
            <button
              onClick={() => setTags(tags.filter((x) => x !== g))}
              style={{
                background: "none",
                border: "none",
                cursor: "pointer",
                color: "inherit",
                padding: 0,
              }}
            >
              ×
            </button>
          </span>
        ))}
        <input
          value={tagInput}
          onChange={(e) => setTagInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === ",") {
              e.preventDefault();
              addTag();
            }
          }}
          placeholder="tag…"
          style={{ ...inputStyle, width: 110 }}
        />
      </div>
      <div
        style={{
          display: "flex",
          gap: 8,
          justifyContent: "flex-end",
          marginTop: 16,
        }}
      >
        <button style={btnStyle("sec")} onClick={onCancel}>
          Cancelar
        </button>
        <button
          style={{ ...btnStyle("prim"), opacity: title.trim() ? 1 : 0.5 }}
          onClick={save}
        >
          Guardar
        </button>
      </div>
    </Overlay>
  );
}

function ProjModal({ onCancel, onSave }) {
  const [name, setName] = useState("");
  const [desc, setDesc] = useState("");
  const nameRef = useRef(null);

  useEffect(() => {
    nameRef.current?.focus();
  }, []);

  return (
    <Overlay onClose={onCancel}>
      <div style={{ fontWeight: 700, fontSize: ".92rem", marginBottom: 10 }}>
        Nuevo Proyecto
      </div>
      <input
        ref={nameRef}
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder="Nombre *"
        style={inputStyle}
      />
      <textarea
        value={desc}
        onChange={(e) => setDesc(e.target.value)}
        rows={2}
        placeholder="Descripción"
        style={{ ...inputStyle, marginTop: 8, resize: "vertical" }}
      />
      <div
        style={{
          display: "flex",
          gap: 8,
          justifyContent: "flex-end",
          marginTop: 14,
        }}
      >
        <button style={btnStyle("sec")} onClick={onCancel}>
          Cancelar
        </button>
        <button
          style={{ ...btnStyle("prim"), opacity: name.trim() ? 1 : 0.5 }}
          onClick={() =>
            name.trim() && onSave({ name: name.trim(), desc: desc.trim() })
          }
        >
          Crear
        </button>
      </div>
    </Overlay>
  );
}
