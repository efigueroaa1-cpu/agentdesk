/**
 * EnergyTab.jsx — Pestaña "Energía": solar/eólico, demanda estimada y precio
 * spot (/monitor/fetch). Render declarativo; tarjetas en EnergyCards.jsx.
 */
import { useState, useEffect, useCallback } from "react";
import { API_BASE } from "../../services/agent.service";
import { addNotification } from "../ui/NotificationSystem";
import { PanelRenovable, DemandaGrid, SpotGrid } from "./EnergyCards";
import LoadingSpinner from "./LoadingSpinner";
import TabPills from "./TabPills";

const CATEGORIAS = [
  { id: "energia_renovable", label: "☀️ Solar & Eólico" },
  { id: "energia_demanda", label: "🔌 Demanda Estimada" },
  { id: "energia_spot", label: "💰 Precio Spot" },
];

const SOLAR_CLS = {
  box: "border-amber-500/30 bg-amber-500/5",
  text: "text-amber-500",
  divider: "border-amber-500/10",
};
const EOLICO_CLS = {
  box: "border-neon-blue/30 bg-neon-blue/5",
  text: "text-neon-blue",
  divider: "border-neon-blue/10",
};

export default function EnergyTab() {
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
    <div className="flex flex-col gap-4">
      <TabPills
        items={CATEGORIAS}
        active={categoria}
        onChange={setCategoria}
        accent="amber"
      />

      {cargando && <LoadingSpinner texto="Consultando datos de energía..." />}

      {datos && !cargando && categoria === "energia_renovable" && (
        <div className="grid grid-cols-2 gap-4">
          <PanelRenovable
            titulo="☀️ Potencial Solar"
            cls={SOLAR_CLS}
            filas={[
              ["Radiación promedio", `${datos.solar?.promedio_wm2} W/m²`],
              ["Radiación máxima", `${datos.solar?.maximo_wm2} W/m²`],
              ["Tendencia", datos.solar?.tendencia],
              ["Potencial", datos.solar?.potencial],
            ]}
          />
          <PanelRenovable
            titulo="💨 Potencial Eólico"
            cls={EOLICO_CLS}
            filas={[
              ["Vel. promedio", `${datos.eolico?.velocidad_prom_kmh} km/h`],
              ["Vel. máxima", `${datos.eolico?.velocidad_max_kmh} km/h`],
              ["Potencial", datos.eolico?.potencial],
            ]}
          />
        </div>
      )}

      {datos && !cargando && categoria === "energia_demanda" && (
        <DemandaGrid
          dias={[
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
          ]}
        />
      )}

      {datos && !cargando && categoria === "energia_spot" && (
        <SpotGrid
          tarjetas={[
            [
              "Precio promedio",
              datos.precio_prom_usd_mwh
                ? `$${datos.precio_prom_usd_mwh}`
                : "N/D",
              "border-neon-blue/20 bg-neon-blue/[.03] text-neon-blue",
            ],
            [
              "Precio máximo",
              datos.precio_max ? `$${datos.precio_max}` : "N/D",
              "border-neon-red/20 bg-neon-red/[.03] text-neon-red",
            ],
            [
              "Precio mínimo",
              datos.precio_min ? `$${datos.precio_min}` : "N/D",
              "border-neon-green/20 bg-neon-green/[.03] text-neon-green",
            ],
            [
              "Tendencia",
              datos.tendencia || "N/D",
              "border-amber-500/20 bg-amber-500/[.03] text-amber-500",
            ],
          ]}
        />
      )}
    </div>
  );
}
