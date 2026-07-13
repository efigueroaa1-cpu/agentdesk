import { useState, useEffect, useCallback, useRef } from "react";
import { API_BASE } from "../../services/agent.service";

const TOKEN = () => sessionStorage.getItem("agentdesk-jwt-token") || "";

const TIPO_BADGE = {
  pdf: { bg: "rgba(239,68,68,0.12)", color: "#f87171", label: "PDF" },
  md: { bg: "rgba(0,212,255,0.10)", color: "var(--t-accent)", label: "MD" },
  json: { bg: "rgba(168,85,247,0.12)", color: "#c084fc", label: "JSON" },
};

function Badge({ tipo }) {
  const s = TIPO_BADGE[tipo] ?? TIPO_BADGE.md;
  return (
    <span
      style={{
        fontSize: "0.65rem",
        fontWeight: 700,
        padding: "2px 7px",
        borderRadius: 6,
        background: s.bg,
        color: s.color,
        border: `1px solid ${s.color}40`,
      }}
    >
      {s.label}
    </span>
  );
}

function fmtFecha(mtime) {
  if (!mtime) return "—";
  return new Date(mtime * 1000).toLocaleString("es-CL", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function fmtTam(kb) {
  if (kb == null) return "—";
  return kb >= 1024 ? `${(kb / 1024).toFixed(1)} MB` : `${kb} KB`;
}

function nombreAgente(nombre) {
  const m = nombre.match(/^(?:reporte|correccion)_(.+?)_\d{8}_\d{6}/);
  if (!m) return nombre;
  return m[1].replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function tipoReporte(nombre) {
  if (nombre.startsWith("correccion_")) return "Corrección";
  if (nombre.startsWith("reporte_")) return "Informe";
  return "Archivo";
}

export default function ReportsPanel() {
  const [reportes, setReportes] = useState([]);
  const [loading, setLoading] = useState(true);
  const [descargando, setDescargando] = useState(null);
  const [filtro, setFiltro] = useState("todos");
  const [busqueda, setBusqueda] = useState("");
  const [toast, setToast] = useState("");
  const toastTimer = useRef(null);

  const notify = useCallback((msg) => {
    setToast(msg);
    clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(""), 3000);
  }, []);

  useEffect(() => () => clearTimeout(toastTimer.current), []);

  const cargar = useCallback(async () => {
    try {
      const r = await fetch(`${API_BASE}/reportes`, {
        headers: { Authorization: `Bearer ${TOKEN()}` },
      });
      if (r.ok) {
        const data = await r.json();
        setReportes(data.reportes ?? []);
      }
    } catch {
      // sin conexión con el backend: se mantiene la última lista cargada
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    cargar();
    const t = setInterval(cargar, 15_000);
    return () => clearInterval(t);
  }, [cargar]);

  const descargar = async (nombre) => {
    setDescargando(nombre);
    try {
      const r = await fetch(
        `${API_BASE}/reportes/${encodeURIComponent(nombre)}`,
        {
          headers: { Authorization: `Bearer ${TOKEN()}` },
        },
      );
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const blob = await r.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = nombre;
      a.click();
      URL.revokeObjectURL(url);
      notify(`Descargado en Descargas: ${nombre}`);
    } catch (e) {
      alert(`No se pudo descargar: ${e.message}`);
    } finally {
      setDescargando(null);
    }
  };

  const filtrados = reportes.filter((r) => {
    if (filtro === "pdf" && r.tipo !== "pdf") return false;
    if (filtro === "chat" && r.tipo !== "pdf") return false;
    if (busqueda && !r.nombre.toLowerCase().includes(busqueda.toLowerCase()))
      return false;
    return true;
  });

  // ── Estilos comunes ───────────────────────────────────────────────────────────
  const card = {
    background: "var(--t-bg-card)",
    border: "1px solid var(--t-border)",
    borderRadius: 10,
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {/* Cabecera */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 12,
          flexWrap: "wrap",
        }}
      >
        <div>
          <h2 style={{ margin: 0, fontSize: "1.1rem", color: "var(--t-text)" }}>
            Reportes PDF
          </h2>
          <p
            style={{
              margin: "2px 0 0",
              fontSize: "0.78rem",
              color: "var(--t-text-muted)",
            }}
          >
            Informes generados desde el chat y el pipeline
          </p>
        </div>

        <div
          style={{
            marginLeft: "auto",
            display: "flex",
            gap: 8,
            flexWrap: "wrap",
          }}
        >
          {/* Buscador */}
          <input
            value={busqueda}
            onChange={(e) => setBusqueda(e.target.value)}
            placeholder="Buscar..."
            style={{
              background: "var(--t-bg)",
              border: "1px solid var(--t-border)",
              borderRadius: 8,
              color: "var(--t-text)",
              padding: "5px 11px",
              fontSize: "0.78rem",
              fontFamily: "inherit",
              outline: "none",
              width: 160,
            }}
          />
          {/* Filtros */}
          {[
            ["todos", "Todos"],
            ["pdf", "Solo PDF"],
          ].map(([k, l]) => (
            <button
              key={k}
              onClick={() => setFiltro(k)}
              style={{
                padding: "5px 13px",
                borderRadius: 20,
                fontSize: "0.72rem",
                fontWeight: 600,
                cursor: "pointer",
                fontFamily: "inherit",
                border:
                  filtro === k
                    ? "1.5px solid var(--t-accent)"
                    : "1px solid var(--t-border)",
                background:
                  filtro === k ? "rgba(0,212,255,.12)" : "transparent",
                color: filtro === k ? "var(--t-accent)" : "var(--t-text-muted)",
              }}
            >
              {l}
            </button>
          ))}
          <button
            onClick={cargar}
            title="Refrescar lista"
            style={{
              padding: "5px 12px",
              borderRadius: 20,
              fontSize: "0.72rem",
              border: "1px solid var(--t-border)",
              background: "transparent",
              color: "var(--t-text-muted)",
              cursor: "pointer",
              fontFamily: "inherit",
            }}
          >
            ↺ Actualizar
          </button>
        </div>
      </div>

      {/* Contador */}
      {!loading && (
        <div style={{ fontSize: "0.76rem", color: "var(--t-text-muted)" }}>
          {filtrados.length} {filtrados.length === 1 ? "reporte" : "reportes"}
          {reportes.length !== filtrados.length &&
            ` de ${reportes.length} total`}
        </div>
      )}

      {/* Estado cargando */}
      {loading && (
        <div
          style={{
            ...card,
            padding: "3rem",
            textAlign: "center",
            color: "var(--t-text-muted)",
          }}
        >
          <div style={{ fontSize: "1.5rem", marginBottom: 8, opacity: 0.4 }}>
            ⏳
          </div>
          Cargando reportes…
        </div>
      )}

      {/* Estado vacío */}
      {!loading && filtrados.length === 0 && (
        <div style={{ ...card, padding: "4rem 2rem", textAlign: "center" }}>
          <div style={{ fontSize: "3.5rem", opacity: 0.2, marginBottom: 12 }}>
            📄
          </div>
          <div
            style={{ color: "var(--t-text)", fontWeight: 600, marginBottom: 6 }}
          >
            No hay reportes aún
          </div>
          <div
            style={{
              color: "var(--t-text-muted)",
              fontSize: "0.82rem",
              lineHeight: 1.6,
            }}
          >
            {busqueda ? (
              <>No se encontraron resultados para &quot;{busqueda}&quot;.</>
            ) : (
              <>
                Conversa con cualquier agente en la pestaña{" "}
                <strong>Agentes → Chat</strong>
                <br />y usa el botón <strong>↓ PDF</strong> que aparece bajo
                cada respuesta.
              </>
            )}
          </div>
        </div>
      )}

      {/* Lista de reportes */}
      {!loading && filtrados.length > 0 && (
        <div style={{ ...card, overflow: "hidden" }}>
          {/* Encabezado tabla */}
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "1fr auto auto auto auto",
              gap: 12,
              padding: "9px 16px",
              borderBottom: "1px solid var(--t-border)",
              background: "var(--t-bg)",
              fontSize: "0.70rem",
              fontWeight: 700,
              color: "var(--t-text-muted)",
              textTransform: "uppercase",
              letterSpacing: ".05em",
            }}
          >
            <span>Nombre / Agente</span>
            <span style={{ textAlign: "center" }}>Tipo</span>
            <span style={{ textAlign: "right" }}>Tamaño</span>
            <span style={{ textAlign: "right" }}>Fecha</span>
            <span style={{ textAlign: "center" }}>Acción</span>
          </div>

          {/* Filas */}
          {filtrados.map((rep, i) => (
            <div
              key={rep.nombre}
              style={{
                display: "grid",
                gridTemplateColumns: "1fr auto auto auto auto",
                gap: 12,
                padding: "10px 16px",
                alignItems: "center",
                borderBottom:
                  i < filtrados.length - 1
                    ? "1px solid var(--t-border)"
                    : "none",
                background:
                  i % 2 === 0 ? "transparent" : "rgba(255,255,255,0.01)",
                transition: "background .12s",
              }}
              onMouseEnter={(e) =>
                (e.currentTarget.style.background = "rgba(0,212,255,0.04)")
              }
              onMouseLeave={(e) =>
                (e.currentTarget.style.background =
                  i % 2 === 0 ? "transparent" : "rgba(255,255,255,0.01)")
              }
            >
              {/* Nombre */}
              <div>
                <div
                  style={{
                    fontSize: "0.82rem",
                    color: "var(--t-text)",
                    fontWeight: 500,
                  }}
                >
                  {tipoReporte(rep.nombre)} — {nombreAgente(rep.nombre)}
                </div>
                <div
                  style={{
                    fontSize: "0.68rem",
                    color: "var(--t-text-muted)",
                    marginTop: 2,
                    fontFamily: "monospace",
                  }}
                >
                  {rep.nombre}
                </div>
              </div>

              {/* Badge tipo */}
              <div style={{ textAlign: "center" }}>
                <Badge tipo={rep.tipo} />
              </div>

              {/* Tamaño */}
              <div
                style={{
                  fontSize: "0.78rem",
                  color: "var(--t-text-muted)",
                  textAlign: "right",
                  whiteSpace: "nowrap",
                }}
              >
                {fmtTam(rep.tamano_kb)}
              </div>

              {/* Fecha */}
              <div
                style={{
                  fontSize: "0.73rem",
                  color: "var(--t-text-muted)",
                  textAlign: "right",
                  whiteSpace: "nowrap",
                }}
              >
                {fmtFecha(rep.mtime)}
              </div>

              {/* Botón descargar */}
              <div style={{ textAlign: "center" }}>
                <button
                  onClick={() => descargar(rep.nombre)}
                  disabled={descargando === rep.nombre}
                  title={`Descargar ${rep.nombre}`}
                  style={{
                    padding: "5px 13px",
                    borderRadius: 8,
                    border: "1px solid rgba(0,212,255,0.35)",
                    background:
                      descargando === rep.nombre
                        ? "rgba(0,212,255,0.05)"
                        : "rgba(0,212,255,0.10)",
                    color: "var(--t-accent)",
                    cursor:
                      descargando === rep.nombre ? "not-allowed" : "pointer",
                    fontSize: "0.75rem",
                    fontWeight: 600,
                    fontFamily: "inherit",
                    whiteSpace: "nowrap",
                    transition: "all .15s",
                  }}
                >
                  {descargando === rep.nombre ? "…" : "↓ Descargar"}
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Nota informativa */}
      <div
        style={{
          fontSize: "0.73rem",
          color: "var(--t-text-muted)",
          padding: "8px 12px",
          background: "rgba(0,212,255,0.04)",
          border: "1px solid rgba(0,212,255,0.12)",
          borderRadius: 8,
        }}
      >
        El servidor genera los reportes en{" "}
        <code style={{ fontSize: "0.70rem" }}>
          %APPDATA%\AgentDesk\reportes\
        </code>{" "}
        (esta lista se actualiza cada 15 segundos). Al pulsar{" "}
        <strong>Descargar</strong> el archivo se guarda directo en tu carpeta{" "}
        <strong>Descargas</strong> sin mostrar un diálogo — no hace falta hacer
        clic más de una vez.
      </div>

      {/* Toast: la descarga no muestra diálogo nativo (WebView2 la guarda directo
          en Descargas), así que confirmamos aquí para que no parezca que no pasó nada. */}
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
