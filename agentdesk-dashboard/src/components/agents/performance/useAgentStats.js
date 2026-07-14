/**
 * useAgentStats.js — Hook de estado del rendimiento de agentes.
 *
 * Carga la lista de agentes, acumula estadísticas escuchando el WebSocket
 * del backend (agente_ejecutando / tarea_completada / tarea_abortada /
 * tarea_error / todos_ejecutando) y las persiste en localStorage.
 */
import { useState, useEffect, useRef } from "react";
import { AgentService, API_BASE } from "../../../services/agent.service";
import { cargarStats, guardarStats, statsVacias } from "./statsUtils";

export function useAgentStats() {
  const [agentes, setAgentes] = useState([]);
  const [stats, setStats] = useState(cargarStats);
  const [running, setRunning] = useState({});
  const [now, setNow] = useState(Date.now());
  const statsRef = useRef(stats);
  const runningRef = useRef(running);
  statsRef.current = stats;
  runningRef.current = running;

  // Reloj para el tiempo transcurrido de tareas activas
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  // Carga inicial de agentes + inicialización de stats para ids nuevos
  useEffect(() => {
    fetch(`${API_BASE}/agentes`)
      .then((r) => r.json())
      .then((data) => {
        const lista = data.agentes ?? [];
        setAgentes(lista);
        setStats((prev) => {
          const next = { ...prev };
          lista.forEach((a) => {
            if (!next[a.id]) next[a.id] = statsVacias();
          });
          guardarStats(next);
          return next;
        });
      })
      .catch(() => {});
  }, []);

  // Eventos del WebSocket del backend
  useEffect(
    () =>
      AgentService.onWsMessage((msg) => {
        const id = msg.agente_id;
        if (!id) return;

        if (msg.tipo === "agente_ejecutando") {
          setRunning((prev) => ({
            ...prev,
            [id]: {
              tarea: msg.tarea || "Tarea en curso",
              inicio: Date.now(),
              estado: "ACTIVO",
            },
          }));
          setStats((prev) => {
            const next = {
              ...prev,
              [id]: {
                ...(prev[id] || statsVacias()),
                tarea_inicio: Date.now(),
              },
            };
            guardarStats(next);
            return next;
          });
        }

        if (msg.tipo === "tarea_completada") {
          const inicio =
            runningRef.current[id]?.inicio ??
            statsRef.current[id]?.tarea_inicio;
          const durMs = inicio ? Date.now() - inicio : null;
          setRunning((prev) => {
            const next = { ...prev };
            delete next[id];
            return next;
          });
          setStats((prev) => {
            const s = { ...(prev[id] || statsVacias()) };
            s.ok++;
            s.ultima_ts = Date.now();
            s.ultimasTareas = [...(s.ultimasTareas || []).slice(-14), "ok"];
            if (durMs && durMs > 100 && durMs < 300000) {
              s.latencias = [...(s.latencias || []).slice(-19), durMs / 1000];
            }
            const next = { ...prev, [id]: s };
            guardarStats(next);
            return next;
          });
        }

        if (msg.tipo === "tarea_abortada" || msg.tipo === "tarea_error") {
          setRunning((prev) => {
            const next = { ...prev };
            delete next[id];
            return next;
          });
          setStats((prev) => {
            const s = { ...(prev[id] || statsVacias()) };
            s.fail++;
            s.ultima_ts = Date.now();
            s.ultimasTareas = [...(s.ultimasTareas || []).slice(-14), "fail"];
            const next = { ...prev, [id]: s };
            guardarStats(next);
            return next;
          });
        }

        if (msg.tipo === "todos_ejecutando") {
          const ids = msg.agentes ?? [];
          setRunning((prev) => {
            const next = { ...prev };
            ids.forEach((aid) => {
              next[aid] = {
                tarea: "Pipeline completo",
                inicio: Date.now(),
                estado: "ACTIVO",
              };
            });
            return next;
          });
        }
      }),
    [],
  );

  function resetear() {
    const limpio = {};
    agentes.forEach((a) => {
      limpio[a.id] = statsVacias();
    });
    guardarStats(limpio);
    setStats(limpio);
    setRunning({});
  }

  return { agentes, stats, running, now, resetear };
}
