import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";

const PASOS = [
  { tab: "dashboard",  icono: "🏠", titulo: "Dashboard Principal",
    desc: "Vista general con KPIs en tiempo real, estado de todos los agentes y métricas de rendimiento del sistema. Tu punto de partida cada sesión." },
  { tab: "metricas",   icono: "📊", titulo: "Métricas de Rendimiento",
    desc: "Histogramas de latencia, series temporales y análisis de comportamiento para cada agente de IA. Detecta cuellos de botella antes de que impacten." },
  { tab: "agentes",    icono: "🤖", titulo: "Gestión de Agentes",
    desc: "Configura agentes especializados: Contador ICI, Supply Chain, Evaluador de Proyectos, Estratega y 13 especialistas más. Crea flujos entre ellos con el Editor Visual." },
  { tab: "mapa",       icono: "🗺️", titulo: "Mapa Regional",
    desc: "Visualización geográfica de las operaciones. Muestra la ubicación de cada agente y las áreas de cobertura de tu organización." },
  { tab: "3d",         icono: "🔮", titulo: "Embeddings 3D",
    desc: "Explora el espacio semántico de tu base de conocimiento en tres dimensiones. Visualiza cómo los conceptos se agrupan y relacionan entre sí." },
  { tab: "pipeline",   icono: "⚡", titulo: "Pipeline de Ejecución",
    desc: "Control y monitoreo en tiempo real del flujo de procesamiento. Inicia, detiene y observa las ejecuciones. El feed de errores te alerta de problemas." },
  { tab: "data",       icono: "📂", titulo: "Datos & Archivos",
    desc: "Carga archivos Excel, PDF o CSV para análisis. Conecta proveedores de datos externos. Los archivos quedan disponibles para todos los agentes." },
  { tab: "monitor",    icono: "🌐", titulo: "Monitor Web",
    desc: "Vigilancia continua de sitios web y APIs. Define alertas por cambio de contenido, disponibilidad o tiempo de respuesta." },
  { tab: "bi",         icono: "📈", titulo: "BI Dashboard",
    desc: "Business Intelligence avanzado con tendencias históricas, análisis predictivo y reportes ejecutivos. Tres vistas: Dashboard, Tendencias y Curva S." },
  { tab: "bi",         icono: "📉", titulo: "Curva S (EVM)",
    desc: "Análisis de Valor Ganado (Earned Value Management) para control de proyectos PMI. Monitorea SPI, CPI, EAC y detecta riesgo de sobrecosto en tiempo real." },
  { tab: "reportes",   icono: "📋", titulo: "Reportes Automáticos",
    desc: "Generación de reportes profesionales en PDF con análisis completo por agente y área. Configura reportes programados para distribución automática." },
  { tab: "sistema",    icono: "⚙️", titulo: "Sistema & Administración",
    desc: "Control del servidor FastAPI, visor de logs en tiempo real, backup/restore, gestión de proveedores de IA y actualizaciones del sistema." },
  { tab: "security",   icono: "🔐", titulo: "Seguridad & Configuración",
    desc: "Gestión de usuarios con RBAC (Admin/Supervisor/Viewer), Kill Switch remoto para bloqueo de emergencia y descarga del Manual de Usuario personalizado." },
];

const spring = { type: "spring", stiffness: 340, damping: 28 };

export default function WelcomeTour({ onClose, onNavigate }) {
  const [paso,    setPaso]    = useState(0);
  const [visible, setVisible] = useState(true);

  const cerrar = () => {
    setVisible(false);
    localStorage.setItem("agentdesk-tour-done", "1");
    setTimeout(onClose, 400);
  };

  const ir = (i) => {
    onNavigate?.(PASOS[i].tab);
    setPaso(i);
  };

  const siguiente = () => {
    const next = paso + 1;
    if (next < PASOS.length) { ir(next); }
    else cerrar();
  };

  const anterior = () => {
    if (paso > 0) ir(paso - 1);
  };

  const pct = Math.round(((paso + 1) / PASOS.length) * 100);

  return (
    <AnimatePresence>
      {visible && (
        <>
          {/* Overlay con blur */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: .25 }}
            onClick={cerrar}
            style={{
              position: "fixed", inset: 0, zIndex: 9990,
              background: "rgba(0,0,0,.72)",
              backdropFilter: "blur(6px)",
              WebkitBackdropFilter: "blur(6px)",
            }}
          />

          {/* Card principal */}
          <motion.div
            initial={{ opacity: 0, y: 48, scale: .9 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -24, scale: .95 }}
            transition={spring}
            onClick={e => e.stopPropagation()}
            style={{
              position: "fixed", top: "50%", left: "50%",
              transform: "translate(-50%, -50%)",
              zIndex: 10000,
              width: "min(500px, 94vw)",
              background: "rgba(4,12,30,.94)",
              backdropFilter: "blur(28px)",
              WebkitBackdropFilter: "blur(28px)",
              border: "1px solid rgba(0,212,255,.22)",
              borderRadius: 24,
              padding: "0",
              overflow: "hidden",
              boxShadow: "0 32px 80px rgba(0,0,0,.65), 0 0 0 1px rgba(0,212,255,.06), inset 0 1px 0 rgba(0,212,255,.08)",
            }}
          >
            {/* Barra de progreso */}
            <div style={{ height: 3, background: "rgba(255,255,255,.06)" }}>
              <motion.div
                animate={{ width: `${pct}%` }}
                transition={{ duration: .4, ease: "easeOut" }}
                style={{ height: "100%", background: "linear-gradient(90deg, #00d4ff, #7c3aed)", borderRadius: 2 }}
              />
            </div>

            <div style={{ padding: "1.8rem 2rem 1.5rem" }}>
              {/* Header */}
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1.4rem" }}>
                <span style={{ fontSize: ".7rem", fontWeight: 700, letterSpacing: ".1em", textTransform: "uppercase", color: "var(--t-accent)", opacity: .8 }}>
                  Módulo {paso + 1} / {PASOS.length}
                </span>
                <button
                  onClick={cerrar}
                  style={{ background: "rgba(255,255,255,.06)", border: "1px solid rgba(255,255,255,.1)", cursor: "pointer", color: "var(--t-text-muted)", borderRadius: 8, width: 28, height: 28, display: "flex", alignItems: "center", justifyContent: "center", fontSize: ".8rem" }}
                >
                  ✕
                </button>
              </div>

              {/* Contenido animado por paso */}
              <AnimatePresence mode="wait">
                <motion.div
                  key={paso}
                  initial={{ opacity: 0, x: 30 }}
                  animate={{ opacity: 1, x: 0 }}
                  exit={{ opacity: 0, x: -30 }}
                  transition={{ duration: .2, ease: "easeOut" }}
                  style={{ textAlign: "center", marginBottom: "1.6rem" }}
                >
                  <motion.div
                    initial={{ scale: .5, rotate: -15 }}
                    animate={{ scale: 1, rotate: 0 }}
                    transition={{ type: "spring", stiffness: 500, damping: 18, delay: .08 }}
                    style={{ fontSize: "3.8rem", lineHeight: 1, marginBottom: ".9rem", filter: "drop-shadow(0 0 16px rgba(0,212,255,.4))" }}
                  >
                    {PASOS[paso].icono}
                  </motion.div>

                  <h2 style={{
                    color: "var(--t-accent)", fontWeight: 700, fontSize: "1.25rem",
                    margin: "0 0 .7rem", letterSpacing: "-.01em",
                  }}>
                    {PASOS[paso].titulo}
                  </h2>

                  <p style={{
                    color: "var(--t-text-muted)", lineHeight: 1.75,
                    fontSize: ".875rem", margin: 0, maxWidth: 380, margin: "0 auto",
                  }}>
                    {PASOS[paso].desc}
                  </p>
                </motion.div>
              </AnimatePresence>

              {/* Puntos de navegación */}
              <div style={{ display: "flex", justifyContent: "center", gap: 5, marginBottom: "1.4rem", flexWrap: "wrap" }}>
                {PASOS.map((_, i) => (
                  <button
                    key={i}
                    onClick={() => ir(i)}
                    title={PASOS[i].titulo}
                    style={{
                      width: i === paso ? 22 : 7, height: 7, borderRadius: 4, border: "none",
                      cursor: "pointer", padding: 0, transition: "all .3s ease",
                      background: i === paso
                        ? "linear-gradient(90deg, #00d4ff, #7c3aed)"
                        : i < paso
                          ? "rgba(0,212,255,.45)"
                          : "rgba(255,255,255,.12)",
                    }}
                  />
                ))}
              </div>

              {/* Botones de navegación */}
              <div style={{ display: "flex", gap: ".75rem" }}>
                <button
                  onClick={anterior}
                  disabled={paso === 0}
                  style={{
                    flex: 1, padding: "10px 0", borderRadius: 12,
                    border: "1px solid var(--t-border)", background: "transparent",
                    color: paso === 0 ? "rgba(255,255,255,.2)" : "var(--t-text-muted)",
                    cursor: paso === 0 ? "not-allowed" : "pointer",
                    fontWeight: 600, fontSize: ".83rem", fontFamily: "inherit",
                    transition: "all .2s",
                  }}
                >
                  ← Anterior
                </button>

                <button
                  onClick={siguiente}
                  style={{
                    flex: 2.2, padding: "10px 0", borderRadius: 12, border: "none",
                    background: "linear-gradient(90deg, #00d4ff, #7c3aed)",
                    color: "#fff", cursor: "pointer", fontWeight: 700,
                    fontSize: ".88rem", fontFamily: "inherit",
                    boxShadow: "0 4px 18px rgba(0,212,255,.28)",
                    transition: "opacity .2s",
                  }}
                  onMouseEnter={e => { e.currentTarget.style.opacity = ".88"; }}
                  onMouseLeave={e => { e.currentTarget.style.opacity = "1"; }}
                >
                  {paso === PASOS.length - 1 ? "¡Comenzar ahora! 🚀" : "Siguiente →"}
                </button>
              </div>

              {/* Saltar */}
              <button
                onClick={cerrar}
                style={{
                  display: "block", width: "100%", marginTop: ".85rem",
                  background: "none", border: "none", cursor: "pointer",
                  color: "var(--t-text-muted)", fontSize: ".75rem", fontFamily: "inherit",
                  opacity: .6, transition: "opacity .2s",
                }}
                onMouseEnter={e => { e.currentTarget.style.opacity = "1"; }}
                onMouseLeave={e => { e.currentTarget.style.opacity = ".6"; }}
              >
                Saltar el tour y explorar por mi cuenta
              </button>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}
