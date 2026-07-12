import { useState, Suspense, useEffect, useCallback } from "react";
import { AuthProvider } from "./context/AuthContext";
import { useAuth } from "./context/AuthContext";
import ProtectedRoute from "./components/auth/ProtectedRoute";
import MainLayout from "./components/layout/MainLayout";
import SummarySection from "./components/sections/SummarySection";
import ErrorBoundary from "./components/ui/ErrorBoundary";
import AgentStatusSection from "./components/sections/AgentStatusSection";
import AgentPerformancePanel from "./components/agents/AgentPerformancePanel";
import MetricsPanel from "./components/metrics/MetricsPanel";
import AgentAreaView from "./components/agents/AgentAreaView";
import AgentManager from "./components/agents/AgentManager";
import PipelineControl from "./components/pipeline/PipelineControl";
import ErrorPanel from "./components/pipeline/ErrorPanel";
import DataProviderPanel from "./components/settings/DataProviderPanel";
import SecurityPanel from "./components/settings/SecurityPanel";
import RegionalMap from "./components/map/RegionalMap";
import ReportsPanel from "./components/reports/ReportsPanel";
import BIDashboard from "./components/bi/BIDashboard";
import TendenciasPanel from "./components/bi/TendenciasPanel";
import SCurveModule from "./components/hub/SCurveModule";
import MonitorPanel from "./components/monitor/MonitorPanel";
import SystemPanel from "./components/system/SystemPanel";
import LogsPanel from "./components/system/LogsPanel";
import ProvidersPanel from "./components/system/ProvidersPanel";
import ChatPanel from "./components/chat/ChatPanel";
import { lazy } from "react";
const EmbeddingView3D = lazy(() => import("./components/hub/EmbeddingView3D"));
import { useDarkMode } from "./hooks/useDarkMode";
import { initAuth } from "./services/auth.service.js";
import { useAppStore } from "./store/useAppStore.js";
import GlobalSearch from "./components/search/GlobalSearch.jsx";
import BackupPanel from "./components/system/BackupPanel.jsx";
import UpdatePanel from "./components/system/UpdatePanel.jsx";
import { SkipLink } from "./components/ui/A11y.jsx";
import AgentFlowEditor from "./components/agents/AgentFlowEditor.jsx";
import { NotificationContainer } from "./components/ui/NotificationSystem";
import { navigation, currentUser, summary } from "./data/data";
import ProyectosModule from "./components/proyectos/ProyectosModule";
import FinancialModule from "./components/hub/FinancialModule";
import GanttModule from "./components/hub/GanttModule";

const TABS = [
  ["dashboard", "Dashboard"],
  ["metricas", "Métricas"],
  ["agentes", "Agentes"],
  ["mapa", "Mapa Regional"],
  ["3d", "Embeddings 3D"],
  ["pipeline", "Pipeline"],
  ["data", "Datos"],
  ["monitor", "Monitor Web"],
  ["bi", "BI Dashboard"],
  ["reportes", "Reportes"],
  ["sistema", "Sistema"],
  ["proyectos", "Proyectos"],
  ["financiero", "Financiero"],
  ["gantt", "Gantt P6"],
  ["security", "Seguridad"],
];

// Contrato de navegación Sidebar → vista (IDs fijos, ver data.js)
const NAV_TO_VIEW = {
  1: "dashboard",
  2: "metricas",
  3: "agentes",
  4: "mapa",
  5: "3d",
  6: "pipeline",
  7: "data",
  8: "monitor",
  9: "bi",
  11: "reportes",
  12: "sistema",
  13: "security",
  14: "proyectos",
  15: "financiero",
  16: "gantt",
};

// Pills de navegación superiores: ocultas por CSS (.tab-pills) — la navegación
// vive en el Sidebar. Se mantienen en el DOM con id="_t_<vista>" como target
// de navegación programática (tests / integraciones).
function TabBar({ setView }) {
  return (
    <div className="tab-pills">
      {TABS.map(([k, l]) => (
        <button key={k} id={`_t_${k}`} onClick={() => setView(k)}>
          {l}
        </button>
      ))}
    </div>
  );
}

function SubTabs({ items, active, setActive }) {
  return (
    <div style={{ display: "flex", gap: ".4rem", marginBottom: "1rem" }}>
      {items.map(([k, l]) => (
        <button
          key={k}
          onClick={() => setActive(k)}
          style={{
            padding: "4px 12px",
            borderRadius: 20,
            fontSize: ".72rem",
            fontWeight: 600,
            cursor: "pointer",
            fontFamily: "inherit",
            border:
              active === k
                ? "1px solid var(--t-accent)"
                : "1px solid var(--t-border)",
            background: active === k ? "rgba(0,212,255,.1)" : "transparent",
            color: active === k ? "var(--t-accent)" : "var(--t-text-muted)",
          }}
        >
          {l}
        </button>
      ))}
    </div>
  );
}

function Dashboard() {
  const { usuario, logout } = useAuth();
  const { isDark, toggle: toggleDark } = useDarkMode();
  const [view, setView] = useState("dashboard");
  const [agentView, setAgentView] = useState("configurar");
  const [pipelineView, setPipelineView] = useState("control");
  const [sistemaView, setSistemaView] = useState("control");
  const [biView, setBiView] = useState("dashboard");
  const [chatFiles, setChatFiles] = useState([]);

  // Callback de navegación para GlobalSearch
  const navigateTo = useCallback((tab, subTab) => {
    setView(tab);
    if (subTab) {
      if (tab === "agentes") setAgentView(subTab);
      else if (tab === "sistema") setSistemaView(subTab);
      else if (tab === "bi") setBiView(subTab);
    }
  }, []);

  return (
    <MainLayout
      user={{ ...currentUser, name: usuario.username }}
      navItems={navigation}
      pageTitle={
        {
          dashboard: "Dashboard",
          metricas: "Métricas",
          agentes: "Agentes",
          mapa: "Mapa Regional",
          "3d": "Embeddings 3D",
          pipeline: "Pipeline",
          data: "Datos",
          monitor: "Monitor Web",
          bi: "BI Dashboard",
          reportes: "Reportes",
          sistema: "Sistema",
          proyectos: "Proyectos",
          financiero: "Financiero",
          gantt: "Gantt P6",
          security: "Seguridad",
        }[view]
      }
      query=""
      onQueryChange={() => {}}
      isDark={isDark}
      onToggleDark={toggleDark}
      onLogout={logout}
      onNavChange={(id) => setView(NAV_TO_VIEW[id] || "dashboard")}
    >
      <SkipLink />
      <GlobalSearch onNavigate={navigateTo} />
      <TabBar setView={setView} />

      {view === "dashboard" && (
        <ErrorBoundary>
          <div
            style={{ display: "flex", flexDirection: "column", gap: "1.2rem" }}
          >
            <SummarySection data={summary} />
            <AgentStatusSection
              onRunAgent={() => {
                setView("pipeline");
                setPipelineView("control");
              }}
            />
            <AgentPerformancePanel />
          </div>
        </ErrorBoundary>
      )}

      {view === "metricas" && (
        <ErrorBoundary>
          <MetricsPanel />
        </ErrorBoundary>
      )}

      {view === "agentes" && (
        <ErrorBoundary>
          <SubTabs
            items={[
              ["configurar", "Configurar por Área"],
              ["tabla", "Tabla CRUD"],
              ["flujo", "Editor de Flujo"],
              ["chat", "Chat con Agentes"],
            ]}
            active={agentView}
            setActive={setAgentView}
          />
          {agentView === "configurar" && <AgentAreaView />}
          {agentView === "tabla" && <AgentManager />}
          {agentView === "flujo" && <AgentFlowEditor />}
          {agentView === "chat" && (
            <div
              style={{
                border: "1px solid var(--t-border)",
                borderRadius: 12,
                overflow: "hidden",
              }}
            >
              <ChatPanel
                initialFiles={chatFiles}
                onFilesUsed={() => setChatFiles([])}
              />
            </div>
          )}
        </ErrorBoundary>
      )}

      {view === "mapa" && (
        <ErrorBoundary>
          <RegionalMap />
        </ErrorBoundary>
      )}

      {view === "3d" && (
        <ErrorBoundary>
          <Suspense
            fallback={
              <div
                style={{
                  height: 400,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  color: "var(--t-text-muted)",
                }}
              >
                Cargando Three.js...
              </div>
            }
          >
            <EmbeddingView3D />
          </Suspense>
        </ErrorBoundary>
      )}

      {view === "pipeline" && (
        <ErrorBoundary>
          <SubTabs
            items={[
              ["control", "Control Pipeline"],
              ["errores", "Feed de Errores"],
            ]}
            active={pipelineView}
            setActive={setPipelineView}
          />
          {pipelineView === "control" ? <PipelineControl /> : <ErrorPanel />}
        </ErrorBoundary>
      )}

      {view === "data" && (
        <ErrorBoundary>
          <DataProviderPanel
            onSendToOrquestador={(archivos) => {
              setChatFiles(archivos);
              setView("agentes");
              setAgentView("chat");
            }}
          />
        </ErrorBoundary>
      )}
      {view === "monitor" && (
        <ErrorBoundary>
          <MonitorPanel />
        </ErrorBoundary>
      )}

      {view === "bi" && (
        <ErrorBoundary>
          <SubTabs
            items={[
              ["dashboard", "BI Dashboard"],
              ["tendencias", "Tendencias Históricas"],
              ["curva-s", "Curva S (EVM)"],
            ]}
            active={biView}
            setActive={setBiView}
          />
          {biView === "dashboard" && <BIDashboard />}
          {biView === "tendencias" && <TendenciasPanel />}
          {biView === "curva-s" && <SCurveModule />}
        </ErrorBoundary>
      )}
      {view === "reportes" && (
        <ErrorBoundary>
          <ReportsPanel />
        </ErrorBoundary>
      )}

      {view === "proyectos" && (
        <ErrorBoundary>
          <ProyectosModule />
        </ErrorBoundary>
      )}
      {view === "financiero" && (
        <ErrorBoundary>
          <FinancialModule />
        </ErrorBoundary>
      )}
      {view === "gantt" && (
        <ErrorBoundary>
          <GanttModule />
        </ErrorBoundary>
      )}

      {view === "sistema" && (
        <ErrorBoundary>
          <SubTabs
            items={[
              ["control", "Control del Sistema"],
              ["proveedores", "Proveedores IA"],
              ["logs", "Visor de Logs"],
              ["backup", "Backup & Restore"],
              ["update", "Actualizaciones"],
            ]}
            active={sistemaView}
            setActive={setSistemaView}
          />
          {sistemaView === "control" && <SystemPanel />}
          {sistemaView === "proveedores" && <ProvidersPanel />}
          {sistemaView === "logs" && <LogsPanel />}
          {sistemaView === "backup" && <BackupPanel />}
          {sistemaView === "update" && <UpdatePanel />}
        </ErrorBoundary>
      )}

      {view === "security" && (
        <ErrorBoundary>
          <SecurityPanel />
        </ErrorBoundary>
      )}
    </MainLayout>
  );
}

export default function App() {
  // Auth + store global al iniciar
  useEffect(() => {
    initAuth()
      .then(() => {
        useAppStore.getState().inicializar();
      })
      .catch(() => {});
  }, []);

  return (
    <AuthProvider>
      <ProtectedRoute>
        <ErrorBoundary>
          <Dashboard />
        </ErrorBoundary>
      </ProtectedRoute>
      <NotificationContainer />
    </AuthProvider>
  );
}
