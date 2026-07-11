/**
 * ChatPanel — interfaz de chat con agentes con Tool Calling visible.
 *
 * Eventos SSE que maneja:
 *   inicio      → identifica al agente respondiendo
 *   tool_call   → muestra indicador "🔧 Consultando <herramienta>..."
 *   tool_result → actualiza indicador con preview del resultado
 *   chunk       → agrega texto en tiempo real
 *   error       → muestra mensaje de error
 *   fin         → finaliza el estado streaming
 */
import { useState, useRef, useEffect, useCallback } from "react";
import { API_BASE } from "../../services/agent.service";

// ── Helpers ────────────────────────────────────────────────────────────────────

function genId() {
  return Math.random().toString(36).slice(2, 9);
}

const TOOL_LABELS = {
  consultar_indicadores_chile: "Banco Central de Chile",
  calcular:                    "Calculadora",
  leer_archivo:                "Lector de archivos",
  listar_archivos:             "Explorador de archivos",
  obtener_energia_chile:       "Mercado eléctrico",
  obtener_partidos:            "Estadísticas de fútbol",
  calcular_financiero:         "Motor financiero",
  consultar_macro_chile:       "Indicadores macroeconómicos",
  buscar_empresa_cmf:          "CMF Chile",
};

function toolLabel(nombre) {
  return TOOL_LABELS[nombre] ?? nombre.replace(/_/g, " ");
}

// ── Subcomponentes ─────────────────────────────────────────────────────────────

function ToolActivityBadge({ calls }) {
  if (!calls || calls.length === 0) return null;
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 8 }}>
      {calls.map((c, i) => (
        <span
          key={i}
          title={c.preview ?? ""}
          style={{
            display:      "inline-flex",
            alignItems:   "center",
            gap:          5,
            fontSize:     "0.72rem",
            padding:      "3px 10px",
            borderRadius: 20,
            border:       "1px solid rgba(0,212,255,0.30)",
            background:   "rgba(0,212,255,0.07)",
            color:        "var(--t-accent)",
            fontWeight:   500,
          }}
        >
          {c.done ? "✓" : "⏳"} {toolLabel(c.nombre)}
        </span>
      ))}
    </div>
  );
}

function Message({ msg, onDownloadPdf, pdfLoading }) {
  const isUser   = msg.rol === "usuario";
  const isError  = msg.rol === "error";
  const isSystem = msg.rol === "sistema";

  if (isSystem) {
    return (
      <div style={{ textAlign: "center", margin: "8px 0" }}>
        <span style={{
          fontSize:   "0.72rem",
          color:      "var(--t-text-muted)",
          background: "var(--t-bg-card)",
          padding:    "3px 12px",
          borderRadius: 20,
          border:     "1px solid var(--t-border)",
        }}>
          {msg.texto}
        </span>
      </div>
    );
  }

  return (
    <div style={{
      display:       "flex",
      justifyContent: isUser ? "flex-end" : "flex-start",
      marginBottom:  12,
    }}>
      <div style={{ maxWidth: "78%", minWidth: 60 }}>
        {/* Header del agente */}
        {!isUser && msg.agente_nombre && (
          <div style={{
            fontSize:    "0.70rem",
            color:       "var(--t-accent)",
            marginBottom: 4,
            fontWeight:  600,
            letterSpacing: ".03em",
          }}>
            {msg.agente_nombre}
            {msg.agente_area && (
              <span style={{ color: "var(--t-text-muted)", fontWeight: 400 }}>
                {" · "}{msg.agente_area}
              </span>
            )}
          </div>
        )}

        {/* Badges de herramientas */}
        {!isUser && <ToolActivityBadge calls={msg.toolCalls ?? []} />}

        {/* Burbuja de texto */}
        <div style={{
          padding:      "10px 14px",
          borderRadius: isUser ? "16px 16px 4px 16px" : "4px 16px 16px 16px",
          background:   isUser
            ? "linear-gradient(135deg, var(--t-accent) 0%, #006fa8 100%)"
            : isError
            ? "rgba(239,68,68,0.12)"
            : "var(--t-bg-card)",
          border:       isUser
            ? "none"
            : isError
            ? "1px solid rgba(239,68,68,0.3)"
            : "1px solid var(--t-border)",
          color:        isUser ? "#fff" : "var(--t-text)",
          fontSize:     "0.85rem",
          lineHeight:   1.55,
          whiteSpace:   "pre-wrap",
          wordBreak:    "break-word",
          position:     "relative",
        }}>
          {msg.texto || (msg._streaming && (
            <span style={{ opacity: 0.5 }}>…</span>
          ))}
          {msg._streaming && (
            <span style={{
              display:      "inline-block",
              width:        8,
              height:       12,
              background:   "var(--t-accent)",
              marginLeft:   2,
              borderRadius: 1,
              animation:    "blink .7s step-end infinite",
              verticalAlign: "middle",
              opacity:      0.8,
            }} />
          )}
        </div>

        {/* Timestamp + botón PDF */}
        {msg.ts && !msg._streaming && (
          <div style={{
            display:    "flex",
            alignItems: "center",
            gap:        8,
            marginTop:  3,
            justifyContent: isUser ? "flex-end" : "flex-start",
          }}>
            <span style={{ fontSize: "0.65rem", color: "var(--t-text-muted)" }}>
              {msg.ts}
            </span>
            {!isUser && !isError && onDownloadPdf && msg.texto && (
              <button
                onClick={() => onDownloadPdf(msg)}
                disabled={pdfLoading === msg.id}
                title="Descargar esta respuesta como PDF"
                style={{
                  fontSize:     "0.63rem",
                  padding:      "1px 7px",
                  borderRadius: 6,
                  border:       "1px solid rgba(0,212,255,0.28)",
                  background:   pdfLoading === msg.id
                    ? "rgba(0,212,255,0.05)"
                    : "rgba(0,212,255,0.08)",
                  color:        "var(--t-accent)",
                  cursor:       pdfLoading === msg.id ? "not-allowed" : "pointer",
                  fontFamily:   "inherit",
                  fontWeight:   600,
                  transition:   "all .15s",
                  lineHeight:   1.6,
                }}
              >
                {pdfLoading === msg.id ? "…" : "↓ PDF"}
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function AgentSelector({ agentes, value, onChange, disabled }) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      disabled={disabled}
      style={{
        background:   "var(--t-bg-card)",
        border:       "1px solid var(--t-border)",
        borderRadius: 8,
        color:        "var(--t-text)",
        padding:      "6px 10px",
        fontSize:     "0.82rem",
        minWidth:     160,
        cursor:       disabled ? "not-allowed" : "pointer",
        outline:      "none",
        fontFamily:   "inherit",
      }}
    >
      <option value="auto">Auto (más relevante)</option>
      {agentes.map((a) => (
        <option key={a.id ?? a.nombre} value={a.id ?? a.nombre}>
          {a.nombre} · {a.area}
        </option>
      ))}
    </select>
  );
}

// ── Componente principal ───────────────────────────────────────────────────────

export default function ChatPanel({ initialFiles = [], onFilesUsed }) {
  const [mensajes,   setMensajes]   = useState([]);
  const [input,      setInput]      = useState("");
  const [streaming,  setStreaming]  = useState(false);
  const [agenteId,   setAgenteId]   = useState("auto");
  const [agentes,    setAgentes]    = useState([]);
  const [sesionId]                  = useState(() => genId());
  const [pdfLoading, setPdfLoading] = useState(null);

  // Archivo adjunto activo
  const archivoActivo = initialFiles?.[0] ?? null;

  const bottomRef  = useRef(null);
  const inputRef   = useRef(null);
  const abortRef   = useRef(null);

  // ── Generar y descargar PDF de un mensaje ────────────────────────────────────
  const downloadPdf = useCallback(async (msg) => {
    setPdfLoading(msg.id);
    try {
      const fecha = new Date().toLocaleDateString("es-CL");
      const payload = {
        reporte: {
          resumen:   msg.texto,
          kpis:      {},
          tabla:     [],
          evidencia: {},
        },
        titulo:         `Informe ${msg.agente_nombre || "Agente"} - ${fecha}`,
        subtitulo:      msg.agente_area || "AgentDesk ICI",
        nombre_agente:  msg.agente_nombre || "Agente",
        empresa:        "AgentDesk ICI",
        archivo_nombre: "",
      };
      const token = sessionStorage.getItem("agentdesk-jwt-token") || "";
      const resp = await fetch(`${API_BASE}/generar-pdf`, {
        method:  "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify(payload),
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const blob = await resp.blob();
      const url  = URL.createObjectURL(blob);
      const a    = document.createElement("a");
      a.href     = url;
      a.download = resp.headers.get("Content-Disposition")
        ?.match(/filename="?([^"]+)"?/)?.[1]
        ?? `informe_${(msg.agente_nombre || "agente").replace(/\s+/g, "_")}.pdf`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      console.error("Error al generar PDF:", err);
    } finally {
      setPdfLoading(null);
    }
  }, []);

  // ── Cargar lista de agentes ──────────────────────────────────────────────────
  useEffect(() => {
    fetch(`${API_BASE}/agentes`, {
      headers: { Authorization: `Bearer ${sessionStorage.getItem("agentdesk-jwt-token") || ""}` },
    })
      .then((r) => r.ok ? r.json() : [])
      .then((data) => setAgentes(Array.isArray(data) ? data : []))
      .catch(() => {});
  }, []);

  // ── Scroll al último mensaje ─────────────────────────────────────────────────
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [mensajes]);

  // ── Notificar archivo usado ──────────────────────────────────────────────────
  useEffect(() => {
    if (archivoActivo) {
      setMensajes((prev) => [
        ...prev,
        {
          id:    genId(),
          rol:   "sistema",
          texto: `📎 Archivo adjunto: ${archivoActivo.nombre_original ?? archivoActivo.archivo_id}`,
        },
      ]);
    }
  }, [archivoActivo?.archivo_id]);

  // ── Enviar mensaje ───────────────────────────────────────────────────────────
  const enviar = useCallback(async () => {
    const texto = input.trim();
    if (!texto || streaming) return;

    setInput("");
    setStreaming(true);

    const msgUsuario = {
      id:   genId(),
      rol:  "usuario",
      texto,
      ts:   new Date().toLocaleTimeString("es-CL", { hour: "2-digit", minute: "2-digit" }),
    };

    const streamId = genId();
    const msgAgente = {
      id:          genId(),
      _streamId:   streamId,
      rol:         "agente",
      texto:       "",
      agente_nombre: "",
      agente_area:   "",
      toolCalls:   [],
      _streaming:  true,
      ts:          null,
    };

    setMensajes((prev) => [...prev, msgUsuario, msgAgente]);
    if (archivoActivo) onFilesUsed?.();

    const payload = {
      mensaje:    texto,
      agente_id:  agenteId === "auto" ? null : agenteId,
      archivo_id: archivoActivo?.archivo_id ?? null,
      sesion_id:  sesionId,
    };

    const token = sessionStorage.getItem("agentdesk-jwt-token") || "";

    abortRef.current = new AbortController();

    try {
      const resp = await fetch(`${API_BASE}/chat/stream`, {
        method:  "POST",
        headers: {
          "Content-Type":  "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body:   JSON.stringify(payload),
        signal: abortRef.current.signal,
      });

      if (!resp.ok) {
        throw new Error(`HTTP ${resp.status}`);
      }

      const reader  = resp.body.getReader();
      const decoder = new TextDecoder();
      let   buffer  = "";

      // eslint-disable-next-line no-constant-condition
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const raw = line.slice(6).trim();
          if (raw === "[DONE]") break;

          let ev;
          try { ev = JSON.parse(raw); } catch { continue; }

          switch (ev.tipo) {
            case "inicio":
              setMensajes((prev) =>
                prev.map((m) =>
                  m._streamId === streamId
                    ? { ...m, agente_nombre: ev.agente_nombre, agente_area: ev.agente_area }
                    : m
                )
              );
              break;

            case "tool_call":
              setMensajes((prev) =>
                prev.map((m) =>
                  m._streamId === streamId
                    ? {
                        ...m,
                        toolCalls: [
                          ...m.toolCalls,
                          { nombre: ev.herramienta, done: false, preview: null },
                        ],
                      }
                    : m
                )
              );
              break;

            case "tool_result":
              setMensajes((prev) =>
                prev.map((m) => {
                  if (m._streamId !== streamId) return m;
                  const calls = m.toolCalls.map((c) =>
                    c.nombre === ev.herramienta && !c.done
                      ? { ...c, done: true, preview: ev.preview }
                      : c
                  );
                  return { ...m, toolCalls: calls };
                })
              );
              break;

            case "chunk":
              setMensajes((prev) =>
                prev.map((m) =>
                  m._streamId === streamId
                    ? { ...m, texto: m.texto + ev.chunk }
                    : m
                )
              );
              break;

            case "error":
              setMensajes((prev) =>
                prev.map((m) =>
                  m._streamId === streamId
                    ? { ...m, rol: "error", texto: ev.error, _streaming: false }
                    : m
                )
              );
              break;

            case "fin":
              setMensajes((prev) =>
                prev.map((m) =>
                  m._streamId === streamId
                    ? {
                        ...m,
                        _streaming: false,
                        ts: new Date().toLocaleTimeString("es-CL", { hour: "2-digit", minute: "2-digit" }),
                      }
                    : m
                )
              );
              break;

            default:
              break;
          }
        }
      }
    } catch (err) {
      if (err.name !== "AbortError") {
        setMensajes((prev) =>
          prev.map((m) =>
            m._streamId === streamId
              ? { ...m, rol: "error", texto: `Error de conexión: ${err.message}`, _streaming: false }
              : m
          )
        );
      }
    } finally {
      setMensajes((prev) =>
        prev.map((m) =>
          m._streamId === streamId ? { ...m, _streaming: false } : m
        )
      );
      setStreaming(false);
      inputRef.current?.focus();
    }
  }, [input, streaming, agenteId, archivoActivo, sesionId, onFilesUsed]);

  // ── Abortar stream activo ────────────────────────────────────────────────────
  const detener = () => {
    abortRef.current?.abort();
  };

  // ── Teclado ──────────────────────────────────────────────────────────────────
  const onKey = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      enviar();
    }
  };

  // ── Render ───────────────────────────────────────────────────────────────────
  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", minHeight: 480 }}>
      <style>{`
        @keyframes blink { 0%,100%{opacity:1} 50%{opacity:0} }
        @keyframes fadeIn { from{opacity:0;transform:translateY(4px)} to{opacity:1;transform:none} }
        .chat-msg-enter { animation: fadeIn .18s ease; }
      `}</style>

      {/* ── Barra superior ───────────────────────────────────────────────── */}
      <div style={{
        display:        "flex",
        alignItems:     "center",
        gap:            12,
        padding:        "10px 16px",
        borderBottom:   "1px solid var(--t-border)",
        background:     "var(--t-bg-card)",
        flexShrink:     0,
      }}>
        <span style={{ fontSize: "0.80rem", color: "var(--t-text-muted)", whiteSpace: "nowrap" }}>
          Agente:
        </span>
        <AgentSelector
          agentes={agentes}
          value={agenteId}
          onChange={setAgenteId}
          disabled={streaming}
        />
        {archivoActivo && (
          <span style={{
            fontSize:   "0.72rem",
            padding:    "3px 10px",
            borderRadius: 20,
            background: "rgba(0,212,255,0.08)",
            border:     "1px solid rgba(0,212,255,0.25)",
            color:      "var(--t-accent)",
          }}>
            📎 {archivoActivo.nombre_original ?? "archivo"}
          </span>
        )}
        {mensajes.length > 0 && (
          <button
            onClick={() => setMensajes([])}
            disabled={streaming}
            title="Limpiar conversación"
            style={{
              marginLeft:   "auto",
              background:   "none",
              border:       "1px solid var(--t-border)",
              borderRadius: 8,
              color:        "var(--t-text-muted)",
              cursor:       streaming ? "not-allowed" : "pointer",
              padding:      "4px 10px",
              fontSize:     "0.72rem",
            }}
          >
            Limpiar
          </button>
        )}
      </div>

      {/* ── Área de mensajes ─────────────────────────────────────────────── */}
      <div style={{
        flex:       1,
        overflowY:  "auto",
        padding:    "16px 20px",
        display:    "flex",
        flexDirection: "column",
      }}>
        {mensajes.length === 0 && (
          <div style={{
            flex:           1,
            display:        "flex",
            flexDirection:  "column",
            alignItems:     "center",
            justifyContent: "center",
            color:          "var(--t-text-muted)",
            gap:            12,
          }}>
            <div style={{ fontSize: "2.5rem", opacity: 0.4 }}>💬</div>
            <div style={{ fontSize: "0.85rem", opacity: 0.6, textAlign: "center" }}>
              Pregunta algo a tus agentes.<br />
              Pueden buscar datos en tiempo real del Banco Central, calcular y más.
            </div>
          </div>
        )}

        {mensajes.map((m) => (
          <div key={m.id} className="chat-msg-enter">
            <Message msg={m} onDownloadPdf={downloadPdf} pdfLoading={pdfLoading} />
          </div>
        ))}

        <div ref={bottomRef} />
      </div>

      {/* ── Input ────────────────────────────────────────────────────────── */}
      <div style={{
        display:      "flex",
        gap:          8,
        padding:      "12px 16px",
        borderTop:    "1px solid var(--t-border)",
        background:   "var(--t-bg-card)",
        flexShrink:   0,
      }}>
        <textarea
          ref={inputRef}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={onKey}
          placeholder={streaming ? "El agente está respondiendo…" : "Escribe un mensaje (Enter para enviar, Shift+Enter para nueva línea)"}
          disabled={streaming}
          rows={2}
          style={{
            flex:        1,
            resize:      "none",
            background:  "var(--t-bg)",
            border:      "1px solid var(--t-border)",
            borderRadius: 10,
            color:       "var(--t-text)",
            padding:     "9px 13px",
            fontSize:    "0.85rem",
            fontFamily:  "inherit",
            lineHeight:  1.5,
            outline:     "none",
            transition:  "border-color .15s",
          }}
          onFocus={(e) => { e.target.style.borderColor = "var(--t-accent)"; }}
          onBlur={(e)  => { e.target.style.borderColor = "var(--t-border)"; }}
        />

        {streaming ? (
          <button
            onClick={detener}
            style={{
              padding:      "0 16px",
              borderRadius: 10,
              border:       "1px solid rgba(239,68,68,0.4)",
              background:   "rgba(239,68,68,0.12)",
              color:        "#f87171",
              cursor:       "pointer",
              fontSize:     "0.82rem",
              fontWeight:   600,
              whiteSpace:   "nowrap",
            }}
          >
            ⏹ Detener
          </button>
        ) : (
          <button
            onClick={enviar}
            disabled={!input.trim()}
            style={{
              padding:      "0 18px",
              borderRadius: 10,
              border:       "none",
              background:   input.trim()
                ? "linear-gradient(135deg, var(--t-accent) 0%, #006fa8 100%)"
                : "var(--t-bg-card)",
              color:        input.trim() ? "#fff" : "var(--t-text-muted)",
              cursor:       input.trim() ? "pointer" : "not-allowed",
              fontSize:     "0.85rem",
              fontWeight:   600,
              transition:   "all .15s",
              border:       input.trim() ? "none" : "1px solid var(--t-border)",
            }}
          >
            Enviar ↑
          </button>
        )}
      </div>
    </div>
  );
}
