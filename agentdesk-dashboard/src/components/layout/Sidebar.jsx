import { useState, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  LayoutDashboard, BarChart2, Settings, LogOut,
  ChevronLeft, ChevronRight, X, Zap, Briefcase,
  Activity, Users, Globe, Layers, Database, Bell, Cpu,
  FileText, DollarSign, Calendar, Shield,
} from "../../icons.js";
import { useTheme }    from "../../hooks/useTheme";
import { useBranding } from "../../hooks/useBranding.js";

const ICON_MAP = {
  LayoutDashboard, Activity, Users, Globe, Layers, Zap, Database,
  Bell, Cpu, FileText, Settings, BarChart2, DollarSign, Calendar, Shield,
};

const springNav = { type: "spring", stiffness: 420, damping: 30 };

function NavItem({ label, icon, isActive, collapsed, onClick }) {
  const Icon = ICON_MAP[icon] ?? LayoutDashboard;
  return (
    <motion.button
      onClick={onClick}
      title={collapsed ? label : undefined}
      whileHover={{ x: collapsed ? 0 : 2 }}
      whileTap={{ scale: 0.97 }}
      transition={springNav}
      onMouseEnter={e => {
        if (!isActive) {
          e.currentTarget.style.background = "rgba(255,255,255,.05)";
          e.currentTarget.style.color = "var(--t-text)";
        }
      }}
      onMouseLeave={e => {
        if (!isActive) {
          e.currentTarget.style.background = "transparent";
          e.currentTarget.style.color = "var(--t-text-muted)";
        }
      }}
      style={{
        width: "100%",
        display: "flex",
        alignItems: "center",
        gap: "0.75rem",
        padding: "0.58rem 0.75rem",
        borderRadius: 12,
        border: `1px solid ${isActive ? "rgba(0,212,255,.22)" : "transparent"}`,
        background: isActive ? "rgba(0,212,255,.1)" : "transparent",
        color: isActive ? "var(--t-accent)" : "var(--t-text-muted)",
        cursor: "pointer",
        fontFamily: "inherit",
        fontSize: "0.875rem",
        fontWeight: 500,
        textAlign: "left",
        justifyContent: collapsed ? "center" : undefined,
        transition: "background .15s, color .15s, border-color .15s",
        flexShrink: 0,
      }}
    >
      <Icon size={18} style={{ flexShrink: 0 }} />
      {!collapsed && (
        <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {label}
        </span>
      )}
    </motion.button>
  );
}

export default function Sidebar({ navItems = [], user = {}, isOpen, onClose, onLogout, onNavChange }) {
  const [activeId,  setActiveId]  = useState(navItems[0]?.id ?? 1);
  const [collapsed, setCollapsed] = useState(false);
  const { toggle: toggleTheme, isCyberpunk } = useTheme();
  const branding = useBranding();

  // Auto-collapse en pantallas medianas (1024–1280 px)
  useEffect(() => {
    const onResize = () => {
      const w = window.innerWidth;
      if (w >= 1024 && w < 1280) setCollapsed(true);
      else if (w >= 1280) setCollapsed(false);
    };
    onResize();
    window.addEventListener("resize", onResize, { passive: true });
    return () => window.removeEventListener("resize", onResize);
  }, []);

  return (
    <>
      {/* Overlay móvil animado */}
      <AnimatePresence>
        {isOpen && (
          <motion.div
            key="sb-overlay"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            onClick={onClose}
            className="lg:hidden"
            style={{
              position: "fixed", inset: 0, zIndex: 20,
              background: "rgba(0,0,0,.65)",
              backdropFilter: "blur(4px)",
              WebkitBackdropFilter: "blur(4px)",
            }}
          />
        )}
      </AnimatePresence>

      {/* Sidebar glassmorphism */}
      <aside
        style={{
          background: "rgba(4,12,30,.88)",
          backdropFilter: "blur(20px)",
          WebkitBackdropFilter: "blur(20px)",
          borderRight: "1px solid var(--t-border)",
          boxShadow: "4px 0 28px rgba(0,0,0,.35), inset -1px 0 0 rgba(0,212,255,.05)",
          display: "flex",
          flexDirection: "column",
          color: "var(--t-text)",
          overflow: "hidden",
          flexShrink: 0,
          transition: "transform .3s cubic-bezier(.4,0,.2,1)",
        }}
        className={`fixed top-0 left-0 h-full z-30
                    ${collapsed ? "w-[72px]" : "w-72"}
                    transition-[width] duration-300 ease-in-out
                    ${isOpen ? "translate-x-0" : "-translate-x-full"}
                    lg:relative lg:translate-x-0 lg:z-auto`}
      >
        {/* Header: logo + branding + controles */}
        <div
          style={{
            height: 64, display: "flex", alignItems: "center",
            padding: collapsed ? "0.5rem 0.5rem" : "0 1rem",
            borderBottom: "1px solid var(--t-border)",
            flexShrink: 0,
            justifyContent: collapsed ? "center" : "space-between",
            flexDirection: collapsed ? "column" : "row",
            gap: collapsed ? "0.25rem" : 0,
          }}
        >
          {!collapsed && (
            <div style={{ display: "flex", alignItems: "center", gap: "0.4rem", minWidth: 0 }}>
              <span style={{
                fontWeight: 800, fontSize: "1.05rem", letterSpacing: "-.02em",
                color: "var(--t-accent)",
                textShadow: "0 0 14px rgba(0,212,255,.45)",
                flexShrink: 0,
              }}>
                {branding.logo_texto}
              </span>
              <span style={{
                color: "var(--t-text)", fontWeight: 600, fontSize: ".9rem",
                overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
              }}>
                {branding.app_name}
              </span>
              <button
                onClick={toggleTheme}
                title={isCyberpunk ? "Cambiar a Corporate" : "Cambiar a Cyberpunk"}
                style={{
                  display: "flex", alignItems: "center", gap: 3,
                  padding: "2px 6px", borderRadius: 7, fontSize: ".67rem",
                  fontWeight: 700, cursor: "pointer", fontFamily: "inherit",
                  border: "1px solid var(--t-accent)",
                  background: isCyberpunk ? "rgba(0,212,255,.1)" : "rgba(37,99,235,.1)",
                  color: "var(--t-accent)", transition: "background .2s",
                  flexShrink: 0,
                }}
              >
                {isCyberpunk ? <Zap size={9} /> : <Briefcase size={9} />}
                {isCyberpunk ? "CP" : "CORP"}
              </button>
            </div>
          )}

          {collapsed && (
            <button
              onClick={toggleTheme}
              title={isCyberpunk ? "Corporate" : "Cyberpunk"}
              style={{
                width: 28, height: 28, display: "flex", alignItems: "center",
                justifyContent: "center", borderRadius: 8, cursor: "pointer",
                border: "1px solid var(--t-accent)", background: "transparent",
                color: "var(--t-accent)",
              }}
            >
              {isCyberpunk ? <Zap size={12} /> : <Briefcase size={12} />}
            </button>
          )}

          {/* Collapse toggle — solo desktop */}
          <button
            onClick={() => setCollapsed(v => !v)}
            className="hidden lg:flex"
            style={{
              width: 26, height: 26, display: "flex", alignItems: "center",
              justifyContent: "center", borderRadius: 7, cursor: "pointer",
              border: "none", background: "transparent",
              color: "var(--t-text-muted)", transition: "color .15s, background .15s",
              flexShrink: 0,
            }}
            onMouseEnter={e => { e.currentTarget.style.color = "var(--t-text)"; e.currentTarget.style.background = "rgba(255,255,255,.07)"; }}
            onMouseLeave={e => { e.currentTarget.style.color = "var(--t-text-muted)"; e.currentTarget.style.background = "transparent"; }}
          >
            {collapsed ? <ChevronRight size={14} /> : <ChevronLeft size={14} />}
          </button>

          {/* Cerrar — solo mobile */}
          <button
            onClick={onClose}
            className="lg:hidden"
            style={{ background: "none", border: "none", cursor: "pointer", color: "var(--t-text-muted)" }}
          >
            <X size={20} />
          </button>
        </div>

        {/* Navegación */}
        <nav style={{
          flex: 1, overflowY: "auto", padding: "0.6rem",
          display: "flex", flexDirection: "column", gap: "0.2rem",
        }}>
          {navItems.map(item => (
            <NavItem
              key={item.id}
              {...item}
              isActive={activeId === item.id}
              collapsed={collapsed}
              onClick={() => { setActiveId(item.id); onNavChange?.(item.id); onClose?.(); }}
            />
          ))}
        </nav>

        {/* Footer — usuario */}
        <div style={{
          borderTop: "1px solid var(--t-border)",
          padding: "0.6rem",
          display: "flex",
          alignItems: "center",
          gap: collapsed ? 0 : "0.75rem",
          justifyContent: collapsed ? "center" : undefined,
          flexShrink: 0,
        }}>
          <div style={{
            width: 34, height: 34, borderRadius: "50%", flexShrink: 0,
            background: "linear-gradient(135deg, var(--t-accent), #7c3aed)",
            display: "flex", alignItems: "center", justifyContent: "center",
            fontWeight: 700, fontSize: ".82rem", color: "#fff",
          }}>
            {user.avatar}
          </div>

          {!collapsed && (
            <>
              <div style={{ flex: 1, minWidth: 0 }}>
                <p style={{ margin: 0, fontSize: ".84rem", fontWeight: 600, color: "var(--t-text)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {user.name}
                </p>
                <p style={{ margin: 0, fontSize: ".71rem", color: "var(--t-text-muted)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {user.role}
                </p>
              </div>
              {onLogout && (
                <button
                  onClick={onLogout}
                  title="Cerrar sesión"
                  style={{
                    background: "none", border: "none", cursor: "pointer",
                    color: "var(--t-text-muted)", flexShrink: 0,
                    padding: "4px", borderRadius: 6,
                    transition: "color .15s",
                  }}
                  onMouseEnter={e => { e.currentTarget.style.color = "var(--t-danger)"; }}
                  onMouseLeave={e => { e.currentTarget.style.color = "var(--t-text-muted)"; }}
                >
                  <LogOut size={16} />
                </button>
              )}
            </>
          )}
        </div>
      </aside>
    </>
  );
}
