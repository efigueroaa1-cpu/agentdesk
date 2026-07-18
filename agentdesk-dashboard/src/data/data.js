// data.js — datos de configuración del dashboard.
// Los contactos/equipo mock han sido eliminados.
// Los datos de agentes y métricas vienen del backend en tiempo real.

export const navigation = [
  { id: 1, label: "Dashboard", icon: "LayoutDashboard", path: "/" },
  { id: 2, label: "Métricas", icon: "Activity", path: "/metricas" },
  { id: 3, label: "Agentes", icon: "Users", path: "/agentes" },
  { id: 4, label: "Mapa Regional", icon: "Globe", path: "/mapa" },
  { id: 5, label: "Embeddings 3D", icon: "Layers", path: "/3d" },
  { id: 6, label: "Pipeline", icon: "Zap", path: "/pipeline" },
  { id: 7, label: "Datos", icon: "Database", path: "/data" },
  { id: 8, label: "Monitor Web", icon: "Bell", path: "/monitor" },
  { id: 9, label: "BI Dashboard", icon: "Cpu", path: "/bi" },
  { id: 10, label: "Diagnóstico", icon: "Activity", path: "/diagnostico" },
  { id: 11, label: "Reportes", icon: "FileText", path: "/reportes" },
  { id: 12, label: "Sistema", icon: "Settings", path: "/sistema" },
  { id: 14, label: "Proyectos", icon: "BarChart2", path: "/proyectos" },
  { id: 15, label: "Financiero", icon: "DollarSign", path: "/financiero" },
  { id: 16, label: "Gantt P6", icon: "Calendar", path: "/gantt" },
  { id: 17, label: "Copiloto", icon: "Zap", path: "/copiloto" },
  { id: 13, label: "Seguridad", icon: "Shield", path: "/security" },
];

export const currentUser = {
  name: "AgentDesk",
  role: "Sistema IA",
  avatar: "AD",
};

// Resumen de KPIs — estos se actualizan dinámicamente en el dashboard
export const summary = [
  {
    id: 1,
    title: "Agentes Activos",
    value: 0,
    total: 10,
    unit: "agentes",
    colorClass: "blue",
  },
  {
    id: 2,
    title: "Tareas Completadas",
    value: 0,
    total: 100,
    unit: "tareas",
    colorClass: "green",
  },
  {
    id: 3,
    title: "Reportes Generados",
    value: 0,
    total: 50,
    unit: "reportes",
    colorClass: "purple",
  },
];

// Lista de proyectos/áreas activas (configurable desde backend)
export const projects = [];

// Tareas del orquestador — vacío por defecto, se llenan desde la API
export const tasks = [];

// Actividad del pipeline (datos de ejemplo para el chart)
export const activityData = [
  { mes: "Ene", tareas: 0, ingresos: 0 },
  { mes: "Feb", tareas: 0, ingresos: 0 },
  { mes: "Mar", tareas: 0, ingresos: 0 },
  { mes: "Abr", tareas: 0, ingresos: 0 },
  { mes: "May", tareas: 0, ingresos: 0 },
  { mes: "Jun", tareas: 0, ingresos: 0 },
];

// Contactos: lista vacía (equipo mock eliminado)
// Para configurar el equipo, usar la sección Usuarios en Seguridad.
export const contacts = [];
