import { createContext, useContext, useState, useEffect } from "react";
import { API_BASE } from "../services/agent.service.js";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [usuario, setUsuario] = useState(null);
  const [estaAutenticado, setEstaAutenticado] = useState(false);
  const [cargando, setCargando] = useState(true);
  const [isKilled, setIsKilled] = useState(false);
  const [killMsg, setKillMsg] = useState("");

  useEffect(() => {
    const token = sessionStorage.getItem("agentdesk-jwt-token");
    const savedRaw = sessionStorage.getItem("agentdesk-user");
    if (token && savedRaw) {
      try {
        const saved = JSON.parse(savedRaw);
        setUsuario(saved);
        setEstaAutenticado(true);
      } catch {
        /* ignore */
      }
    }

    fetch(`${API_BASE}/kill-switch`)
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (data && data.active === false) {
          setIsKilled(true);
          setKillMsg(
            data.fuente === "licencia_invalida"
              ? `Licencia inválida (${data.motivo}). Contacta al administrador.`
              : "Sistema bloqueado. Contacta al administrador.",
          );
        }
      })
      .catch(() => {})
      .finally(() => setCargando(false));
  }, []);

  const login = async (username, password) => {
    try {
      const r = await fetch(`${API_BASE}/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });
      if (!r.ok) return false;
      const data = await r.json();
      if (!data.token) return false;
      sessionStorage.setItem("agentdesk-jwt-token", data.token);
      if (data.refresh_token) {
        sessionStorage.setItem("agentdesk-refresh-token", data.refresh_token);
      }
      sessionStorage.setItem("agentdesk-user", JSON.stringify(data));
      setUsuario(data);
      setEstaAutenticado(true);
      return true;
    } catch {
      return false;
    }
  };

  const logout = () => {
    setUsuario(null);
    setEstaAutenticado(false);
    sessionStorage.removeItem("agentdesk-jwt-token");
    sessionStorage.removeItem("agentdesk-refresh-token");
    sessionStorage.removeItem("agentdesk-user");
  };

  return (
    <AuthContext.Provider
      value={{
        usuario,
        estaAutenticado,
        cargando,
        isKilled,
        killMsg,
        login,
        logout,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
