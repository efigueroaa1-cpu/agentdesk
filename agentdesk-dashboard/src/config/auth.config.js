/**
 * auth.config.js — Configuración de autenticación del dashboard AgentDesk.
 *
 * Las credenciales viven SOLO en el backend (bcrypt + JWT + refresh tokens,
 * ver ADR-0008); este archivo no contiene usuarios ni contraseñas.
 *
 * El Kill Switch se gestiona por licencia RSA local en el backend
 * (ADR-0022, license.key) — sin URLs de control externas.
 */
export const AUTH_CONFIG = {
  IS_LOCKED: false,
  LOCK_MESSAGE: "Sistema temporalmente bloqueado. Contacta al administrador.",

  SESSION_KEY: "agentdesk-session",
  SESSION_DURATION: 8 * 60 * 60 * 1000, // 8 horas
};
