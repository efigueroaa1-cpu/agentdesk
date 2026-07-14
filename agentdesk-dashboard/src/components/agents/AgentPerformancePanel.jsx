/**
 * AgentPerformancePanel.jsx — Rendimiento por agente + estado de tareas en tiempo real.
 *
 * Orquestador delgado: la lógica vive en performance/useAgentStats.js y los
 * helpers puros en performance/statsUtils.js; la presentación está dividida
 * en sub-componentes (PerformanceTable, LiveTasksTable y sus celdas).
 */
import { useAgentStats } from "./performance/useAgentStats";
import PerformanceTable from "./performance/PerformanceTable";
import LiveTasksTable from "./performance/LiveTasksTable";

export default function AgentPerformancePanel() {
  const { agentes, stats, running, now, resetear } = useAgentStats();

  if (agentes.length === 0) return null;

  return (
    <div className="flex flex-col gap-4">
      <PerformanceTable
        agentes={agentes}
        stats={stats}
        running={running}
        onReset={resetear}
      />
      <LiveTasksTable
        agentes={agentes}
        stats={stats}
        running={running}
        now={now}
      />
    </div>
  );
}
