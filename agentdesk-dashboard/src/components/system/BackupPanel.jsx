/**
 * BackupPanel.jsx — Pestaña "Backup & Restore": descarga un ZIP con toda la
 * base de datos y configuración (`GET /backup/descargar`) y permite
 * restaurar uno previamente generado (`POST /backup/restaurar`). Ambos
 * endpoints requieren rol admin (verificado por el backend); si el usuario
 * no tiene el rol se explica el motivo en vez de mostrar un error genérico.
 *
 * Reconstruido desde el bundle de producción (react_dist/assets/index-CRDO1T5r.js,
 * función `l6`): el fuente original de este componente no estaba versionado.
 */
import { useState, useEffect, useRef } from "react";
import { Download, Upload, HardDrive, ShieldAlert } from "../../icons.js";
import { API_BASE } from "../../services/agent.service";
import { useAuth } from "../../context/AuthContext";
import { addNotification } from "../ui/NotificationSystem";

function authHeaders() {
  const token = sessionStorage.getItem("agentdesk-jwt-token") || "";
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export default function BackupPanel() {
  const { usuario } = useAuth();
  const [version, setVersion] = useState("");
  const [descargando, setDescargando] = useState(false);
  const [restaurando, setRestaurando] = useState(false);
  const [resultado, setResultado] = useState(null);
  const fileRef = useRef(null);

  useEffect(() => {
    fetch(`${API_BASE}/version`)
      .then((r) => r.json())
      .then((d) => setVersion(d.version || ""))
      .catch(() => {});
  }, []);

  const esAdmin = usuario?.role === "admin";

  async function descargar() {
    setDescargando(true);
    try {
      const r = await fetch(`${API_BASE}/backup/descargar`, {
        headers: authHeaders(),
      });
      if (!r.ok)
        throw new Error(
          r.status === 403 ? "Se requiere rol admin." : `Error ${r.status}`,
        );
      const blob = await r.blob();
      const url = URL.createObjectURL(blob);
      const ts = new Date().toISOString().slice(0, 16).replace(/[T:]/g, "_");
      const a = document.createElement("a");
      a.href = url;
      a.download = `agentdesk_backup_${ts}.zip`;
      a.click();
      URL.revokeObjectURL(url);
      addNotification({
        message: "Backup descargado correctamente",
        type: "success",
      });
    } catch (e) {
      addNotification({
        message: "Error al descargar backup: " + e.message,
        type: "error",
      });
    } finally {
      setDescargando(false);
    }
  }

  async function restaurar(file) {
    if (!file) return;
    setRestaurando(true);
    setResultado(null);
    const form = new FormData();
    form.append("archivo", file);
    try {
      const r = await fetch(`${API_BASE}/backup/restaurar`, {
        method: "POST",
        headers: authHeaders(),
        body: form,
      }).then((res) => res.json());
      setResultado(r);
      if (r.ok)
        addNotification({
          message: `Backup restaurado (${r.total ?? "?"} registros)`,
          type: "success",
        });
      else
        addNotification({
          message: r.error ?? "No se pudo restaurar el backup.",
          type: "error",
        });
    } catch (e) {
      setResultado({ ok: false, error: e.message });
      addNotification({
        message: "Error al restaurar backup: " + e.message,
        type: "error",
      });
    } finally {
      setRestaurando(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  if (!esAdmin) {
    return (
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          padding: "3rem 1rem",
          gap: 10,
          color: "var(--t-text-muted)",
        }}
      >
        <ShieldAlert size={32} style={{ opacity: 0.4 }} />
        <p style={{ fontSize: ".85rem", margin: 0 }}>
          Solo el administrador puede descargar o restaurar backups.
        </p>
      </div>
    );
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
          flexWrap: "wrap",
          gap: "1rem",
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
            Descarga la base de datos y configuración completas en un ZIP
          </div>
        </div>
        <button
          onClick={descargar}
          disabled={descargando}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 7,
            padding: "9px 18px",
            border: "none",
            borderRadius: 10,
            cursor: descargando ? "default" : "pointer",
            background: descargando
              ? "var(--t-border)"
              : "linear-gradient(135deg,var(--t-accent),var(--t-accent2,var(--t-accent)))",
            color: descargando ? "var(--t-text-muted)" : "#0a0e1a",
            fontWeight: 700,
            fontSize: ".82rem",
            fontFamily: "inherit",
          }}
        >
          <Download size={15} />{" "}
          {descargando ? "Descargando..." : "Descargar Backup"}
        </button>
      </div>

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
            display: "flex",
            alignItems: "center",
            gap: 7,
            marginBottom: 6,
            fontWeight: 700,
            fontSize: ".85rem",
            color: "var(--t-text)",
          }}
        >
          <HardDrive size={16} color="var(--t-accent)" /> Restaurar Backup
        </div>
        <p
          style={{
            fontSize: ".75rem",
            color: "var(--t-text-muted)",
            margin: "0 0 1rem",
            lineHeight: 1.6,
          }}
        >
          Sube un ZIP generado con <strong>Descargar Backup</strong> para
          restaurar la base de datos y configuración. Esta operación puede
          sobrescribir datos existentes.
        </p>
        <div
          style={{
            display: "flex",
            gap: ".6rem",
            alignItems: "center",
            flexWrap: "wrap",
          }}
        >
          <input
            ref={fileRef}
            type="file"
            accept=".zip"
            disabled={restaurando}
            onChange={(e) => restaurar(e.target.files?.[0])}
            style={{ fontSize: ".8rem", color: "var(--t-text-muted)" }}
          />
          {restaurando && (
            <span
              style={{
                fontSize: ".75rem",
                color: "var(--t-accent)",
                display: "flex",
                alignItems: "center",
                gap: 5,
              }}
            >
              <Upload size={13} /> Restaurando...
            </span>
          )}
        </div>
        {resultado && (
          <div
            style={{
              marginTop: "1rem",
              padding: "10px 14px",
              borderRadius: 10,
              fontSize: ".8rem",
              background: resultado.ok
                ? "rgba(0,255,157,.08)"
                : "rgba(255,45,85,.08)",
              border: `1px solid ${resultado.ok ? "rgba(0,255,157,.3)" : "rgba(255,45,85,.3)"}`,
              color: resultado.ok ? "#00ff9d" : "#ff2d55",
            }}
          >
            {resultado.ok
              ? `Restauración completada (${resultado.total ?? "?"} registros).`
              : (resultado.error ?? "No se pudo restaurar el backup.")}
          </div>
        )}
      </div>
    </div>
  );
}
