/**
 * UpdatePanel.jsx — Pestaña "Actualizaciones": consulta la versión instalada
 * (`GET /version`), busca actualizaciones (`GET /update/check`) y permite
 * configurar la URL del servidor de `version.json` (`PUT /update/url`).
 *
 * Reconstruido desde el bundle de producción (react_dist/assets/index-CRDO1T5r.js,
 * función `c6`): el fuente original de este componente no estaba versionado.
 */
import { useState, useEffect } from "react";
import { RefreshCw, Download } from "../../icons.js";
import { API_BASE } from "../../services/agent.service";
import { addNotification } from "../ui/NotificationSystem";

function authHeaders() {
  const token = sessionStorage.getItem("agentdesk-jwt-token") || "";
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export default function UpdatePanel() {
  const [version, setVersion] = useState("");
  const [info, setInfo] = useState(null);
  const [verificando, setVerificando] = useState(false);
  const [url, setUrl] = useState("");
  const [guardando, setGuardando] = useState(false);

  useEffect(() => {
    fetch(`${API_BASE}/version`)
      .then((r) => r.json())
      .then((d) => setVersion(d.version || ""))
      .catch(() => {});
    setUrl(localStorage.getItem("agentdesk-update-url") || "");
  }, []);

  async function verificar() {
    setVerificando(true);
    setInfo(null);
    try {
      const path = url
        ? `${API_BASE}/update/check?url=${encodeURIComponent(url)}`
        : `${API_BASE}/update/check`;
      const r = await fetch(path, { headers: authHeaders() }).then((res) =>
        res.json(),
      );
      setInfo(r);
      if (r.disponible)
        addNotification({
          message: `Nueva versión disponible: ${r.version_nueva}`,
          type: "info",
        });
      else if (!r.error)
        addNotification({
          message: "AgentDesk está actualizado",
          type: "success",
        });
    } catch (e) {
      addNotification({
        message: "Error al verificar: " + e.message,
        type: "error",
      });
    } finally {
      setVerificando(false);
    }
  }

  async function guardarUrl() {
    setGuardando(true);
    localStorage.setItem("agentdesk-update-url", url);
    try {
      await fetch(`${API_BASE}/update/url`, {
        method: "PUT",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        body: JSON.stringify({ url }),
      });
      addNotification({ message: "URL guardada", type: "success" });
    } catch {
      /* red offline: la URL igual queda guardada en localStorage */
    } finally {
      setGuardando(false);
    }
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
      <div
        style={{
          padding: "14px 18px",
          borderRadius: 14,
          background: "rgba(0,212,255,.06)",
          border: "1px solid rgba(0,212,255,.2)",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
        }}
      >
        <div>
          <div
            style={{
              fontWeight: 800,
              fontSize: "1rem",
              color: "var(--t-text)",
            }}
          >
            AgentDesk v{version || "1.0.0"}
          </div>
          <div
            style={{
              fontSize: ".75rem",
              color: "var(--t-text-muted)",
              marginTop: 3,
            }}
          >
            Versión instalada actualmente
          </div>
        </div>
        <button
          onClick={verificar}
          disabled={verificando}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 7,
            padding: "9px 18px",
            border: "none",
            borderRadius: 10,
            cursor: verificando ? "default" : "pointer",
            background: verificando
              ? "var(--t-border)"
              : "linear-gradient(135deg,var(--t-accent),var(--t-accent2,var(--t-accent)))",
            color: verificando ? "var(--t-text-muted)" : "#0a0e1a",
            fontWeight: 700,
            fontSize: ".82rem",
            fontFamily: "inherit",
          }}
        >
          <RefreshCw
            size={15}
            style={{
              animation: verificando ? "spin .8s linear infinite" : "none",
            }}
          />
          {verificando ? "Verificando..." : "Buscar Actualizaciones"}
          <style>{"@keyframes spin{to{transform:rotate(360deg)}}"}</style>
        </button>
      </div>

      {info && !info.error && (
        <div
          style={{
            padding: "14px 18px",
            borderRadius: 14,
            border: `2px solid ${info.disponible ? "#00ff9d" : "#334155"}`,
            background: info.disponible
              ? "rgba(0,255,157,.07)"
              : "rgba(255,255,255,.02)",
          }}
        >
          {info.disponible ? (
            <>
              <div
                style={{
                  fontWeight: 700,
                  fontSize: ".9rem",
                  color: "#00ff9d",
                  marginBottom: 8,
                }}
              >
                🎉 Nueva versión disponible: v{info.version_nueva}
              </div>
              {info.fecha && (
                <div
                  style={{
                    fontSize: ".75rem",
                    color: "#64748b",
                    marginBottom: 6,
                  }}
                >
                  Fecha: {info.fecha}
                </div>
              )}
              {info.notas && (
                <div
                  style={{
                    fontSize: ".8rem",
                    color: "var(--t-text-muted)",
                    lineHeight: 1.6,
                    marginBottom: 12,
                  }}
                >
                  {info.notas}
                </div>
              )}
              {info.url_descarga ? (
                <a
                  href={info.url_descarga}
                  target="_blank"
                  rel="noreferrer"
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: 7,
                    padding: "8px 18px",
                    borderRadius: 10,
                    border: "none",
                    background: "#00ff9d",
                    color: "#0a0e1a",
                    fontWeight: 700,
                    fontSize: ".82rem",
                    textDecoration: "none",
                  }}
                >
                  <Download size={15} /> Descargar e Instalar
                </a>
              ) : (
                <div style={{ fontSize: ".75rem", color: "#64748b" }}>
                  Descarga no disponible — configura una URL de servidor de
                  actualizaciones.
                </div>
              )}
              {info.obligatoria && (
                <div
                  style={{
                    marginTop: 8,
                    fontSize: ".75rem",
                    color: "#f59e0b",
                    fontWeight: 600,
                  }}
                >
                  ⚠️ Actualización obligatoria
                </div>
              )}
            </>
          ) : (
            <div
              style={{ fontWeight: 600, fontSize: ".88rem", color: "#00d4ff" }}
            >
              ✓ AgentDesk v{info.version_actual} está al día
            </div>
          )}
        </div>
      )}
      {info?.error && (
        <div
          style={{
            padding: "10px 14px",
            borderRadius: 10,
            background: "rgba(245,158,11,.08)",
            border: "1px solid rgba(245,158,11,.3)",
            color: "#f59e0b",
            fontSize: ".8rem",
          }}
        >
          ⚠️ {info.error}
        </div>
      )}

      <div
        style={{
          padding: "1.2rem 1.4rem",
          borderRadius: 14,
          border: "1px solid var(--t-border)",
          background: "var(--t-bg-card)",
        }}
      >
        <div
          style={{
            fontWeight: 700,
            fontSize: ".85rem",
            color: "var(--t-text)",
            marginBottom: 6,
          }}
        >
          🌐 Servidor de Actualizaciones
        </div>
        <div
          style={{
            fontSize: ".75rem",
            color: "var(--t-text-muted)",
            marginBottom: "1rem",
            lineHeight: 1.6,
          }}
        >
          Configura la URL donde se aloja el archivo <code>version.json</code>{" "}
          con la versión más reciente. Puede ser un GitHub Gist, un servidor
          propio o cualquier URL pública.
        </div>
        <div style={{ marginBottom: 8, fontSize: ".72rem", color: "#64748b" }}>
          Formato de <code>version.json</code>:
          <pre
            style={{
              margin: "6px 0",
              padding: "8px 12px",
              borderRadius: 8,
              background: "var(--t-bg)",
              fontSize: ".7rem",
              color: "#94a3b8",
              overflow: "auto",
            }}
          >
            {`{
  "version": "1.1.0",
  "notas": "Descripción de cambios",
  "url_descarga": "https://tu-servidor/AgentDesk_1.1.0.exe",
  "fecha": "2026-07-01",
  "obligatoria": false
}`}
          </pre>
        </div>
        <div style={{ display: "flex", gap: ".5rem" }}>
          <input
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://raw.githubusercontent.com/tu_usuario/repo/main/version.json"
            style={{
              flex: 1,
              padding: "8px 12px",
              borderRadius: 8,
              fontFamily: "inherit",
              border: "1px solid var(--t-border)",
              background: "var(--t-bg)",
              color: "var(--t-text)",
              fontSize: ".8rem",
              outline: "none",
            }}
          />
          <button
            onClick={guardarUrl}
            disabled={guardando || !url.trim()}
            style={{
              padding: "8px 16px",
              borderRadius: 8,
              border: "none",
              background: url.trim() ? "var(--t-accent)" : "var(--t-border)",
              color: url.trim() ? "#0a0e1a" : "var(--t-text-muted)",
              cursor: url.trim() ? "pointer" : "default",
              fontWeight: 600,
              fontSize: ".8rem",
              fontFamily: "inherit",
            }}
          >
            {guardando ? "Guardando..." : "Guardar"}
          </button>
        </div>
      </div>
    </div>
  );
}
