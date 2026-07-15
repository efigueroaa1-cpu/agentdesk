/**
 * auth.config.js — Configuración de autenticación del dashboard AgentDesk.
 *
 * Las credenciales viven SOLO en el backend (bcrypt + JWT + refresh tokens,
 * ver ADR-0008); este archivo no contiene usuarios ni contraseñas.
 *
 * KILL SWITCH REMOTO:
 *   1. Crea un Gist público en https://gist.github.com con el contenido:
 *      { "active": true }
 *   2. Obtén la URL raw del Gist (botón "Raw") — termina en .json
 *   3. Pégala en KILL_SWITCH_URL abajo
 *   4. Para bloquear el sistema: cambia el Gist a { "active": false }
 *   5. También configurar KILL_SWITCH_GIST_URL en %APPDATA%\AgentDesk\.env
 *      para que el backend Python también verifique el kill switch.
 */
export const AUTH_CONFIG = {
  IS_LOCKED: false,
  LOCK_MESSAGE: "Sistema temporalmente bloqueado. Contacta al administrador.",

  // Kill Switch remoto — pegar URL raw del Gist de GitHub:
  // Ej: "https://gist.githubusercontent.com/TU_USUARIO/ID/raw/agentdesk.json"
  KILL_SWITCH_URL: "",

  SESSION_KEY: "agentdesk-session",
  SESSION_DURATION: 8 * 60 * 60 * 1000, // 8 horas
};
