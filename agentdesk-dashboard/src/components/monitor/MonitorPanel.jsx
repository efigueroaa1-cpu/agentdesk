// MonitorPanel.jsx — "Monitor Web" (ID 8). Orquestador delgado: la lógica vive
// en el Puerto de Telemetría (hooks/useMonitorData); la UI, en este directorio.
import { useState } from "react";
import { useMonitorData } from "../../hooks/useMonitorData";
import { MONITOR_TABS } from "./monitorUtils";
import TabPills from "./TabPills";
import MonitorTaskTable from "./MonitorTaskTable";
import LiveAnalysisConsole from "./LiveAnalysisConsole";
import LeaguesTab from "./LeaguesTab";
import EnergyTab from "./EnergyTab";
import HistoryTab from "./HistoryTab";
import AlertsTab from "./AlertsTab";

export default function MonitorPanel() {
  const [tab, setTab] = useState("automatico");
  const { fuentes, cargando, eventos, historial, alertas, acciones } =
    useMonitorData();

  const vistas = {
    automatico: <MonitorTaskTable {...{ fuentes, cargando, acciones }} />,
    consola: (
      <LiveAnalysisConsole
        eventos={eventos}
        onLimpiar={acciones.limpiarEventos}
      />
    ),
    ligas: <LeaguesTab />,
    energia: <EnergyTab />,
    historial: (
      <HistoryTab historial={historial} onCargar={acciones.cargarHistorial} />
    ),
    alertas: <AlertsTab alertas={alertas} onCargar={acciones.cargarAlertas} />,
  };

  return (
    <div className="flex flex-col gap-4">
      <TabPills items={MONITOR_TABS} active={tab} onChange={setTab} />
      {vistas[tab]}
    </div>
  );
}
