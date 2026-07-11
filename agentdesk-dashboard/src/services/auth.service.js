import { API_BASE } from "./agent.service.js";

export async function initAuth() {
  const token = sessionStorage.getItem("agentdesk-jwt-token");
  if (!token) return null;
  try {
    const res = await fetch(`${API_BASE}/auth/verificar`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (res.ok) return await res.json();
    sessionStorage.removeItem("agentdesk-jwt-token");
    sessionStorage.removeItem("agentdesk-user");
    return null;
  } catch {
    return null;
  }
}

export async function refreshToken() {
  const token = sessionStorage.getItem("agentdesk-jwt-token");
  if (!token) return null;
  try {
    const res = await fetch(`${API_BASE}/auth/refresh`, {
      method:  "POST",
      headers: { Authorization: `Bearer ${token}` },
    });
    if (res.ok) {
      const data = await res.json();
      if (data.token) sessionStorage.setItem("agentdesk-jwt-token", data.token);
      return data;
    }
    return null;
  } catch {
    return null;
  }
}
