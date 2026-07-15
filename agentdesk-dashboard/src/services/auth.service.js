import { API_BASE } from "./agent.service.js";

// ADR-0008: el access token expira en 30 min; la sesión se mantiene con un
// refresh token rotativo (cada canje emite un par nuevo e invalida el usado).

export async function initAuth() {
  const token = sessionStorage.getItem("agentdesk-jwt-token");
  if (!token) return null;
  try {
    const res = await fetch(`${API_BASE}/auth/verificar`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (res.ok) return await res.json();

    // Access expirado: intentar mantener la sesión vía refresh rotativo
    const renovado = await refreshToken();
    if (renovado?.token) {
      return { ok: true, username: renovado.username, role: renovado.role };
    }
    sessionStorage.removeItem("agentdesk-jwt-token");
    sessionStorage.removeItem("agentdesk-refresh-token");
    sessionStorage.removeItem("agentdesk-user");
    return null;
  } catch {
    return null;
  }
}

export async function refreshToken() {
  const refresh = sessionStorage.getItem("agentdesk-refresh-token");
  if (!refresh) return null;
  try {
    const res = await fetch(`${API_BASE}/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refresh }),
    });
    if (res.ok) {
      const data = await res.json();
      if (data.token) {
        sessionStorage.setItem("agentdesk-jwt-token", data.token);
      }
      if (data.refresh_token) {
        sessionStorage.setItem("agentdesk-refresh-token", data.refresh_token);
      }
      return data;
    }
    return null;
  } catch {
    return null;
  }
}
