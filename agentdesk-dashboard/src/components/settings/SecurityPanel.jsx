/**
 * SecurityPanel.jsx — Panel de Seguridad y Administración (ID 13).
 *
 * Secciones (solo admin):
 *   1. Generador de hash bcrypt (client-side, nunca envía contraseña en claro)
 *   2. Gestión de usuarios RBAC (GET/POST/DELETE/PUT /auth/usuarios)
 *      Roles: admin · supervisor · viewer
 *   3. Kill Switch remoto (activa/desactiva ejecución de agentes)
 *   4. Cambio de contraseña de usuarios
 *
 * Sprint 8: integrado con endpoints /auth/usuarios del backend RBAC.
 */

import { useState, useEffect, useCallback } from "react";
import bcrypt from "bcryptjs";
import {
  Shield, Copy, Check, Eye, EyeOff, RefreshCw,
  UserPlus, AlertCircle, Lock, Trash2, Users,
  Power, PowerOff, Key, Edit2, X, Globe, Download,
  Link,
} from "lucide-react";
import { useAuth } from "../../context/AuthContext";
import { API_BASE } from "../../services/agent.service";

// ── Estilos base ──────────────────────────────────────────────────────────────
const card = { borderRadius: 14, border: "1px solid var(--t-border)",
               background: "var(--t-bg-base)", padding: "20px 22px",
               display: "flex", flexDirection: "column", gap: 16 };

const input = {
  background: "var(--t-bg-deep)", borderColor: "var(--t-border)",
  color: "var(--t-text)", borderRadius: 10, border: "1px solid",
  padding: "8px 12px", fontSize: 13, width: "100%", fontFamily: "inherit",
  outline: "none",
};

const btnPrimary = {
  display: "flex", alignItems: "center", gap: 6,
  padding: "8px 16px", borderRadius: 10, fontSize: 13, fontWeight: 600,
  background: "var(--t-bg-accent)", color: "var(--t-accent)",
  border: "1px solid var(--t-accent)", cursor: "pointer",
};

const btnDanger = {
  display: "flex", alignItems: "center", gap: 6,
  padding: "6px 12px", borderRadius: 8, fontSize: 12, fontWeight: 600,
  background: "rgba(239,68,68,0.1)", color: "#ef4444",
  border: "1px solid rgba(239,68,68,0.35)", cursor: "pointer",
};

// ── Helpers ───────────────────────────────────────────────────────────────────
function rolColor(rol) {
  return { admin: "#00d4ff", supervisor: "#a78bfa", viewer: "#64748b" }[rol] ?? "#64748b";
}

function RolBadge({ rol }) {
  return (
    <span style={{
      color: rolColor(rol), background: `${rolColor(rol)}18`,
      border: `1px solid ${rolColor(rol)}44`,
      borderRadius: 6, padding: "2px 8px", fontSize: 11, fontWeight: 700,
    }}>
      {rol}
    </span>
  );
}

function Msg({ msg }) {
  if (!msg) return null;
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 6, fontSize: 12,
      color: msg.type === "ok" ? "#22c55e" : "#ef4444",
    }}>
      {msg.type === "ok" ? <Check size={13} /> : <AlertCircle size={13} />}
      {msg.text}
    </div>
  );
}

// ── 1. Generador de hash bcrypt ───────────────────────────────────────────────
function HashGenerator() {
  const [password,   setPassword]   = useState("");
  const [rounds,     setRounds]     = useState(12);
  const [hash,       setHash]       = useState("");
  const [showPw,     setShowPw]     = useState(false);
  const [generating, setGenerating] = useState(false);
  const [copied,     setCopied]     = useState(false);

  const generateHash = async () => {
    if (!password.trim()) return;
    setGenerating(true);
    setHash("");
    await new Promise(r => setTimeout(r, 30));
    const salt    = bcrypt.genSaltSync(rounds);
    const newHash = bcrypt.hashSync(password.trim(), salt);
    setHash(newHash);
    setGenerating(false);
  };

  const copyHash = () => {
    navigator.clipboard.writeText(hash);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      {/* Input contraseña */}
      <div style={{ position: "relative" }}>
        <Lock size={13} style={{
          position: "absolute", left: 10, top: "50%", transform: "translateY(-50%)",
          color: "var(--t-text-muted)", pointerEvents: "none",
        }} />
        <input
          type={showPw ? "text" : "password"}
          value={password}
          onChange={e => setPassword(e.target.value)}
          onKeyDown={e => e.key === "Enter" && generateHash()}
          placeholder="Contraseña a hashear…"
          style={{ ...input, paddingLeft: 32, paddingRight: 36 }}
        />
        <button onClick={() => setShowPw(v => !v)} style={{
          position: "absolute", right: 10, top: "50%", transform: "translateY(-50%)",
          background: "none", border: "none", cursor: "pointer", color: "var(--t-text-muted)",
        }}>
          {showPw ? <EyeOff size={14} /> : <Eye size={14} />}
        </button>
      </div>

      {/* Rounds */}
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <span style={{ fontSize: 12, color: "var(--t-text-muted)", whiteSpace: "nowrap" }}>
          Rounds: <strong style={{ color: "var(--t-accent)" }}>{rounds}</strong>
        </span>
        <input
          type="range" min={10} max={14} value={rounds}
          onChange={e => setRounds(Number(e.target.value))}
          style={{ flex: 1, accentColor: "var(--t-accent)" }}
        />
        <span style={{ fontSize: 11, color: "var(--t-text-muted)" }}>
          (~{Math.round(2 ** rounds / 1000)}k iter.)
        </span>
      </div>

      {/* Botón */}
      <button onClick={generateHash} disabled={generating || !password.trim()} style={btnPrimary}>
        {generating
          ? <><RefreshCw size={13} style={{ animation: "spin 1s linear infinite" }} />Generando…</>
          : <><Shield size={13} />Generar Hash bcrypt</>
        }
      </button>

      {/* Resultado */}
      {hash && (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <div style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
            <pre style={{
              flex: 1, fontSize: 11, padding: "10px 12px", borderRadius: 10,
              background: "var(--t-bg-deep)", color: "#22c55e", wordBreak: "break-all",
              border: "1px solid var(--t-border)", margin: 0, fontFamily: "monospace",
            }}>
              {hash}
            </pre>
            <button onClick={copyHash} style={{
              padding: "8px", borderRadius: 8, background: "none",
              border: "1px solid var(--t-border)", cursor: "pointer",
              color: copied ? "#22c55e" : "var(--t-text-muted)",
            }}>
              {copied ? <Check size={14} /> : <Copy size={14} />}
            </button>
          </div>
          <p style={{ fontSize: 11, color: "var(--t-text-muted)", margin: 0 }}>
            Pega este hash en <code style={{ color: "var(--t-accent)" }}>.env</code> como{" "}
            <code style={{ color: "var(--t-accent)" }}>MASTER_PASSWORD_HASH</code>{" "}
            o úsalo al crear un usuario.
          </p>
        </div>
      )}
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );
}

// ── 2. Gestión de usuarios RBAC ───────────────────────────────────────────────
function UserManager({ token }) {
  const { usuario }             = useAuth();
  const [users,      setUsers]  = useState([]);
  const [loading,    setLoading]= useState(false);
  const [msg,        setMsg]    = useState(null);
  const [showForm,   setShowForm] = useState(false);
  const [editRol,    setEditRol]  = useState(null);  // username en edición de rol

  // Nuevo usuario
  const [newUser, setNewUser]   = useState({ username: "", password: "", rol: "viewer" });
  const [saving,  setSaving]    = useState(false);

  const authHeaders = token ? { Authorization: `Bearer ${token}` } : {};

  const showMsg = (text, type = "ok") => {
    setMsg({ text, type });
    setTimeout(() => setMsg(null), 4000);
  };

  const cargarUsuarios = useCallback(async () => {
    setLoading(true);
    try {
      const res  = await fetch(`${API_BASE}/auth/usuarios`, { headers: authHeaders });
      if (res.status === 403) { showMsg("Se requiere rol admin.", "error"); return; }
      const data = await res.json();
      setUsers(Array.isArray(data) ? data : []);
    } catch {
      showMsg("No se pudo cargar la lista de usuarios.", "error");
    } finally {
      setLoading(false);
    }
  }, [token]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { cargarUsuarios(); }, [cargarUsuarios]);

  const handleCreate = async () => {
    if (!newUser.username.trim() || !newUser.password.trim()) {
      showMsg("Usuario y contraseña son obligatorios.", "error"); return;
    }
    setSaving(true);
    setMsg(null);
    try {
      const res = await fetch(`${API_BASE}/auth/usuarios`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders },
        body: JSON.stringify(newUser),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail ?? "Error al crear usuario.");
      showMsg(`Usuario "${newUser.username}" creado con rol ${newUser.rol}.`);
      setNewUser({ username: "", password: "", rol: "viewer" });
      setShowForm(false);
      cargarUsuarios();
    } catch (e) {
      showMsg(e.message, "error");
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (username) => {
    if (!confirm(`¿Eliminar al usuario "${username}"?`)) return;
    try {
      const res = await fetch(`${API_BASE}/auth/usuarios/${encodeURIComponent(username)}`, {
        method: "DELETE", headers: authHeaders,
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail ?? "Error al eliminar.");
      showMsg(`Usuario "${username}" eliminado.`);
      cargarUsuarios();
    } catch (e) {
      showMsg(e.message, "error");
    }
  };

  const handleCambiarRol = async (username, nuevo_rol) => {
    try {
      const res = await fetch(`${API_BASE}/auth/usuarios/${encodeURIComponent(username)}/rol`, {
        method: "PUT",
        headers: { "Content-Type": "application/json", ...authHeaders },
        body: JSON.stringify({ nuevo_rol }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail ?? "Error al cambiar rol.");
      showMsg(`Rol de "${username}" cambiado a ${nuevo_rol}.`);
      setEditRol(null);
      cargarUsuarios();
    } catch (e) {
      showMsg(e.message, "error");
    }
  };

  const handleToggleActivo = async (username, activo) => {
    try {
      const res = await fetch(`${API_BASE}/auth/usuarios/${encodeURIComponent(username)}/activo`, {
        method: "PUT",
        headers: { "Content-Type": "application/json", ...authHeaders },
        body: JSON.stringify({ activo }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail ?? "Error.");
      showMsg(`Usuario "${username}" ${activo ? "activado" : "desactivado"}.`);
      cargarUsuarios();
    } catch (e) {
      showMsg(e.message, "error");
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      {/* Acciones */}
      <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
        <button onClick={() => setShowForm(v => !v)} style={btnPrimary}>
          <UserPlus size={14} />
          {showForm ? "Cancelar" : "Nuevo usuario"}
        </button>
        <button onClick={cargarUsuarios} style={{
          ...btnPrimary, background: "transparent", color: "var(--t-text-muted)",
          borderColor: "var(--t-border)",
        }}>
          <RefreshCw size={13} style={{ animation: loading ? "spin 1s linear infinite" : "none" }} />
        </button>
        <Msg msg={msg} />
      </div>

      {/* Formulario nuevo usuario */}
      {showForm && (
        <div style={{
          background: "var(--t-bg-deep)", border: "1px solid var(--t-border)",
          borderRadius: 12, padding: "16px",
          display: "grid", gridTemplateColumns: "1fr 1fr auto auto",
          gap: 10, alignItems: "end",
        }}>
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <label style={{ fontSize: 11, color: "var(--t-text-muted)" }}>Username</label>
            <input
              value={newUser.username}
              onChange={e => setNewUser(p => ({ ...p, username: e.target.value }))}
              placeholder="ej. jsmith"
              style={input}
            />
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <label style={{ fontSize: 11, color: "var(--t-text-muted)" }}>Contraseña (≥8 chars)</label>
            <input
              type="password"
              value={newUser.password}
              onChange={e => setNewUser(p => ({ ...p, password: e.target.value }))}
              placeholder="Contraseña inicial"
              style={input}
            />
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <label style={{ fontSize: 11, color: "var(--t-text-muted)" }}>Rol</label>
            <select
              value={newUser.rol}
              onChange={e => setNewUser(p => ({ ...p, rol: e.target.value }))}
              style={{ ...input, width: "auto" }}
            >
              <option value="viewer">viewer</option>
              <option value="supervisor">supervisor</option>
              <option value="admin">admin</option>
            </select>
          </div>
          <button onClick={handleCreate} disabled={saving} style={{ ...btnPrimary, alignSelf: "end" }}>
            {saving ? <RefreshCw size={13} style={{ animation: "spin 1s linear infinite" }} /> : <Check size={13} />}
            {saving ? "Creando…" : "Crear"}
          </button>
        </div>
      )}

      {/* Tabla de usuarios */}
      {users.length > 0 && (
        <div style={{ borderRadius: 12, border: "1px solid var(--t-border)", overflow: "hidden" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
            <thead>
              <tr style={{ background: "var(--t-bg-deep)" }}>
                {["#", "Usuario", "Rol", "Estado", "Último acceso", "Acciones"].map(h => (
                  <th key={h} style={{
                    padding: "8px 12px", textAlign: "left", fontWeight: 600,
                    color: "var(--t-text-muted)", fontSize: 11,
                  }}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {users.map((u, i) => (
                <tr key={u.id ?? u.username} style={{
                  borderTop: "1px solid var(--t-border)",
                  background: i % 2 === 0 ? "transparent" : "rgba(255,255,255,0.015)",
                }}>
                  <td style={{ padding: "8px 12px", color: "var(--t-text-muted)" }}>{u.id}</td>
                  <td style={{ padding: "8px 12px", fontWeight: 600, color: "var(--t-text)" }}>
                    {u.username}
                    {u.username === usuario?.username && (
                      <span style={{ marginLeft: 6, fontSize: 10,
                                     color: "var(--t-accent)", opacity: 0.7 }}>
                        (tú)
                      </span>
                    )}
                  </td>

                  {/* Celda de rol con editor inline */}
                  <td style={{ padding: "8px 12px" }}>
                    {editRol === u.username ? (
                      <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                        <select
                          defaultValue={u.rol}
                          id={`rol-${u.username}`}
                          style={{ ...input, width: "auto", padding: "3px 8px", fontSize: 11 }}
                        >
                          <option value="viewer">viewer</option>
                          <option value="supervisor">supervisor</option>
                          <option value="admin">admin</option>
                        </select>
                        <button
                          onClick={() => {
                            const sel = document.getElementById(`rol-${u.username}`);
                            handleCambiarRol(u.username, sel.value);
                          }}
                          style={{ padding: "3px 6px", borderRadius: 6,
                                   background: "rgba(34,197,94,0.15)", border: "1px solid #22c55e44",
                                   color: "#22c55e", cursor: "pointer" }}
                        >
                          <Check size={11} />
                        </button>
                        <button onClick={() => setEditRol(null)} style={{
                          padding: "3px 6px", borderRadius: 6, background: "none",
                          border: "1px solid var(--t-border)", color: "var(--t-text-muted)", cursor: "pointer",
                        }}>
                          <X size={11} />
                        </button>
                      </div>
                    ) : (
                      <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                        <RolBadge rol={u.rol} />
                        {u.username !== usuario?.username && (
                          <button onClick={() => setEditRol(u.username)} style={{
                            padding: "2px 4px", borderRadius: 5, background: "none",
                            border: "none", cursor: "pointer", color: "var(--t-text-muted)",
                            opacity: 0.6,
                          }}>
                            <Edit2 size={11} />
                          </button>
                        )}
                      </div>
                    )}
                  </td>

                  <td style={{ padding: "8px 12px" }}>
                    <span style={{
                      fontSize: 10, fontWeight: 700,
                      color: u.activo ? "#22c55e" : "#ef4444",
                      background: u.activo ? "rgba(34,197,94,0.12)" : "rgba(239,68,68,0.12)",
                      border: `1px solid ${u.activo ? "#22c55e" : "#ef4444"}33`,
                      borderRadius: 5, padding: "2px 7px",
                    }}>
                      {u.activo ? "Activo" : "Inactivo"}
                    </span>
                  </td>

                  <td style={{ padding: "8px 12px", color: "var(--t-text-muted)" }}>
                    {u.ultimo_acceso ? u.ultimo_acceso.slice(0, 16).replace("T", " ") : "Nunca"}
                  </td>

                  <td style={{ padding: "8px 12px" }}>
                    {u.username !== usuario?.username && (
                      <div style={{ display: "flex", gap: 6 }}>
                        <button
                          onClick={() => handleToggleActivo(u.username, !u.activo)}
                          title={u.activo ? "Desactivar" : "Activar"}
                          style={{
                            padding: "4px 8px", borderRadius: 7, border: "none",
                            cursor: "pointer", fontSize: 11,
                            background: u.activo ? "rgba(239,68,68,0.1)" : "rgba(34,197,94,0.1)",
                            color: u.activo ? "#ef4444" : "#22c55e",
                          }}
                        >
                          {u.activo ? <PowerOff size={12} /> : <Power size={12} />}
                        </button>
                        <button
                          onClick={() => handleDelete(u.username)}
                          title="Eliminar usuario"
                          style={{ ...btnDanger, padding: "4px 8px" }}
                        >
                          <Trash2 size={12} />
                        </button>
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {users.length === 0 && !loading && (
        <div style={{ color: "var(--t-text-muted)", fontSize: 12, textAlign: "center", padding: 20 }}>
          No se encontraron usuarios. Crea el primero con el botón de arriba.
        </div>
      )}
    </div>
  );
}

// ── 3. Kill Switch ────────────────────────────────────────────────────────────
function KillSwitchPanel({ token }) {
  const [estado,    setEstado]    = useState(null);
  const [loading,   setLoading]   = useState(false);
  const [msg,       setMsg]       = useState(null);
  const [gistUrl,   setGistUrl]   = useState("");
  const [savingUrl, setSavingUrl] = useState(false);
  const [showUrl,   setShowUrl]   = useState(false);
  const authHeaders = token ? { Authorization: `Bearer ${token}` } : {};

  const cargar = useCallback(async () => {
    try {
      const res  = await fetch(`${API_BASE}/kill-switch`, { headers: authHeaders });
      const data = await res.json();
      setEstado(data);
      setGistUrl(data.gist_url ?? "");
    } catch { /* API offline */ }
  }, [token]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { cargar(); }, [cargar]);

  const toggle = async () => {
    setLoading(true);
    setMsg(null);
    try {
      // estado.active es el campo real devuelto por el backend
      const nuevoEstado = !(estado?.active ?? true);
      const res = await fetch(`${API_BASE}/kill-switch/toggle`, {
        method:  "POST",
        headers: { "Content-Type": "application/json", ...authHeaders },
        body:    JSON.stringify({ activo: nuevoEstado }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail ?? "Error al cambiar kill switch.");
      setMsg({ type: "ok", text: `Sistema ${nuevoEstado ? "activado" : "bloqueado"}.` });
      setEstado(data);
    } catch (e) {
      setMsg({ type: "error", text: e.message });
    } finally {
      setLoading(false);
      setTimeout(() => setMsg(null), 3000);
    }
  };

  const guardarUrl = async () => {
    setSavingUrl(true);
    setMsg(null);
    try {
      const res  = await fetch(`${API_BASE}/kill-switch/url`, {
        method:  "POST",
        headers: { "Content-Type": "application/json", ...authHeaders },
        body:    JSON.stringify({ url: gistUrl.trim() }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail ?? "Error al guardar URL.");
      setMsg({ type: "ok", text: gistUrl.trim() ? "URL Gist guardada. Verificación en curso." : "Control remoto desactivado." });
      cargar();
    } catch (e) {
      setMsg({ type: "error", text: e.message });
    } finally {
      setSavingUrl(false);
      setTimeout(() => setMsg(null), 4000);
    }
  };

  const activo = estado?.active ?? true;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      {/* Estado visual */}
      <div style={{
        display: "flex", alignItems: "center", gap: 16,
        padding: "14px 18px", borderRadius: 12,
        background: activo ? "rgba(34,197,94,0.08)" : "rgba(239,68,68,0.08)",
        border: `1px solid ${activo ? "#22c55e44" : "#ef444444"}`,
      }}>
        <div style={{
          width: 12, height: 12, borderRadius: "50%",
          background: activo ? "#22c55e" : "#ef4444",
          boxShadow: `0 0 8px ${activo ? "#22c55e" : "#ef4444"}`,
          animation: activo ? "pulse 2s infinite" : "none",
        }} />
        <div style={{ flex: 1 }}>
          <div style={{ fontWeight: 700, fontSize: 13, color: activo ? "#22c55e" : "#ef4444" }}>
            {activo ? "Sistema ACTIVO — Agentes pueden ejecutar" : "Sistema BLOQUEADO — Ejecución detenida"}
          </div>
          <div style={{ fontSize: 10, color: "var(--t-text-muted)", marginTop: 2 }}>
            Fuente: {estado?.fuente ?? "—"}
            {estado?.gist_configurado && (
              <span style={{ marginLeft: 8, color: "var(--t-accent)" }}>
                · Gist configurado
              </span>
            )}
          </div>
        </div>
        <button onClick={toggle} disabled={loading} style={{
          ...(activo ? btnDanger : { ...btnPrimary, background: "rgba(34,197,94,0.1)",
              color: "#22c55e", borderColor: "#22c55e44" }),
        }}>
          {loading
            ? <RefreshCw size={13} style={{ animation: "spin 1s linear infinite" }} />
            : activo ? <PowerOff size={13} /> : <Power size={13} />
          }
          {activo ? "Bloquear" : "Activar"}
        </button>
      </div>

      <Msg msg={msg} />

      {/* Configurador URL Gist */}
      <div>
        <button
          onClick={() => setShowUrl(v => !v)}
          style={{ ...btnPrimary, fontSize: 11, padding: "5px 12px",
                   background: "transparent", borderColor: "var(--t-border)",
                   color: "var(--t-text-muted)" }}
        >
          <Globe size={12} />
          {showUrl ? "Ocultar" : "Configurar URL Gist (control remoto)"}
        </button>

        {showUrl && (
          <div style={{
            marginTop: 10, padding: "12px 14px", borderRadius: 10,
            background: "var(--t-bg-deep)", border: "1px solid var(--t-border)",
            display: "flex", flexDirection: "column", gap: 8,
          }}>
            <label style={{ fontSize: 11, color: "var(--t-text-muted)" }}>
              URL raw del Gist de GitHub (formato JSON: {"{ \"active\": true }"})
            </label>
            <div style={{ display: "flex", gap: 8 }}>
              <div style={{ position: "relative", flex: 1 }}>
                <Link size={12} style={{
                  position: "absolute", left: 9, top: "50%", transform: "translateY(-50%)",
                  color: "var(--t-text-muted)", pointerEvents: "none",
                }} />
                <input
                  value={gistUrl}
                  onChange={e => setGistUrl(e.target.value)}
                  placeholder="https://gist.githubusercontent.com/…/raw/…"
                  style={{ ...input, paddingLeft: 28 }}
                />
              </div>
              <button onClick={guardarUrl} disabled={savingUrl} style={btnPrimary}>
                {savingUrl
                  ? <RefreshCw size={12} style={{ animation: "spin 1s linear infinite" }} />
                  : <Check size={12} />
                }
                Guardar
              </button>
            </div>
            <p style={{ fontSize: 10, color: "var(--t-text-muted)", margin: 0, lineHeight: 1.5 }}>
              Deja vacío para desactivar el control remoto (el sistema siempre estará activo).
              El monitor verifica el Gist cada 5 minutos.
            </p>
          </div>
        )}
      </div>

      <div style={{ fontSize: 11, color: "var(--t-text-muted)", lineHeight: 1.6 }}>
        El Kill Switch bloquea <strong>inmediatamente</strong> la ejecución de todos los agentes.
        Los agentes en curso terminan su filtro actual y se detienen en el siguiente.
      </div>
      <style>{`@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.5} }`}</style>
    </div>
  );
}

// ── 4. Cambio de contraseña ───────────────────────────────────────────────────
function ChangePasswordSection({ token }) {
  const [username, setUsername]   = useState("");
  const [newPw,    setNewPw]      = useState("");
  const [loading,  setLoading]    = useState(false);
  const [msg,      setMsg]        = useState(null);
  const authHeaders = token ? { Authorization: `Bearer ${token}` } : {};

  const handleChange = async () => {
    if (!username || !newPw || newPw.length < 8) {
      setMsg({ type: "error", text: "Usuario y contraseña ≥8 caracteres requeridos." });
      return;
    }
    setLoading(true);
    setMsg(null);
    try {
      const res  = await fetch(`${API_BASE}/auth/cambiar-password`, {
        method:  "POST",
        headers: { "Content-Type": "application/json", ...authHeaders },
        body:    JSON.stringify({ username, nueva_password: newPw, token }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail ?? "Error al cambiar contraseña.");
      setMsg({ type: "ok", text: `Contraseña de "${username}" actualizada.` });
      setUsername(""); setNewPw("");
    } catch (e) {
      setMsg({ type: "error", text: e.message });
    } finally {
      setLoading(false);
      setTimeout(() => setMsg(null), 4000);
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <label style={{ fontSize: 11, color: "var(--t-text-muted)" }}>Usuario</label>
          <input
            value={username}
            onChange={e => setUsername(e.target.value)}
            placeholder="username"
            style={input}
          />
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <label style={{ fontSize: 11, color: "var(--t-text-muted)" }}>Nueva contraseña (≥8)</label>
          <input
            type="password"
            value={newPw}
            onChange={e => setNewPw(e.target.value)}
            placeholder="Mínimo 8 caracteres"
            style={input}
          />
        </div>
      </div>
      <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
        <button onClick={handleChange} disabled={loading} style={btnPrimary}>
          {loading ? <RefreshCw size={13} style={{ animation: "spin 1s linear infinite" }} /> : <Key size={13} />}
          {loading ? "Cambiando…" : "Cambiar contraseña"}
        </button>
        <Msg msg={msg} />
      </div>
    </div>
  );
}

// ── Descargador de Manual PDF ─────────────────────────────────────────────────
function ManualDownload() {
  const [empresa,     setEmpresa]     = useState("");
  const [descargando, setDescargando] = useState(false);

  const descargar = async () => {
    setDescargando(true);
    try {
      const param = empresa.trim() ? `?empresa=${encodeURIComponent(empresa.trim())}` : "";
      const res   = await fetch(`${API_BASE}/docs/manual${param}`);
      if (!res.ok) throw new Error("Error al generar el manual.");
      const blob  = await res.blob();
      const url   = URL.createObjectURL(blob);
      const a     = document.createElement("a");
      a.href      = url;
      a.download  = `Manual_AgentDesk${empresa.trim() ? "_" + empresa.trim() : ""}.pdf`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      alert(e.message);
    } finally {
      setDescargando(false);
    }
  };

  return (
    <div style={{ display: "flex", gap: 10, alignItems: "flex-end", flexWrap: "wrap" }}>
      <div style={{ display: "flex", flexDirection: "column", gap: 4, flex: 1, minWidth: 200 }}>
        <label style={{ fontSize: 11, color: "var(--t-text-muted)" }}>Nombre de empresa (opcional)</label>
        <input
          value={empresa}
          onChange={e => setEmpresa(e.target.value)}
          placeholder="ej. ACME Construcciones S.A."
          style={input}
        />
      </div>
      <button onClick={descargar} disabled={descargando} style={btnPrimary}>
        {descargando
          ? <RefreshCw size={13} style={{ animation: "spin 1s linear infinite" }} />
          : <Download size={13} />
        }
        {descargando ? "Generando…" : "Descargar Manual PDF"}
      </button>
    </div>
  );
}


// ── Panel principal ───────────────────────────────────────────────────────────
export default function SecurityPanel() {
  const { usuario } = useAuth();
  const token       = localStorage.getItem("token") || sessionStorage.getItem("token") || "";

  if (usuario?.role !== "admin") {
    return (
      <div style={{
        display: "flex", flexDirection: "column", alignItems: "center",
        justifyContent: "center", padding: "60px 0", gap: 12,
        color: "var(--t-text-muted)",
      }}>
        <Shield size={36} style={{ opacity: 0.25 }} />
        <p style={{ fontSize: 13, margin: 0 }}>
          Solo el administrador puede acceder a este panel de seguridad.
        </p>
        <p style={{ fontSize: 11, margin: 0, opacity: 0.6 }}>
          Tu rol actual: <strong>{usuario?.role ?? "desconocido"}</strong>
        </p>
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20, fontFamily: "inherit" }}>

      {/* 1. Hash bcrypt */}
      <div style={card}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <Shield size={16} style={{ color: "var(--t-accent)" }} />
          <h3 style={{ margin: 0, fontSize: 14, fontWeight: 700, color: "var(--t-text)" }}>
            Generador de Hash bcrypt
          </h3>
          <span style={{
            marginLeft: "auto", fontSize: 10, padding: "2px 8px", borderRadius: 6,
            background: "var(--t-bg-accent)", color: "var(--t-accent)",
          }}>
            client-side · jamás envía la contraseña
          </span>
        </div>
        <p style={{ margin: 0, fontSize: 12, color: "var(--t-text-muted)" }}>
          El hash se calcula localmente en el navegador con bcryptjs.
          Úsalo para MASTER_PASSWORD_HASH o al crear un usuario sin exponer la contraseña en texto claro.
        </p>
        <HashGenerator />
      </div>

      {/* 2. Gestión de usuarios */}
      <div style={card}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <Users size={16} style={{ color: "var(--t-accent)" }} />
          <h3 style={{ margin: 0, fontSize: 14, fontWeight: 700, color: "var(--t-text)" }}>
            Gestión de Usuarios RBAC
          </h3>
          <span style={{
            marginLeft: "auto", fontSize: 10, padding: "2px 8px", borderRadius: 6,
            background: "rgba(167,139,250,0.1)", color: "#a78bfa",
          }}>
            admin › supervisor › viewer
          </span>
        </div>
        <div style={{ display: "flex", gap: 10 }}>
          {["admin", "supervisor", "viewer"].map(r => (
            <div key={r} style={{ fontSize: 11, color: "var(--t-text-muted)" }}>
              <RolBadge rol={r} />{" "}
              {r === "admin" ? "Control total" : r === "supervisor" ? "Ejecución y reportes" : "Solo lectura"}
            </div>
          ))}
        </div>
        <UserManager token={token} />
      </div>

      {/* 3. Kill Switch */}
      <div style={card}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <Power size={16} style={{ color: "#ef4444" }} />
          <h3 style={{ margin: 0, fontSize: 14, fontWeight: 700, color: "var(--t-text)" }}>
            Kill Switch del Sistema
          </h3>
        </div>
        <KillSwitchPanel token={token} />
      </div>

      {/* 4. Cambio de contraseña */}
      <div style={card}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <Key size={16} style={{ color: "var(--t-accent)" }} />
          <h3 style={{ margin: 0, fontSize: 14, fontWeight: 700, color: "var(--t-text)" }}>
            Cambio de Contraseña
          </h3>
        </div>
        <p style={{ margin: 0, fontSize: 12, color: "var(--t-text-muted)" }}>
          Cambia la contraseña de cualquier usuario. Requiere rol admin.
        </p>
        <ChangePasswordSection token={token} />
      </div>

      {/* 5. Manual de Usuario PDF */}
      <div style={card}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <Download size={16} style={{ color: "var(--t-accent)" }} />
          <h3 style={{ margin: 0, fontSize: 14, fontWeight: 700, color: "var(--t-text)" }}>
            Manual de Usuario
          </h3>
          <span style={{
            marginLeft: "auto", fontSize: 10, padding: "2px 8px", borderRadius: 6,
            background: "rgba(34,197,94,0.1)", color: "#22c55e",
          }}>
            PDF · fpdf2
          </span>
        </div>
        <p style={{ margin: 0, fontSize: 12, color: "var(--t-text-muted)" }}>
          Genera un Manual de Usuario personalizado con el nombre de tu empresa.
          Incluye guía de la Curva S, gestión de roles y configuración del Kill Switch.
        </p>
        <ManualDownload />
      </div>

      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );
}
