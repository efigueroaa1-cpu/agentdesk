import { createContext, useContext, useState, useEffect } from "react";
import { API_BASE } from "../services/agent.service.js";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [usuario,         setUsuario]         = useState(null);
  const [estaAutenticado, setEstaAutenticado] = useState(false);
  const [cargando,        setCargando]        = useState(true);
  const [isKilled,        setIsKilled]        = useState(false);
  const [killMsg,         setKillMsg]         = useState("");

  useEffect(() => {
    const token    = sessionStorage.getItem("agentdesk-jwt-token");
    const savedRaw = sessionStorage.getItem("agentdesk-user");
    if (token && savedRaw) {
      try {
        const saved = JSON.parse(savedRaw);
        setUsuario(saved);
        setEstaAutenticado(true);
      } catch { /* ignore */ }
    }

    fetch(`${API_BASE}/kill-switch`)
      .then(r => r.ok ? r.json() : null)
      .then(data => {
        if (data && data.active === false) {
          setIsKilled(true);
          setKillMsg(data.fuente === "gist"
            ? "Sistema desactivado remotamente. Contacta al administrador."
            : "Sistema bloqueado. Contacta al administrador.");
        }
      })
      .catch(() => {})
      .finally(() => setCargando(false));
  }, []);

  const login = (username, password) => {
    fetch(`${API_BASE}/auth/login`, {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify({ username, password }),
    })
      .then(r => r.ok ? r.json() : Promise.reject("bad"))
      .then(data => {
        if (!data.token) throw new Error("no token");
        sessionStorage.setItem("agentdesk-jwt-token", data.token);
        sessionStorage.setItem("agentdesk-user",      JSON.stringify(data));
        setUsuario(data);
        setEstaAutenticado(true);
      })
      .catch(() => {
        // Login failure: state stays as-is, Login.jsx will re-enable the button
      });
    // Returns a truthy Promise so Login.jsx's `if (!login(...))` is always false
    // (success/failure communicated via state update → re-render)
    return Promise.resolve(true);
  };

  const logout = () => {
    setUsuario(null);
    setEstaAutenticado(false);
    sessionStorage.removeItem("agentdesk-jwt-token");
    sessionStorage.removeItem("agentdesk-user");
  };

  return (
    <AuthContext.Provider value={{ usuario, estaAutenticado, cargando, isKilled, killMsg, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
