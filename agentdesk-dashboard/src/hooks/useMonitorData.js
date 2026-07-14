/**
 * useMonitorData.js — Puerto de Telemetría del Monitor (capa de lógica).
 *
 * Contrato agnóstico de la fuente de datos: expone `fuentes` (unidades
 * monitoreables: id, nombre, activo, estado, intervalo_min, ultimo_fetch,
 * proxima_ejecucion), `eventos` (feed en vivo del FilterLogHandler vía
 * WebSocket), `historial`, `alertas` y `acciones`.
 *
 * Hoy el único adaptador es REST + WebSocket contra el backend web
 * (/scheduler/tareas, /monitor/*, /ws/telemetria). Una futura fuente de
 * telemetría industrial (Modbus / OPC-UA) solo necesita poblar este mismo
 * contrato desde su propio adaptador — los componentes de UI no cambian.
 */
import { useState, useEffect, useCallback } from "react";
import { API_BASE, AgentService } from "../services/agent.service";
import { addNotification } from "../components/ui/NotificationSystem";

const MAX_EVENTOS = 200;

async function putFuente(id, cambios) {
  const r = await fetch(`${API_BASE}/scheduler/tareas/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(cambios),
  });
  return r.json();
}

export function useMonitorData({ pollMs = 15000 } = {}) {
  const [fuentes, setFuentes] = useState([]);
  const [cargando, setCargando] = useState(true);
  const [eventos, setEventos] = useState([]);
  const [historial, setHistorial] = useState([]);
  const [alertas, setAlertas] = useState([]);

  const recargar = useCallback(() => {
    fetch(`${API_BASE}/scheduler/tareas`)
      .then((r) => r.json())
      .then((d) => {
        setFuentes(d.tareas ?? []);
        setCargando(false);
      })
      .catch(() => setCargando(false));
  }, []);

  // Sondeo periódico del estado de las fuentes
  useEffect(() => {
    recargar();
    const id = setInterval(recargar, pollMs);
    return () => clearInterval(id);
  }, [recargar, pollMs]);

  // Feed en vivo: eventos del FilterLogHandler emitidos por /ws/telemetria
  useEffect(
    () =>
      AgentService.onWsMessage((msg) => {
        setEventos((prev) => [
          ...prev.slice(-(MAX_EVENTOS - 1)),
          { ...msg, _ts: Date.now() },
        ]);
        if (
          [
            "monitor_ejecutando",
            "monitor_completado",
            "monitor_error",
            "scheduler_actualizado",
          ].includes(msg.tipo)
        ) {
          recargar();
          if (msg.tipo === "monitor_completado")
            addNotification({
              message: `Monitor: ${msg.nombre} actualizado`,
              type: "success",
            });
          if (msg.tipo === "monitor_error")
            addNotification({
              message: `Monitor error: ${msg.error || ""}`,
              type: "error",
            });
        }
      }),
    [recargar],
  );

  const alternar = useCallback(async (fuente) => {
    const r = await putFuente(fuente.id, { activo: !fuente.activo });
    if (r.ok) {
      setFuentes(r.tareas);
      addNotification({
        message: fuente.activo ? "Monitor pausado" : "Monitor activado",
        type: "success",
      });
    }
  }, []);

  const cambiarFrecuencia = useCallback(async (fuente, min) => {
    const r = await putFuente(fuente.id, { intervalo_min: min });
    if (r.ok) {
      setFuentes(r.tareas);
      addNotification({
        message: `Intervalo actualizado: ${min} min`,
        type: "success",
      });
    }
  }, []);

  const ejecutarAhora = useCallback(
    async (fuente) => {
      await fetch(`${API_BASE}/scheduler/tareas/${fuente.id}/ejecutar`, {
        method: "POST",
      });
      addNotification({
        message: `Ejecutando: ${fuente.nombre}...`,
        type: "info",
      });
      setTimeout(recargar, 2000);
    },
    [recargar],
  );

  const cargarHistorial = useCallback(() => {
    fetch(`${API_BASE}/monitor/historial?limit=50`)
      .then((r) => r.json())
      .then((d) => setHistorial(d.datos || []))
      .catch(() => {});
  }, []);

  const cargarAlertas = useCallback(() => {
    fetch(`${API_BASE}/monitor/alertas`)
      .then((r) => r.json())
      .then((d) => setAlertas(d.alertas || []))
      .catch(() => {});
  }, []);

  const limpiarEventos = useCallback(() => setEventos([]), []);

  return {
    fuentes,
    cargando,
    eventos,
    historial,
    alertas,
    acciones: {
      recargar,
      alternar,
      cambiarFrecuencia,
      ejecutarAhora,
      cargarHistorial,
      cargarAlertas,
      limpiarEventos,
    },
  };
}
