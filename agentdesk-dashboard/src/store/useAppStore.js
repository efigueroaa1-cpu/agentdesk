import { create } from "zustand";
import { API_BASE } from "../services/agent.service.js";

export const useAppStore = create((set, get) => ({
  alertas: [],
  sistemaKpis: null,
  inicializado: false,

  inicializar: async () => {
    if (get().inicializado) return;
    set({ inicializado: true });
    try {
      const token = sessionStorage.getItem("agentdesk-jwt-token");
      const headers = token ? { Authorization: `Bearer ${token}` } : {};
      const res = await fetch(`${API_BASE}/sistema/kpis`, { headers });
      if (res.ok) {
        const data = await res.json();
        set({ sistemaKpis: data });
      }
    } catch {
      /* ignore */
    }
  },

  agregarAlerta: (alerta) =>
    set((s) => ({
      alertas: [
        {
          ...alerta,
          id: Date.now(),
          leida: false,
          ts: new Date().toISOString(),
        },
        ...s.alertas,
      ].slice(0, 100),
    })),

  marcarLeidas: () =>
    set((s) => ({ alertas: s.alertas.map((a) => ({ ...a, leida: true })) })),
}));

export const useAlertasSinLeer = () =>
  useAppStore((s) => s.alertas.filter((a) => !a.leida).length);
