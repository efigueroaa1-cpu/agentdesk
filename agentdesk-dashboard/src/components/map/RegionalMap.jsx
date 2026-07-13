/**
 * RegionalMap.jsx — "Mapa Regional": ubica los agentes con `ubicacion.lat/lng`
 * configurada sobre un mapa mundial (react-simple-maps) y muestra un panel de
 * detalle al hacer clic en un marcador.
 *
 * Reconstruido desde el bundle de producción (react_dist/assets/index-CRDO1T5r.js,
 * función `mw`): el fuente original de este componente no estaba versionado.
 */
import { useState, useEffect } from "react";
import {
  ComposableMap,
  Geographies,
  Geography,
  Marker,
  ZoomableGroup,
} from "react-simple-maps";
import { AgentService } from "../../services/agent.service";

const GEO_URL =
  "https://cdn.jsdelivr.net/npm/world-atlas@2/countries-110m.json";

const AREA_COLOR = {
  Finanzas: "#00d4ff",
  Mecánica: "#00ff9d",
  RRHH: "#f59e0b",
  Logística: "#8b5cf6",
  Marketing: "#ef4444",
  Legal: "#f97316",
  Tecnología: "#06b6d4",
  Operaciones: "#84cc16",
  General: "#64748b",
};
function areaColor(area) {
  return AREA_COLOR[area] ?? "#64748b";
}

export default function RegionalMap() {
  const [agentes, setAgentes] = useState([]);
  const [seleccionado, setSeleccionado] = useState(null);
  const [filtroArea, setFiltroArea] = useState("Todas");
  const [zoom, setZoom] = useState(1);
  const [center, setCenter] = useState([0, 20]);
  const [ejecutando, setEjecutando] = useState(new Set());

  useEffect(() => {
    AgentService.getAll()
      .then((d) => setAgentes(d.agentes ?? []))
      .catch(() => {});
    return AgentService.onWsMessage((msg) => {
      if (msg.tipo === "agente_ejecutando") {
        setEjecutando((s) => new Set([...s, msg.agente_id]));
      }
      if (msg.tipo === "tarea_completada" || msg.tipo === "tarea_abortada") {
        setEjecutando((s) => {
          const next = new Set(s);
          next.delete(msg.agente_id);
          return next;
        });
      }
      if (
        ["agente_creado", "agente_eliminado", "agente_actualizado"].includes(
          msg.tipo,
        )
      ) {
        AgentService.getAll()
          .then((d) => setAgentes(d.agentes ?? []))
          .catch(() => {});
      }
    });
  }, []);

  const areas = ["Todas", ...new Set(agentes.map((a) => a.area || "General"))];
  const conUbicacion = agentes.filter(
    (a) =>
      a.ubicacion?.lat &&
      a.ubicacion?.lng &&
      (filtroArea === "Todas" || (a.area || "General") === filtroArea),
  );
  const sinUbicacion = agentes.filter((a) => !a.ubicacion?.lat);

  return (
    <div
      style={{
        display: "flex",
        gap: "1rem",
        height: "calc(100vh - 180px)",
        minHeight: 500,
      }}
    >
      <div
        style={{
          flex: 1,
          borderRadius: 12,
          overflow: "hidden",
          border: "1px solid var(--t-border)",
          background: "#020818",
          position: "relative",
        }}
      >
        <div
          style={{
            position: "absolute",
            top: 12,
            left: 12,
            zIndex: 10,
            display: "flex",
            gap: ".4rem",
            flexWrap: "wrap",
          }}
        >
          {areas.map((a) => {
            const c = areaColor(a === "Todas" ? null : a);
            const active = filtroArea === a;
            return (
              <button
                key={a}
                onClick={() => setFiltroArea(a)}
                style={{
                  padding: "3px 10px",
                  borderRadius: 20,
                  fontSize: ".7rem",
                  fontWeight: 600,
                  cursor: "pointer",
                  fontFamily: "inherit",
                  border: active ? `1px solid ${c}` : "1px solid #162454",
                  background: active ? `${c}20` : "rgba(6,13,36,.8)",
                  color: active ? c : "#64748b",
                  backdropFilter: "blur(4px)",
                }}
              >
                {a}
              </button>
            );
          })}
        </div>

        <div
          style={{
            position: "absolute",
            bottom: 12,
            right: 12,
            zIndex: 10,
            display: "flex",
            flexDirection: "column",
            gap: 4,
          }}
        >
          {[
            ["＋", () => setZoom((z) => Math.min(z * 1.5, 8))],
            ["－", () => setZoom((z) => Math.max(z / 1.5, 0.5))],
            [
              "⌖",
              () => {
                setZoom(1);
                setCenter([0, 20]);
              },
            ],
          ].map(([label, fn]) => (
            <button
              key={label}
              onClick={fn}
              style={{
                width: 28,
                height: 28,
                borderRadius: 7,
                border: "1px solid #162454",
                background: "rgba(6,13,36,.9)",
                color: "#00d4ff",
                cursor: "pointer",
                fontSize: 14,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
              }}
            >
              {label}
            </button>
          ))}
        </div>

        <div
          style={{
            position: "absolute",
            bottom: 12,
            left: 12,
            zIndex: 10,
            background: "rgba(6,13,36,.85)",
            border: "1px solid #162454",
            borderRadius: 8,
            padding: "4px 10px",
            fontSize: ".7rem",
            color: "#64748b",
          }}
        >
          {conUbicacion.length} agente{conUbicacion.length !== 1 ? "s" : ""} en
          mapa
          {sinUbicacion.length > 0 && ` · ${sinUbicacion.length} sin ubicación`}
        </div>

        <ComposableMap
          projection="geoNaturalEarth1"
          style={{ width: "100%", height: "100%" }}
        >
          <ZoomableGroup
            zoom={zoom}
            center={center}
            onMoveEnd={({ coordinates, zoom: z }) => {
              setCenter(coordinates);
              setZoom(z);
            }}
          >
            <Geographies geography={GEO_URL}>
              {({ geographies }) =>
                geographies.map((geo) => (
                  <Geography
                    key={geo.rsmKey}
                    geography={geo}
                    style={{
                      default: {
                        fill: "#0d1a3e",
                        stroke: "#162454",
                        strokeWidth: 0.5,
                        outline: "none",
                      },
                      hover: {
                        fill: "#1e2d5a",
                        stroke: "#162454",
                        strokeWidth: 0.5,
                        outline: "none",
                      },
                      pressed: { fill: "#0d1a3e", outline: "none" },
                    }}
                  />
                ))
              }
            </Geographies>
            {conUbicacion.map((a) => {
              const c = areaColor(a.area);
              const activo = ejecutando.has(a.id);
              const sel = seleccionado?.id === a.id;
              return (
                <Marker
                  key={a.id}
                  coordinates={[a.ubicacion.lng, a.ubicacion.lat]}
                  onClick={() => setSeleccionado(sel ? null : a)}
                >
                  {activo && (
                    <circle
                      r={12}
                      fill="transparent"
                      stroke={c}
                      strokeWidth={1}
                      style={{ animation: "pulse 1.5s infinite" }}
                    />
                  )}
                  <circle
                    r={sel ? 7 : 5}
                    fill={c}
                    stroke={sel ? "#fff" : "#020818"}
                    strokeWidth={sel ? 2 : 1}
                    style={{ cursor: "pointer", transition: "r .15s" }}
                  />
                  <text
                    textAnchor="middle"
                    y={-10}
                    style={{
                      fontSize: 7,
                      fill: c,
                      fontFamily: "monospace",
                      pointerEvents: "none",
                      fontWeight: sel ? 700 : 400,
                    }}
                  >
                    {a.nombre}
                  </text>
                </Marker>
              );
            })}
          </ZoomableGroup>
        </ComposableMap>
        <style>{`
          @keyframes pulse {
            0%   { r: 8; opacity: 1; }
            100% { r: 20; opacity: 0; }
          }
        `}</style>
      </div>

      <div
        style={{
          width: 260,
          flexShrink: 0,
          border: "1px solid var(--t-border)",
          borderRadius: 12,
          background: "var(--t-bg-card)",
          overflow: "hidden",
          display: "flex",
          flexDirection: "column",
        }}
      >
        <div
          style={{
            padding: "10px 14px",
            borderBottom: "1px solid var(--t-border)",
            background: "var(--t-bg)",
            fontSize: ".75rem",
            fontWeight: 700,
            color: "var(--t-text-muted)",
            textTransform: "uppercase",
            letterSpacing: ".06em",
          }}
        >
          Detalle del Agente
        </div>
        {seleccionado ? (
          <div
            style={{
              padding: "1rem",
              display: "flex",
              flexDirection: "column",
              gap: ".8rem",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <div
                style={{
                  width: 36,
                  height: 36,
                  borderRadius: 9,
                  background: `${areaColor(seleccionado.area)}20`,
                  border: `1px solid ${areaColor(seleccionado.area)}40`,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  fontSize: 18,
                }}
              >
                🤖
              </div>
              <div>
                <div
                  style={{
                    fontWeight: 700,
                    fontSize: ".84rem",
                    color: "var(--t-text)",
                  }}
                >
                  {seleccionado.nombre}
                </div>
                <div
                  style={{ fontSize: ".68rem", color: "var(--t-text-muted)" }}
                >
                  {seleccionado.id}
                </div>
              </div>
            </div>
            {[
              ["Área", seleccionado.area || "General"],
              ["Modelo", (seleccionado.modelo || "").replace("models/", "")],
              ["Temp.", seleccionado.temperatura ?? "-"],
              ["Idioma", seleccionado.idioma || "-"],
              ["Ubicación", seleccionado.ubicacion?.label || "-"],
            ].map(([k, v]) => (
              <div
                key={k}
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  fontSize: ".76rem",
                }}
              >
                <span style={{ color: "var(--t-text-muted)" }}>{k}</span>
                <span
                  style={{
                    fontWeight: 600,
                    color: "var(--t-text)",
                    textAlign: "right",
                    maxWidth: "60%",
                  }}
                >
                  {v}
                </span>
              </div>
            ))}
            {seleccionado.prompt_base && (
              <div
                style={{
                  fontSize: ".68rem",
                  color: "var(--t-text-muted)",
                  lineHeight: 1.5,
                  padding: 8,
                  borderRadius: 7,
                  background: "var(--t-bg)",
                  border: "1px solid var(--t-border)",
                  overflow: "hidden",
                  display: "-webkit-box",
                  WebkitLineClamp: 4,
                  WebkitBoxOrient: "vertical",
                }}
              >
                {seleccionado.prompt_base}
              </div>
            )}
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 6,
                fontSize: ".72rem",
              }}
            >
              <div
                style={{
                  width: 8,
                  height: 8,
                  borderRadius: "50%",
                  background: ejecutando.has(seleccionado.id)
                    ? "#f59e0b"
                    : "#00ff9d",
                  boxShadow: ejecutando.has(seleccionado.id)
                    ? "0 0 6px #f59e0b"
                    : "none",
                }}
              />
              <span
                style={{
                  color: ejecutando.has(seleccionado.id)
                    ? "#f59e0b"
                    : "#00ff9d",
                  fontWeight: 600,
                }}
              >
                {ejecutando.has(seleccionado.id) ? "Ejecutando..." : "Idle"}
              </span>
            </div>
            <button
              onClick={() => setSeleccionado(null)}
              style={{
                padding: "6px 0",
                border: "1px solid var(--t-border)",
                borderRadius: 8,
                background: "transparent",
                color: "var(--t-text-muted)",
                cursor: "pointer",
                fontSize: ".72rem",
                fontFamily: "inherit",
              }}
            >
              Cerrar
            </button>
          </div>
        ) : (
          <div
            style={{
              flex: 1,
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              justifyContent: "center",
              color: "var(--t-text-muted)",
              fontSize: ".76rem",
              padding: "1rem",
              textAlign: "center",
              gap: ".5rem",
            }}
          >
            <div style={{ fontSize: 28 }}>🗺️</div>
            <div>
              Haz clic en un marcador del mapa para ver el detalle del agente
            </div>
            {sinUbicacion.length > 0 && (
              <div style={{ marginTop: ".5rem", fontSize: ".68rem" }}>
                <strong style={{ color: "var(--t-text)" }}>
                  {sinUbicacion.length}
                </strong>{" "}
                agente{sinUbicacion.length !== 1 ? "s" : ""} sin ubicación:
                <br />
                {sinUbicacion.map((a) => a.nombre).join(", ")}
                <br />
                <br />
                Configura <code>ubicacion.lat/lng</code> en la vista Agentes.
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
