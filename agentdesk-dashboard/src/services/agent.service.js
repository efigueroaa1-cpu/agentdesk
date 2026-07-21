/**
 * AgentService — capa de comunicación unificada.
 *
 * Dos canales:
 *   1. Tauri invoke/listen  → comandos run/stop hacia el backend Rust (desktop)
 *   2. FastAPI REST + WS    → CRUD de agentes y telemetría del Orquestador Python
 *
 * La URL de la API se configura en API_BASE.
 * En producción empaquetada se puede ajustar vía variable de entorno.
 */

// ── Configuración ─────────────────────────────────────────────────────────────
// Use 127.0.0.1 explicitly — on Windows, "localhost" can resolve to ::1 (IPv6)
// which fails when the Python backend only listens on 127.0.0.1 (IPv4).
export const API_BASE = import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8000";
const WS_URL = API_BASE.replace(/^http/, "ws") + "/ws/telemetria";

// Tauri v2 injects __TAURI_INTERNALS__ (not __TAURI__ which requires withGlobalTauri).
const IS_TAURI =
  typeof window !== "undefined" &&
  ("__TAURI_INTERNALS__" in window || "__TAURI__" in window);

// ── Importación lazy de Tauri ──────────────────────────────────────────────────
let _invoke = null;
let _listen = null;

async function getTauriApis() {
  if (!IS_TAURI || _invoke) return;
  const core = await import("@tauri-apps/api/core");
  const event = await import("@tauri-apps/api/event");
  _invoke = core.invoke;
  _listen = event.listen;
}

async function tauriInvoke(cmd, args = {}) {
  await getTauriApis();
  if (IS_TAURI && _invoke) return _invoke(cmd, args);
  return mockInvoke(cmd, args);
}

// ── Mocks offline ──────────────────────────────────────────────────────────────
const _mockRunning = new Set();

async function mockInvoke(cmd, args) {
  await new Promise((r) => setTimeout(r, 200));
  if (cmd === "run_agent") {
    if (_mockRunning.has(args.id)) throw `Agente '${args.id}' ya en ejecución.`;
    _mockRunning.add(args.id);
    return null;
  }
  if (cmd === "stop_agent") {
    _mockRunning.delete(args.id);
    return null;
  }
  throw `Mock: comando desconocido '${cmd}'`;
}

// ── Helper REST con JWT automático ────────────────────────────────────────────
function _getToken() {
  return sessionStorage.getItem("agentdesk-jwt-token") || "";
}

async function apiFetch(path, options = {}) {
  const token = _getToken();
  const headers = {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(options.headers || {}),
  };
  const res = await fetch(`${API_BASE}${path}`, { ...options, headers });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw body.error ?? `HTTP ${res.status}`;
  }
  return res.json();
}

// ── WebSocket singleton ────────────────────────────────────────────────────────
let _ws = null;
let _wsHandlers = []; // lista de callbacks suscritos

function _wsUrl() {
  // Incluir JWT como query param: el browser WebSocket API no admite headers.
  // El servidor extrae el rol del token para filtrar mensajes RBAC.
  const token = _getToken();
  return token ? `${WS_URL}?token=${encodeURIComponent(token)}` : WS_URL;
}

function ensureWS() {
  if (_ws && _ws.readyState < 2) return; // OPEN o CONNECTING

  _ws = new WebSocket(_wsUrl());

  _ws.onmessage = (e) => {
    try {
      const msg = JSON.parse(e.data);
      _wsHandlers.forEach((fn) => fn(msg));
    } catch {
      /* ignorar mensajes malformados */
    }
  };

  _ws.onclose = () => {
    // Reconectar tras 3 s si hay handlers suscritos
    if (_wsHandlers.length > 0) setTimeout(ensureWS, 3000);
  };

  // Keepalive cada 25 s
  const ping = setInterval(() => {
    if (_ws?.readyState === 1) _ws.send(JSON.stringify({ ping: true }));
    else clearInterval(ping);
  }, 25_000);
}

// ── API pública ────────────────────────────────────────────────────────────────
export const AgentService = {
  // ── Tauri: ejecutar / detener proceso Python ───────────────────────────────
  run: (id) => tauriInvoke("run_agent", { id }),
  stop: (id) => tauriInvoke("stop_agent", { id }),

  // ── FastAPI REST ───────────────────────────────────────────────────────────

  /** Lista todos los agentes registrados en el Orquestador Python */
  getAll: () => apiFetch("/agentes"),

  /** Crea un nuevo agente (CREAR_AGENTE via CommandBridge) */
  create: (payload) =>
    apiFetch("/agentes", { method: "POST", body: JSON.stringify(payload) }),

  /** Actualiza parámetros de un agente existente */
  update: (agentId, payload) =>
    apiFetch(`/agentes/${agentId}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    }),

  /** Elimina un agente del sistema */
  delete: (agentId) => apiFetch(`/agentes/${agentId}`, { method: "DELETE" }),

  /** Lista los modelos Gemini disponibles */
  getModelos: () => apiFetch("/modelos"),

  /** Ejecuta realizar_tarea() en un agente y devuelve el reporte */
  ejecutar: (agentId, tarea = "reporte_ventas") =>
    apiFetch(`/agentes/${agentId}/ejecutar`, {
      method: "POST",
      body: JSON.stringify({ tarea }),
    }),

  /** Verifica que el servidor FastAPI esté activo */
  health: () => apiFetch("/health"),

  // ── WebSocket: telemetría + eventos en tiempo real ─────────────────────────

  /**
   * Suscribe un handler a todos los mensajes del WebSocket.
   * Retorna una función de limpieza (unsubscribe).
   *
   * Tipos de mensaje:
   *   { tipo: "telemetria",    filtro, agente, status, duracion_s }
   *   { tipo: "agente_creado", nombre, area }
   *   { tipo: "conexion",      mensaje }
   */
  onWsMessage: (handler) => {
    ensureWS();
    _wsHandlers.push(handler);
    return () => {
      _wsHandlers = _wsHandlers.filter((h) => h !== handler);
      if (_wsHandlers.length === 0 && _ws) {
        _ws.close();
        _ws = null;
      }
    };
  },

  // ── Tauri: eventos de proceso (run/stop streaming) ─────────────────────────
  onLog: async (handler) => {
    await getTauriApis();
    if (IS_TAURI && _listen)
      return _listen("agent_log", (e) => handler(e.payload));
    return () => {};
  },
  onStarted: async (handler) => {
    await getTauriApis();
    if (IS_TAURI && _listen)
      return _listen("agent_started", (e) => handler(e.payload));
    return () => {};
  },
  onStopped: async (handler) => {
    await getTauriApis();
    if (IS_TAURI && _listen)
      return _listen("agent_stopped", (e) => handler(e.payload));
    return () => {};
  },

  // ── Métricas de hardware (emitidas por sysinfo cada 2s) ───────────────────
  // Returns a sync cleanup function immediately (the async subscription is
  // set up internally). This prevents "unsubHW is not a function" errors
  // when callers don't await the return value.
  onHardwareMetrics: (handler) => {
    let iv = null;
    let unlisten = null;
    let cancelled = false;

    getTauriApis()
      .then(() => {
        if (cancelled) return;
        if (IS_TAURI && _listen) {
          _listen("hardware_metrics", (e) => handler(e.payload))
            .then((u) => {
              unlisten = u;
            })
            .catch(() => {});
        } else {
          iv = setInterval(
            () =>
              handler({
                cpu_pct: Math.round(20 + Math.random() * 60),
                ram_used_mb: Math.round(1024 + Math.random() * 2048),
                ram_total_mb: 8192,
                ram_pct: Math.round(30 + Math.random() * 40),
              }),
            2000,
          );
        }
      })
      .catch(() => {});

    // Sync cleanup — always a function, never a Promise
    return () => {
      cancelled = true;
      if (unlisten) unlisten();
      if (iv) clearInterval(iv);
    };
  },

  // ── Notificaciones nativas (tauri-plugin-notification) ────────────────────
  sendNotification: async (title, body) => {
    await getTauriApis();
    if (!IS_TAURI || !_invoke) return;
    try {
      await _invoke("plugin:notification|notify", { options: { title, body } });
    } catch {
      /* sin permisos o plugin no disponible */
    }
  },

  // ── Usuarios (Tauri invoke -> Rust lib.rs) ─────────────────────────────────
  loginUser: (username, password) =>
    tauriInvoke("login_user", { username, password }),
  listUsers: (callerRole) => tauriInvoke("list_users", { callerRole }),
  createUser: (username, password, role, callerRole) =>
    tauriInvoke("create_user", { username, password, role, callerRole }),
  changePassword: (username, oldPassword, newPassword) =>
    tauriInvoke("change_password", { username, oldPassword, newPassword }),
  deleteUser: (username, callerRole) =>
    tauriInvoke("delete_user", { username, callerRole }),
};
