import { useState, useEffect } from "react";
import { API_BASE } from "../services/agent.service.js";

const _defaults = {
  empresa:          "AgentDesk Professional",
  app_name:         "AgentDesk",
  logo_texto:       "AD",
  tagline:          "Inteligencia Operacional",
  color_primario:   "#00d4ff",
  color_secundario: "#0066cc",
};

let _cache = null;

export function useBranding() {
  const [branding, setBranding] = useState(_cache ?? _defaults);

  useEffect(() => {
    if (_cache) return;
    fetch(`${API_BASE}/branding`)
      .then(r => r.ok ? r.json() : null)
      .then(data => {
        if (data && Object.keys(data).length > 0) {
          _cache = { ..._defaults, ...data };
          setBranding(_cache);
        }
      })
      .catch(() => {});
  }, []);

  return branding;
}
