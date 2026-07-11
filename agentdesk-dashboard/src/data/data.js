// data.js — datos de configuración del dashboard.
// Los contactos/equipo mock han sido eliminados.
// Los datos de agentes y métricas vienen del backend en tiempo real.

export const navigation = [
  { id: 1, label: "Dashboard", icon: "LayoutDashboard", path: "/" },
  { id: 2, label: "Reports",   icon: "BarChart2",       path: "/reports" },
  { id: 3, label: "Settings",  icon: "Settings",        path: "/settings" },
];

export const currentUser = {
  name: "AgentDesk", role: "Sistema IA", avatar: "AD",
};

// Resumen de KPIs — estos se actualizan dinámicamente en el dashboard
export const summary = [
  { id: 1, title: "Agentes Activos",    value: 0,  total: 10, unit: "agentes",  colorClass: "blue"   },
  { id: 2, title: "Tareas Completadas", value: 0,  total: 100, unit: "tareas",   colorClass: "green"  },
  { id: 3, title: "Reportes Generados", value: 0,  total: 50,  unit: "reportes", colorClass: "purple" },
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
