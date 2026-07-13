/**
 * MonitorPanel.jsx — "Monitor Web": cinco pestañas sobre datos monitoreados
 * en tiempo real desde fuentes externas.
 *   - Automático: agente de monitoreo en segundo plano (`/scheduler/tareas`).
 *   - Ligas & Tablas: fútbol vía TheSportsDB (`/monitor/equipos-preset`,
 *     `/monitor/liga/{id}`).
 *   - Energía: solar/eólico, demanda y precio spot (`/monitor/fetch`).
 *   - Historial: datos crudos persistidos en SQLite (`/monitor/historial`).
 *   - Alertas: alertas generadas por el monitor (`/monitor/alertas`).
 *
 * Reconstruido desde el bundle de producción (react_dist/assets/index-CRDO1T5r.js,
 * funciones `Fw`/`Mw`/`Lw`): el fuente original de este componente no estaba
 * versionado.
 */
import { useState, useEffect, useCallback, useRef } from "react";
import { RefreshCw, Play } from "../../icons.js";
import { API_BASE, AgentService } from "../../services/agent.service";
import { addNotification } from "../ui/NotificationSystem";

const RACHA_ICON = { W: "🟢", D: "🟡", L: "🔴", w: "🟢", d: "🟡", l: "🔴" };
const ALERTA_COLOR = { info: "#00d4ff", warn: "#f59e0b", critico: "#ff2d55" };
const TAREA_ESTADO = {
  ok: { color: "#0a0e1a", bg: "#00ff9d", label: "✓ Completado" },
  ejecutando: { color: "#0a0e1a", bg: "#00d4ff", label: "⟳ Ejecutando..." },
  error: { color: "#ffffff", bg: "#ff2d55", label: "✗ Error" },
  pendiente: {
    color: "#94a3b8",
    bg: "rgba(100,116,139,.2)",
    label: "◷ Pendiente",
  },
};
const INTERVALOS = [
  { label: "15 min", val: 15 },
  { label: "30 min", val: 30 },
  { label: "1 hora", val: 60 },
  { label: "3 horas", val: 180 },
  { label: "6 horas", val: 360 },
  { label: "12 horas", val: 720 },
  { label: "24 horas", val: 1440 },
];
function fmtProxima(iso) {
  if (!iso) return "—";
  const s = Math.round((new Date(iso + "Z") - Date.now()) / 1000);
  if (s <= 0) return "¡Ahora!";
  if (s < 60) return `en ${s}s`;
  if (s < 3600) return `en ${Math.round(s / 60)}min`;
  return `en ${Math.round(s / 3600)}h`;
}
function fmtUltima(iso) {
  return iso
    ? new Date(iso + "Z").toLocaleString("es", {
        day: "2-digit",
        month: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "Nunca";
}
function colorPosicion(pos, total) {
  return pos <= 4
    ? "#00d4ff"
    : pos <= 6
      ? "#00ff9d"
      : pos >= total - 2
        ? "#ff2d55"
        : "var(--t-text-muted)";
}

function Cargando({ texto }) {
  return (
    <div
      style={{
        padding: "2rem",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        gap: 10,
        color: "var(--t-text-muted)",
        fontSize: ".85rem",
      }}
    >
      <RefreshCw
        size={18}
        style={{
          animation: "spin .8s linear infinite",
          color: "var(--t-accent)",
        }}
      />
      {texto}
      <style>{"@keyframes spin{to{transform:rotate(360deg)}}"}</style>
    </div>
  );
}

// ── Pestaña: Automático ──────────────────────────────────────────────────────
function TabAutomatico() {
  const [tareas, setTareas] = useState([]);
  const [cargando, setCargando] = useState(true);
  const intervalRef = useRef(null);

  const cargar = useCallback(() => {
    fetch(`${API_BASE}/scheduler/tareas`)
      .then((r) => r.json())
      .then((d) => {
        setTareas(d.tareas ?? []);
        setCargando(false);
      })
      .catch(() => setCargando(false));
  }, []);

  useEffect(() => {
    cargar();
    intervalRef.current = setInterval(cargar, 15000);
    return () => clearInterval(intervalRef.current);
  }, [cargar]);

  useEffect(
    () =>
      AgentService.onWsMessage((msg) => {
        if (
          [
            "monitor_ejecutando",
            "monitor_completado",
            "monitor_error",
            "scheduler_actualizado",
          ].includes(msg.tipo)
        ) {
          cargar();
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
    [cargar],
  );

  async function toggle(tarea) {
    const r = await fetch(`${API_BASE}/scheduler/tareas/${tarea.id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ activo: !tarea.activo }),
    }).then((res) => res.json());
    if (r.ok) {
      setTareas(r.tareas);
      addNotification({
        message: tarea.activo ? "Monitor pausado" : "Monitor activado",
        type: "success",
      });
    }
  }
  async function cambiarIntervalo(tarea, min) {
    const r = await fetch(`${API_BASE}/scheduler/tareas/${tarea.id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ intervalo_min: min }),
    }).then((res) => res.json());
    if (r.ok) {
      setTareas(r.tareas);
      addNotification({
        message: `Intervalo actualizado: ${min} min`,
        type: "success",
      });
    }
  }
  async function ejecutarAhora(tarea) {
    await fetch(`${API_BASE}/scheduler/tareas/${tarea.id}/ejecutar`, {
      method: "POST",
    });
    addNotification({
      message: `Ejecutando: ${tarea.nombre}...`,
      type: "info",
    });
    setTimeout(cargar, 2000);
  }

  const activos = tareas.filter((t) => t.activo).length;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "12px 18px",
          borderRadius: 14,
          background: "rgba(0,212,255,.05)",
          border: "1px solid rgba(0,212,255,.2)",
          flexWrap: "wrap",
          gap: "1rem",
        }}
      >
        <div>
          <div
            style={{
              fontWeight: 800,
              fontSize: ".95rem",
              color: "var(--t-text)",
            }}
          >
            🤖 Agente de Monitoreo Automático
          </div>
          <div
            style={{
              fontSize: ".75rem",
              color: "var(--t-text-muted)",
              marginTop: 3,
            }}
          >
            {activos} de {tareas.length} monitores activos · corre en segundo
            plano
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <div
            style={{
              width: 10,
              height: 10,
              borderRadius: "50%",
              flexShrink: 0,
              background: activos > 0 ? "#00ff9d" : "#334155",
              boxShadow: activos > 0 ? "0 0 10px #00ff9d" : "none",
            }}
          />
          <span
            style={{
              fontSize: ".78rem",
              color: activos > 0 ? "#00ff9d" : "#64748b",
              fontWeight: 600,
            }}
          >
            {activos > 0 ? "Sistema activo" : "Sistema inactivo"}
          </span>
          <button
            onClick={cargar}
            style={{
              padding: "4px 10px",
              borderRadius: 20,
              border: "1px solid var(--t-border)",
              background: "transparent",
              color: "var(--t-text-muted)",
              cursor: "pointer",
              fontFamily: "inherit",
              fontSize: ".72rem",
            }}
          >
            <RefreshCw size={12} />
          </button>
        </div>
      </div>

      <div
        style={{
          padding: "10px 16px",
          borderRadius: 12,
          fontSize: ".75rem",
          background: "var(--t-bg)",
          border: "1px solid var(--t-border)",
          color: "var(--t-text-muted)",
          lineHeight: 1.8,
        }}
      >
        <strong style={{ color: "var(--t-accent)" }}>Flujo de datos:</strong>{" "}
        Monitor Web → <span style={{ color: "#f59e0b" }}>Datos Crudos</span> →
        SQLite (sin filtros) →{" "}
        <span style={{ color: "#00d4ff" }}>Agente IA</span> →{" "}
        <span style={{ color: "#a78bfa" }}>Pipeline</span> →{" "}
        <span style={{ color: "#00ff9d" }}>Informe Verificado</span>
        <br />
        Los datos reales NO pasan por pipeline. Solo el análisis del agente es
        validado.
      </div>

      {cargando ? (
        <Cargando texto="" />
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: ".7rem" }}>
          {tareas.map((t) => {
            const est = TAREA_ESTADO[t.estado] ?? TAREA_ESTADO.pendiente;
            return (
              <div
                key={t.id}
                style={{
                  padding: "1.1rem 1.4rem",
                  borderRadius: 14,
                  border: `2px solid ${t.activo ? "#00d4ff" : "#334155"}`,
                  background: t.activo ? "rgba(0,20,40,.4)" : "var(--t-bg)",
                }}
              >
                <div
                  style={{
                    display: "flex",
                    alignItems: "flex-start",
                    justifyContent: "space-between",
                    gap: "1rem",
                    flexWrap: "wrap",
                  }}
                >
                  <div
                    style={{ display: "flex", alignItems: "center", gap: 12 }}
                  >
                    <span style={{ fontSize: 26 }}>{t.icono}</span>
                    <div>
                      <div
                        style={{
                          fontWeight: 800,
                          fontSize: "1rem",
                          color: "var(--t-text)",
                        }}
                      >
                        {t.nombre}
                      </div>
                      <div
                        style={{
                          display: "flex",
                          gap: 8,
                          marginTop: 6,
                          flexWrap: "wrap",
                          alignItems: "center",
                        }}
                      >
                        <span
                          style={{
                            padding: "3px 11px",
                            borderRadius: 20,
                            fontSize: ".72rem",
                            fontWeight: 800,
                            background: est.bg,
                            color: est.color,
                          }}
                        >
                          {est.label}
                        </span>
                        <span
                          style={{
                            fontSize: ".74rem",
                            color: "var(--t-text-muted)",
                            fontWeight: 500,
                          }}
                        >
                          Última:{" "}
                          <strong style={{ color: "var(--t-text)" }}>
                            {fmtUltima(t.ultimo_fetch)}
                          </strong>
                        </span>
                        {t.activo && (
                          <span
                            style={{
                              fontSize: ".74rem",
                              color: "#00d4ff",
                              fontWeight: 600,
                            }}
                          >
                            Próxima: {fmtProxima(t.proxima_ejecucion)}
                          </span>
                        )}
                      </div>
                    </div>
                  </div>
                  <div
                    style={{
                      display: "flex",
                      gap: ".5rem",
                      alignItems: "center",
                      flexWrap: "wrap",
                    }}
                  >
                    <select
                      value={t.intervalo_min}
                      onChange={(e) =>
                        cambiarIntervalo(t, Number(e.target.value))
                      }
                      style={{
                        padding: "5px 10px",
                        borderRadius: 8,
                        fontFamily: "inherit",
                        border: "1px solid var(--t-border)",
                        background: "var(--t-bg)",
                        color: "var(--t-text)",
                        fontSize: ".76rem",
                        outline: "none",
                      }}
                    >
                      {INTERVALOS.map((op) => (
                        <option key={op.val} value={op.val}>
                          {op.label}
                        </option>
                      ))}
                    </select>
                    <button
                      onClick={() => ejecutarAhora(t)}
                      disabled={t.estado === "ejecutando"}
                      style={{
                        padding: "6px 13px",
                        borderRadius: 8,
                        fontFamily: "inherit",
                        border: "1px solid var(--t-accent)",
                        background: "rgba(0,212,255,.12)",
                        color: "var(--t-accent)",
                        cursor: "pointer",
                        fontSize: ".76rem",
                        fontWeight: 700,
                        display: "flex",
                        alignItems: "center",
                        gap: 5,
                      }}
                    >
                      <Play size={13} /> Ahora
                    </button>
                    <button
                      onClick={() => toggle(t)}
                      style={{
                        padding: "6px 16px",
                        borderRadius: 8,
                        fontFamily: "inherit",
                        border: "none",
                        background: t.activo ? "#00ff9d" : "var(--t-border)",
                        color: t.activo ? "#0a0e1a" : "var(--t-text-muted)",
                        cursor: "pointer",
                        fontSize: ".78rem",
                        fontWeight: 800,
                      }}
                    >
                      {t.activo ? "● ACTIVO" : "○ PAUSADO"}
                    </button>
                  </div>
                </div>
              </div>
            );
          })}
          {tareas.length === 0 && (
            <div
              style={{
                padding: "2rem",
                textAlign: "center",
                color: "var(--t-text-muted)",
                fontSize: ".85rem",
              }}
            >
              No hay tareas de monitoreo configuradas en el scheduler.
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Pestaña: Ligas & Tablas ───────────────────────────────────────────────────
function TabLigas() {
  const [porGrupo, setPorGrupo] = useState({});
  const [liga, setLiga] = useState(null);
  const [datos, setDatos] = useState(null);
  const [cargando, setCargando] = useState(false);
  const [vista, setVista] = useState("tabla");

  useEffect(() => {
    fetch(`${API_BASE}/monitor/equipos-preset`)
      .then((r) => r.json())
      .then((d) => {
        const ligas = d.ligas ?? [];
        const grupos = {};
        ligas.forEach((l) => {
          grupos[l.grupo] = grupos[l.grupo] || [];
          grupos[l.grupo].push(l);
        });
        setPorGrupo(grupos);
        if (ligas.length > 0) setLiga(ligas[0]);
      })
      .catch(() => {});
  }, []);

  const cargarLiga = useCallback(async (l) => {
    if (!l) return;
    setCargando(true);
    setDatos(null);
    setVista("tabla");
    try {
      const r = await fetch(
        `${API_BASE}/monitor/liga/${l.id}?nombre=${encodeURIComponent(l.nombre)}`,
      ).then((res) => res.json());
      if (r.ok) {
        setDatos(r.data);
        if (
          (r.data?.equipos_tabla ?? []).length === 0 &&
          (r.data?.partidos_recientes ?? []).length > 0
        )
          setVista("recientes");
      } else {
        addNotification({
          message: r.error || "Error al cargar liga",
          type: "error",
        });
      }
    } catch (e) {
      addNotification({
        message: "Error de conexión: " + e.message,
        type: "error",
      });
    } finally {
      setCargando(false);
    }
  }, []);

  useEffect(() => {
    if (liga) cargarLiga(liga);
  }, [liga, cargarLiga]);

  const tabla = datos?.equipos_tabla ?? [];
  const recientes = datos?.partidos_recientes ?? [];
  const proximos = datos?.proximos_partidos ?? [];
  const stats = datos?.estadisticas_liga ?? {};

  return (
    <div style={{ display: "flex", gap: "1rem", minHeight: 500 }}>
      <div
        style={{
          width: 220,
          flexShrink: 0,
          display: "flex",
          flexDirection: "column",
          gap: ".2rem",
          overflowY: "auto",
          maxHeight: "75vh",
          background: "var(--t-bg-card)",
          borderRadius: 12,
          border: "1px solid var(--t-border)",
          padding: 8,
        }}
      >
        {Object.entries(porGrupo).map(([grupo, ligas]) => (
          <div key={grupo}>
            <div
              style={{
                fontSize: ".7rem",
                fontWeight: 800,
                color: "#f59e0b",
                textTransform: "uppercase",
                letterSpacing: ".1em",
                padding: "12px 8px 4px",
                borderBottom: "1px solid var(--t-border)",
                marginBottom: 4,
              }}
            >
              ⚽ {grupo}
            </div>
            {ligas.map((l) => {
              const activa = liga?.id === l.id;
              return (
                <button
                  key={l.id}
                  onClick={() => setLiga(l)}
                  style={{
                    width: "100%",
                    textAlign: "left",
                    padding: "9px 12px",
                    borderRadius: 10,
                    border: "none",
                    cursor: "pointer",
                    fontFamily: "inherit",
                    marginBottom: 3,
                    background: activa
                      ? "linear-gradient(90deg,rgba(245,158,11,.25),rgba(245,158,11,.08))"
                      : "transparent",
                    borderLeft: activa
                      ? "3px solid #f59e0b"
                      : "3px solid transparent",
                  }}
                >
                  <div
                    style={{
                      fontWeight: activa ? 700 : 500,
                      fontSize: ".82rem",
                      color: activa ? "#fbbf24" : "var(--t-text)",
                    }}
                  >
                    {l.nombre}
                  </div>
                  <div
                    style={{
                      fontSize: ".68rem",
                      color: activa ? "#f59e0b" : "var(--t-text-muted)",
                      marginTop: 2,
                    }}
                  >
                    {l.pais}
                  </div>
                </button>
              );
            })}
          </div>
        ))}
      </div>

      <div
        style={{
          flex: 1,
          display: "flex",
          flexDirection: "column",
          gap: ".8rem",
          minWidth: 0,
        }}
      >
        {liga && (
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              padding: "12px 16px",
              borderRadius: 12,
              background: "rgba(0,212,255,.06)",
              border: "1px solid rgba(0,212,255,.2)",
              flexWrap: "wrap",
              gap: ".5rem",
            }}
          >
            <div>
              <div
                style={{
                  fontWeight: 800,
                  fontSize: "1rem",
                  color: "var(--t-text)",
                }}
              >
                ⚽ {liga.nombre}
              </div>
              <div
                style={{
                  fontSize: ".72rem",
                  color: "var(--t-text-muted)",
                  marginTop: 2,
                }}
              >
                {liga.pais} · {datos?.temporada ?? "temporada actual"}
                {stats.equipos ? ` · ${stats.equipos} equipos` : ""}
              </div>
            </div>
            <button
              onClick={() => cargarLiga(liga)}
              disabled={cargando}
              style={{
                padding: "5px 14px",
                borderRadius: 20,
                border: "1px solid var(--t-accent)",
                background: "rgba(0,212,255,.1)",
                color: "var(--t-accent)",
                cursor: "pointer",
                fontFamily: "inherit",
                fontSize: ".75rem",
                display: "flex",
                alignItems: "center",
                gap: 5,
              }}
            >
              <RefreshCw
                size={13}
                style={{
                  animation: cargando ? "spin .8s linear infinite" : "none",
                }}
              />{" "}
              Actualizar
            </button>
          </div>
        )}

        {cargando && <Cargando texto={`Cargando ${liga?.nombre ?? ""}...`} />}

        {datos && !cargando && (
          <>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fill,minmax(160px,1fr))",
                gap: ".7rem",
              }}
            >
              {[
                ["Líder", stats.lider, "#00ff9d"],
                ["Puntos líder", stats.max_puntos, "#00d4ff"],
                ["Más goles", stats.equipo_mas_goles, "#f59e0b"],
                ["Total goles", stats.total_goles_marcados, "#a78bfa"],
              ].map(([label, val, color]) => (
                <div
                  key={label}
                  style={{
                    padding: "14px 16px",
                    borderRadius: 12,
                    border: `2px solid ${color}`,
                    background: "var(--t-bg)",
                  }}
                >
                  <div
                    style={{
                      fontSize: ".72rem",
                      color: "var(--t-text-muted)",
                      marginBottom: 7,
                      textTransform: "uppercase",
                      letterSpacing: ".05em",
                      fontWeight: 600,
                    }}
                  >
                    {label}
                  </div>
                  <div
                    style={{
                      fontWeight: 900,
                      fontSize: "1.1rem",
                      color,
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {val && val !== "?" ? (
                      val
                    ) : (
                      <span style={{ color: "#475569", fontSize: ".85rem" }}>
                        Sin datos
                      </span>
                    )}
                  </div>
                </div>
              ))}
            </div>

            <div style={{ display: "flex", gap: ".3rem" }}>
              {[
                { id: "tabla", label: `📊 Tabla (${tabla.length})` },
                {
                  id: "recientes",
                  label: `🕐 Recientes (${recientes.length})`,
                },
                { id: "proximos", label: `📅 Próximos (${proximos.length})` },
              ].map((t) => (
                <button
                  key={t.id}
                  onClick={() => setVista(t.id)}
                  style={{
                    padding: "5px 13px",
                    borderRadius: 20,
                    fontFamily: "inherit",
                    border:
                      vista === t.id
                        ? "1px solid var(--t-accent)"
                        : "1px solid var(--t-border)",
                    background:
                      vista === t.id ? "rgba(0,212,255,.12)" : "transparent",
                    color:
                      vista === t.id
                        ? "var(--t-accent)"
                        : "var(--t-text-muted)",
                    fontSize: ".73rem",
                    fontWeight: 600,
                    cursor: "pointer",
                  }}
                >
                  {t.label}
                </button>
              ))}
            </div>

            {vista === "tabla" &&
              (tabla.length === 0 ? (
                <div
                  style={{
                    padding: "2rem",
                    textAlign: "center",
                    border: "2px dashed var(--t-border)",
                    borderRadius: 12,
                    color: "var(--t-text-muted)",
                    fontSize: ".82rem",
                  }}
                >
                  Sin tabla de posiciones disponible para esta liga.
                </div>
              ) : (
                <div
                  style={{
                    borderRadius: 12,
                    border: "1px solid var(--t-border)",
                    overflow: "hidden",
                  }}
                >
                  <div
                    style={{
                      display: "grid",
                      gridTemplateColumns:
                        "34px 1.8fr 40px 40px 40px 40px 50px 50px 50px 65px 90px",
                      padding: "10px 14px",
                      background: "var(--t-bg)",
                      borderBottom: "2px solid var(--t-accent)",
                      fontSize: ".72rem",
                      fontWeight: 800,
                      color: "var(--t-accent)",
                      textTransform: "uppercase",
                      gap: 4,
                      textAlign: "center",
                    }}
                  >
                    <span>#</span>
                    <span style={{ textAlign: "left" }}>Equipo</span>
                    <span>PJ</span>
                    <span>G</span>
                    <span>E</span>
                    <span>P</span>
                    <span>GF</span>
                    <span>GC</span>
                    <span>DG</span>
                    <span>Pts</span>
                    <span>Forma</span>
                  </div>
                  {tabla.map((eq, i) => {
                    const color = colorPosicion(eq.posicion, tabla.length);
                    const forma = (eq.forma || "").split("").slice(0, 5);
                    return (
                      <div
                        key={i}
                        style={{
                          display: "grid",
                          gridTemplateColumns:
                            "34px 1.8fr 40px 40px 40px 40px 50px 50px 50px 65px 90px",
                          padding: "11px 14px",
                          gap: 4,
                          borderBottom:
                            i < tabla.length - 1
                              ? "1px solid var(--t-border)"
                              : "none",
                          background:
                            i % 2 === 0
                              ? "transparent"
                              : "rgba(255,255,255,.02)",
                          alignItems: "center",
                          textAlign: "center",
                        }}
                      >
                        <span
                          style={{
                            fontWeight: 900,
                            fontSize: ".85rem",
                            color,
                            borderLeft: `3px solid ${color}`,
                            paddingLeft: 5,
                          }}
                        >
                          {eq.posicion}
                        </span>
                        <span
                          style={{
                            fontWeight: eq.posicion <= 3 ? 800 : 500,
                            fontSize: ".85rem",
                            color: "var(--t-text)",
                            textAlign: "left",
                            overflow: "hidden",
                            textOverflow: "ellipsis",
                            whiteSpace: "nowrap",
                          }}
                        >
                          {eq.equipo}
                        </span>
                        <span
                          style={{
                            fontSize: ".82rem",
                            color: "var(--t-text-muted)",
                          }}
                        >
                          {eq.pj}
                        </span>
                        <span
                          style={{
                            fontSize: ".85rem",
                            color: "#00ff9d",
                            fontWeight: 700,
                          }}
                        >
                          {eq.victorias}
                        </span>
                        <span
                          style={{
                            fontSize: ".82rem",
                            color: "#f59e0b",
                            fontWeight: 600,
                          }}
                        >
                          {eq.empates}
                        </span>
                        <span
                          style={{
                            fontSize: ".82rem",
                            color: "#ff2d55",
                            fontWeight: 600,
                          }}
                        >
                          {eq.derrotas}
                        </span>
                        <span
                          style={{
                            fontSize: ".82rem",
                            color: "var(--t-text-muted)",
                          }}
                        >
                          {eq.gf}
                        </span>
                        <span style={{ fontSize: ".82rem", color: "#64748b" }}>
                          {eq.gc}
                        </span>
                        <span
                          style={{
                            fontSize: ".85rem",
                            fontWeight: 700,
                            color:
                              eq.diferencia > 0
                                ? "#00ff9d"
                                : eq.diferencia < 0
                                  ? "#ff2d55"
                                  : "#64748b",
                          }}
                        >
                          {eq.diferencia > 0 ? "+" : ""}
                          {eq.diferencia}
                        </span>
                        <span
                          style={{
                            fontWeight: 900,
                            fontSize: ".95rem",
                            color: "#fff",
                            padding: "3px 8px",
                            borderRadius: 8,
                            background: color,
                            display: "inline-block",
                          }}
                        >
                          {eq.puntos}
                        </span>
                        <div
                          style={{
                            display: "flex",
                            gap: 2,
                            justifyContent: "center",
                          }}
                        >
                          {forma.map((f, k) => (
                            <span key={k} style={{ fontSize: 13 }}>
                              {RACHA_ICON[f] ?? ""}
                            </span>
                          ))}
                        </div>
                      </div>
                    );
                  })}
                </div>
              ))}

            {vista === "recientes" && (
              <div
                style={{
                  display: "flex",
                  flexDirection: "column",
                  gap: ".5rem",
                }}
              >
                {recientes.length === 0 ? (
                  <div
                    style={{
                      padding: "2rem",
                      textAlign: "center",
                      color: "var(--t-text-muted)",
                      border: "2px dashed var(--t-border)",
                      borderRadius: 12,
                      fontSize: ".85rem",
                    }}
                  >
                    Sin datos de partidos recientes.
                  </div>
                ) : (
                  [...recientes].reverse().map((p, i) => {
                    const gl = Number(p.gl ?? -1),
                      gv = Number(p.gv ?? -1);
                    const localGana = gl > gv,
                      visitaGana = gv > gl;
                    return (
                      <div
                        key={i}
                        style={{
                          padding: "14px 18px",
                          borderRadius: 12,
                          border: "1px solid var(--t-border)",
                          background: "var(--t-bg)",
                          display: "grid",
                          gridTemplateColumns: "100px 1fr auto 1fr 80px",
                          alignItems: "center",
                          gap: "1rem",
                        }}
                      >
                        <div>
                          <div
                            style={{
                              fontSize: ".8rem",
                              color: "var(--t-accent)",
                              fontWeight: 700,
                            }}
                          >
                            {p.fecha}
                          </div>
                          {p.ronda && (
                            <div
                              style={{
                                fontSize: ".68rem",
                                color: "var(--t-text-muted)",
                                marginTop: 2,
                              }}
                            >
                              {p.ronda}
                            </div>
                          )}
                        </div>
                        <div
                          style={{
                            textAlign: "right",
                            fontWeight: 700,
                            color: localGana
                              ? "var(--t-text)"
                              : "var(--t-text-muted)",
                          }}
                        >
                          {p.local}
                        </div>
                        <div
                          style={{
                            textAlign: "center",
                            minWidth: 80,
                            padding: "8px 14px",
                            borderRadius: 10,
                            background: "var(--t-bg-card)",
                            border: "2px solid var(--t-border)",
                            fontWeight: 900,
                            fontSize: "1.3rem",
                          }}
                        >
                          {gl >= 0 ? `${gl} - ${gv}` : "?"}
                        </div>
                        <div
                          style={{
                            textAlign: "left",
                            fontWeight: 700,
                            color: visitaGana
                              ? "var(--t-text)"
                              : "var(--t-text-muted)",
                          }}
                        >
                          {p.visita}
                        </div>
                        <div style={{ textAlign: "center" }}>
                          {gl === gv ? (
                            <span
                              style={{
                                fontSize: ".72rem",
                                color: "#f59e0b",
                                fontWeight: 700,
                                padding: "3px 8px",
                                borderRadius: 20,
                                background: "rgba(245,158,11,.15)",
                              }}
                            >
                              EMPATE
                            </span>
                          ) : (
                            <span
                              style={{
                                fontSize: ".72rem",
                                fontWeight: 700,
                                color: "#00ff9d",
                                padding: "3px 8px",
                                borderRadius: 20,
                                background: "rgba(0,255,157,.12)",
                              }}
                            >
                              {localGana ? "L" : "V"} gana
                            </span>
                          )}
                        </div>
                      </div>
                    );
                  })
                )}
              </div>
            )}

            {vista === "proximos" && (
              <div
                style={{
                  display: "flex",
                  flexDirection: "column",
                  gap: ".5rem",
                }}
              >
                {proximos.length === 0 ? (
                  <div
                    style={{
                      padding: "2rem",
                      textAlign: "center",
                      color: "var(--t-text-muted)",
                      border: "2px dashed var(--t-border)",
                      borderRadius: 12,
                      fontSize: ".85rem",
                    }}
                  >
                    Sin próximos partidos disponibles.
                  </div>
                ) : (
                  proximos.map((p, i) => (
                    <div
                      key={i}
                      style={{
                        padding: "14px 18px",
                        borderRadius: 12,
                        border: "1px solid rgba(0,212,255,.3)",
                        background: "rgba(0,212,255,.04)",
                        display: "grid",
                        gridTemplateColumns: "120px 1fr auto 1fr 60px",
                        alignItems: "center",
                        gap: "1rem",
                      }}
                    >
                      <div>
                        <div
                          style={{
                            fontSize: ".82rem",
                            color: "var(--t-accent)",
                            fontWeight: 800,
                          }}
                        >
                          {p.fecha}
                        </div>
                        {p.hora && (
                          <div
                            style={{
                              fontSize: ".78rem",
                              color: "var(--t-text-muted)",
                              marginTop: 2,
                            }}
                          >
                            🕐 {p.hora}
                          </div>
                        )}
                      </div>
                      <div
                        style={{
                          textAlign: "right",
                          fontWeight: 700,
                          color: "var(--t-text)",
                        }}
                      >
                        {p.local}
                      </div>
                      <div
                        style={{
                          textAlign: "center",
                          minWidth: 50,
                          padding: "6px 12px",
                          borderRadius: 10,
                          background: "rgba(0,212,255,.1)",
                          border: "1px solid rgba(0,212,255,.4)",
                          fontWeight: 900,
                          fontSize: ".85rem",
                          color: "var(--t-accent)",
                        }}
                      >
                        VS
                      </div>
                      <div
                        style={{
                          textAlign: "left",
                          fontWeight: 700,
                          color: "var(--t-text)",
                        }}
                      >
                        {p.visita}
                      </div>
                      <div
                        style={{
                          textAlign: "center",
                          fontSize: ".7rem",
                          color: "var(--t-text-muted)",
                        }}
                      >
                        {p.ronda}
                      </div>
                    </div>
                  ))
                )}
              </div>
            )}
          </>
        )}

        {!datos && !cargando && (
          <div
            style={{
              flex: 1,
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              justifyContent: "center",
              gap: ".8rem",
              color: "var(--t-text-muted)",
              fontSize: ".85rem",
              minHeight: 200,
            }}
          >
            <span style={{ fontSize: 32 }}>⚽</span>
            <div>Selecciona una liga del panel izquierdo</div>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Pestaña: Energía ──────────────────────────────────────────────────────────
function TabEnergia() {
  const [categoria, setCategoria] = useState("energia_renovable");
  const [datos, setDatos] = useState(null);
  const [cargando, setCargando] = useState(false);

  const cargar = useCallback(async (cat) => {
    setCargando(true);
    setDatos(null);
    try {
      const r = await fetch(`${API_BASE}/monitor/fetch?categoria=${cat}`).then(
        (res) => res.json(),
      );
      if (r.ok) setDatos(r.data);
      else
        addNotification({
          message: r.error || "Error al obtener datos de energía",
          type: "error",
        });
    } catch (e) {
      addNotification({ message: "Error: " + e.message, type: "error" });
    } finally {
      setCargando(false);
    }
  }, []);

  useEffect(() => {
    cargar(categoria);
  }, [categoria, cargar]);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
      <div style={{ display: "flex", gap: ".4rem", flexWrap: "wrap" }}>
        {[
          { id: "energia_renovable", label: "☀️ Solar & Eólico" },
          { id: "energia_demanda", label: "🔌 Demanda Estimada" },
          { id: "energia_spot", label: "💰 Precio Spot" },
        ].map((t) => (
          <button
            key={t.id}
            onClick={() => setCategoria(t.id)}
            disabled={cargando}
            style={{
              padding: "6px 14px",
              borderRadius: 16,
              fontFamily: "inherit",
              border:
                categoria === t.id
                  ? "1px solid #f59e0b"
                  : "1px solid var(--t-border)",
              background:
                categoria === t.id ? "rgba(245,158,11,.1)" : "transparent",
              color: categoria === t.id ? "#f59e0b" : "var(--t-text-muted)",
              fontSize: ".75rem",
              fontWeight: 600,
              cursor: "pointer",
            }}
          >
            {t.label}
          </button>
        ))}
      </div>

      {cargando && <Cargando texto="Consultando datos de energía..." />}

      {datos && !cargando && categoria === "energia_renovable" && (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "1fr 1fr",
            gap: "1rem",
          }}
        >
          <div
            style={{
              padding: "1.2rem",
              borderRadius: 14,
              border: "2px solid rgba(245,158,11,.3)",
              background: "rgba(245,158,11,.05)",
            }}
          >
            <div
              style={{
                fontSize: ".72rem",
                color: "#f59e0b",
                fontWeight: 700,
                textTransform: "uppercase",
                marginBottom: 10,
              }}
            >
              ☀️ Potencial Solar
            </div>
            {[
              ["Radiación promedio", `${datos.solar?.promedio_wm2} W/m²`],
              ["Radiación máxima", `${datos.solar?.maximo_wm2} W/m²`],
              ["Tendencia", datos.solar?.tendencia],
              ["Potencial", datos.solar?.potencial],
            ].map(([k, v]) => (
              <div
                key={k}
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  padding: "5px 0",
                  borderBottom: "1px solid rgba(245,158,11,.1)",
                  fontSize: ".78rem",
                }}
              >
                <span style={{ color: "var(--t-text-muted)" }}>{k}</span>
                <span style={{ color: "#f59e0b", fontWeight: 600 }}>{v}</span>
              </div>
            ))}
          </div>
          <div
            style={{
              padding: "1.2rem",
              borderRadius: 14,
              border: "2px solid rgba(0,212,255,.3)",
              background: "rgba(0,212,255,.05)",
            }}
          >
            <div
              style={{
                fontSize: ".72rem",
                color: "#00d4ff",
                fontWeight: 700,
                textTransform: "uppercase",
                marginBottom: 10,
              }}
            >
              💨 Potencial Eólico
            </div>
            {[
              [
                "Velocidad promedio",
                `${datos.eolico?.velocidad_prom_kmh} km/h`,
              ],
              ["Velocidad máxima", `${datos.eolico?.velocidad_max_kmh} km/h`],
              ["Potencial", datos.eolico?.potencial],
            ].map(([k, v]) => (
              <div
                key={k}
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  padding: "5px 0",
                  borderBottom: "1px solid rgba(0,212,255,.1)",
                  fontSize: ".78rem",
                }}
              >
                <span style={{ color: "var(--t-text-muted)" }}>{k}</span>
                <span style={{ color: "#00d4ff", fontWeight: 600 }}>{v}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {datos && !cargando && categoria === "energia_demanda" && (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(3,1fr)",
            gap: ".6rem",
          }}
        >
          {[
            ["Hoy", datos.temperatura?.hoy_prom_c, datos.demanda_estimada?.hoy],
            [
              "Mañana",
              datos.temperatura?.manana_prom_c,
              datos.demanda_estimada?.manana,
            ],
            [
              "Pasado mañana",
              datos.temperatura?.pasado_prom_c,
              datos.demanda_estimada?.pasado_manana,
            ],
          ].map(([label, temp, demanda]) => (
            <div
              key={label}
              style={{
                padding: "1rem",
                borderRadius: 12,
                textAlign: "center",
                border: "2px solid var(--t-border)",
                background: "var(--t-bg)",
              }}
            >
              <div
                style={{
                  fontSize: ".72rem",
                  color: "var(--t-text-muted)",
                  marginBottom: 6,
                }}
              >
                {label}
              </div>
              <div
                style={{
                  fontSize: "1.6rem",
                  fontWeight: 800,
                  color: "var(--t-text)",
                }}
              >
                {temp}°C
              </div>
              <div
                style={{
                  marginTop: 6,
                  padding: "3px 10px",
                  borderRadius: 20,
                  display: "inline-block",
                  background: "rgba(245,158,11,.15)",
                  color: "#f59e0b",
                  fontSize: ".7rem",
                  fontWeight: 700,
                }}
              >
                Demanda {demanda}
              </div>
            </div>
          ))}
        </div>
      )}

      {datos && !cargando && categoria === "energia_spot" && (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill,minmax(160px,1fr))",
            gap: ".6rem",
          }}
        >
          {[
            [
              "Precio promedio",
              datos.precio_prom_usd_mwh
                ? `$${datos.precio_prom_usd_mwh}`
                : "N/D",
              "#00d4ff",
            ],
            [
              "Precio máximo",
              datos.precio_max ? `$${datos.precio_max}` : "N/D",
              "#ff2d55",
            ],
            [
              "Precio mínimo",
              datos.precio_min ? `$${datos.precio_min}` : "N/D",
              "#00ff9d",
            ],
            ["Tendencia", datos.tendencia || "N/D", "#f59e0b"],
          ].map(([label, val, color]) => (
            <div
              key={label}
              style={{
                padding: "12px 14px",
                borderRadius: 12,
                border: `1px solid ${color}30`,
                background: `${color}08`,
              }}
            >
              <div
                style={{
                  fontSize: ".64rem",
                  color: "var(--t-text-muted)",
                  marginBottom: 5,
                }}
              >
                {label}
              </div>
              <div style={{ fontSize: "1.2rem", fontWeight: 800, color }}>
                {val}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Pestaña: Historial ────────────────────────────────────────────────────────
function TabHistorial() {
  const [datos, setDatos] = useState([]);
  const cargar = useCallback(() => {
    fetch(`${API_BASE}/monitor/historial?limit=50`)
      .then((r) => r.json())
      .then((d) => setDatos(d.datos || []))
      .catch(() => {});
  }, []);
  useEffect(() => {
    cargar();
  }, [cargar]);

  return (
    <div
      style={{
        borderRadius: 12,
        border: "1px solid var(--t-border)",
        overflow: "hidden",
      }}
    >
      <div
        style={{
          padding: "8px 14px",
          background: "var(--t-bg)",
          borderBottom: "1px solid var(--t-border)",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
        }}
      >
        <span
          style={{
            fontWeight: 700,
            fontSize: ".78rem",
            color: "var(--t-text-muted)",
            textTransform: "uppercase",
          }}
        >
          Datos Monitoreados ({datos.length})
        </span>
        <button
          onClick={cargar}
          style={{
            padding: "3px 10px",
            borderRadius: 16,
            border: "1px solid var(--t-border)",
            background: "transparent",
            color: "var(--t-text-muted)",
            cursor: "pointer",
            fontSize: ".7rem",
          }}
        >
          <RefreshCw size={12} />
        </button>
      </div>
      {datos.length === 0 ? (
        <div
          style={{
            padding: "2rem",
            textAlign: "center",
            color: "var(--t-text-muted)",
            fontSize: ".82rem",
          }}
        >
          Sin datos todavía. Consulta Ligas o Energía para generar historial.
        </div>
      ) : (
        datos.map((d, i) => (
          <div
            key={i}
            style={{
              display: "grid",
              gridTemplateColumns: "1fr 1.5fr .7fr .8fr",
              padding: "8px 14px",
              fontSize: ".75rem",
              color: "var(--t-text)",
              borderBottom:
                i < datos.length - 1 ? "1px solid var(--t-border)" : "none",
              background: i % 2 === 0 ? "transparent" : "rgba(255,255,255,.02)",
            }}
          >
            <span style={{ color: "var(--t-text-muted)" }}>{d.categoria}</span>
            <span
              style={{
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
              }}
            >
              {d.clave}
            </span>
            <span style={{ fontWeight: 700, color: "var(--t-accent)" }}>
              {d.valor}
            </span>
            <span style={{ color: "var(--t-text-muted)" }}>
              {new Date(d.ts).toLocaleString("es", {
                day: "2-digit",
                month: "2-digit",
                hour: "2-digit",
                minute: "2-digit",
              })}
            </span>
          </div>
        ))
      )}
    </div>
  );
}

// ── Pestaña: Alertas ───────────────────────────────────────────────────────────
function TabAlertas() {
  const [alertas, setAlertas] = useState([]);
  useEffect(() => {
    fetch(`${API_BASE}/monitor/alertas`)
      .then((r) => r.json())
      .then((d) => setAlertas(d.alertas || []))
      .catch(() => {});
  }, []);
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: ".5rem" }}>
      {alertas.length === 0 ? (
        <div
          style={{
            padding: "2rem",
            textAlign: "center",
            color: "var(--t-text-muted)",
            border: "2px dashed var(--t-border)",
            borderRadius: 12,
            fontSize: ".85rem",
          }}
        >
          Sin alertas generadas todavía.
        </div>
      ) : (
        alertas.map((a, i) => {
          const color = ALERTA_COLOR[a.nivel] ?? "#64748b";
          return (
            <div
              key={i}
              style={{
                padding: "12px 16px",
                borderRadius: 12,
                border: `1px solid ${color}40`,
                background: `${color}08`,
              }}
            >
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  marginBottom: 4,
                }}
              >
                <span style={{ fontWeight: 700, fontSize: ".82rem", color }}>
                  {a.titulo}
                </span>
                <span
                  style={{ fontSize: ".68rem", color: "var(--t-text-muted)" }}
                >
                  {new Date(a.ts).toLocaleString("es")}
                </span>
              </div>
              <div style={{ fontSize: ".78rem", color: "var(--t-text-muted)" }}>
                {a.descripcion}
              </div>
            </div>
          );
        })
      )}
    </div>
  );
}

export default function MonitorPanel() {
  const [tab, setTab] = useState("automatico");
  const tabs = [
    { id: "automatico", label: "🤖 Automático" },
    { id: "ligas", label: "⚽ Ligas & Tablas" },
    { id: "energia", label: "⚡ Energía" },
    { id: "historial", label: "📊 Historial" },
    { id: "alertas", label: "🔔 Alertas" },
  ];
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
      <div style={{ display: "flex", gap: ".4rem", flexWrap: "wrap" }}>
        {tabs.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            style={{
              padding: "6px 16px",
              borderRadius: 20,
              fontFamily: "inherit",
              border:
                tab === t.id
                  ? "1.5px solid var(--t-accent)"
                  : "1px solid var(--t-border)",
              background: tab === t.id ? "rgba(0,212,255,.12)" : "transparent",
              color: tab === t.id ? "var(--t-accent)" : "var(--t-text-muted)",
              fontWeight: 600,
              fontSize: ".78rem",
              cursor: "pointer",
            }}
          >
            {t.label}
          </button>
        ))}
      </div>
      {tab === "automatico" && <TabAutomatico />}
      {tab === "ligas" && <TabLigas />}
      {tab === "energia" && <TabEnergia />}
      {tab === "historial" && <TabHistorial />}
      {tab === "alertas" && <TabAlertas />}
    </div>
  );
}
