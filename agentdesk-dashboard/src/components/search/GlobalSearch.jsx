import { useState, useEffect, useCallback } from "react";
import { X, Search } from "../../icons.js";

const ITEMS = [
  { label: "Dashboard",          tab: "dashboard" },
  { label: "Métricas",           tab: "metricas" },
  { label: "Agentes",            tab: "agentes" },
  { label: "Mapa Regional",      tab: "mapa" },
  { label: "Embeddings 3D",      tab: "3d" },
  { label: "Pipeline",           tab: "pipeline" },
  { label: "Datos",              tab: "data" },
  { label: "Monitor Web",        tab: "monitor" },
  { label: "BI Dashboard",       tab: "bi" },
  { label: "Curva S (EVM)",      tab: "bi",   sub: "curva-s" },
  { label: "Reportes",           tab: "reportes" },
  { label: "Sistema",            tab: "sistema" },
  { label: "Seguridad",          tab: "security" },
];

export default function GlobalSearch({ onNavigate }) {
  const [open,  setOpen]  = useState(false);
  const [query, setQuery] = useState("");

  const toggle = useCallback(() => setOpen(o => !o), []);

  useEffect(() => {
    const handler = (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "k") { e.preventDefault(); toggle(); }
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [toggle]);

  if (!open) return null;

  const filtered = ITEMS.filter(i => i.label.toLowerCase().includes(query.toLowerCase()));

  return (
    <div
      style={{
        position: "fixed", inset: 0, zIndex: 9000,
        background: "rgba(0,0,0,.7)", backdropFilter: "blur(6px)",
        display: "flex", alignItems: "flex-start", justifyContent: "center",
        paddingTop: "12vh",
      }}
      onClick={() => setOpen(false)}
    >
      <div
        className="glass-modal"
        style={{ width: "min(520px, 92vw)", borderRadius: 16, overflow: "hidden" }}
        onClick={e => e.stopPropagation()}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "12px 16px", borderBottom: "1px solid var(--t-border)" }}>
          <Search size={16} style={{ color: "var(--t-text-muted)", flexShrink: 0 }} />
          <input
            autoFocus
            value={query}
            onChange={e => setQuery(e.target.value)}
            placeholder="Buscar módulos y vistas..."
            style={{ flex: 1, background: "transparent", border: "none", outline: "none", color: "var(--t-text)", fontSize: ".9rem", fontFamily: "inherit" }}
          />
          <button onClick={() => setOpen(false)} style={{ background: "none", border: "none", cursor: "pointer", color: "var(--t-text-muted)" }}>
            <X size={14} />
          </button>
        </div>
        <div style={{ maxHeight: 320, overflowY: "auto" }}>
          {filtered.map((item, i) => (
            <button
              key={i}
              onClick={() => { onNavigate?.(item.tab, item.sub); setOpen(false); setQuery(""); }}
              style={{
                width: "100%", textAlign: "left", padding: "10px 16px",
                background: "transparent", border: "none", cursor: "pointer",
                color: "var(--t-text)", fontSize: ".85rem", fontFamily: "inherit",
                borderBottom: "1px solid rgba(255,255,255,.04)",
                transition: "background .15s",
              }}
              onMouseEnter={e => { e.currentTarget.style.background = "var(--t-accent-dim)"; }}
              onMouseLeave={e => { e.currentTarget.style.background = "transparent"; }}
            >
              {item.label}
            </button>
          ))}
          {!filtered.length && (
            <div style={{ padding: "1.5rem", textAlign: "center", color: "var(--t-text-muted)", fontSize: ".8rem" }}>
              Sin resultados para "{query}"
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
