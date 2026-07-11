import { useState, useCallback, useEffect } from "react";
import { useAppStore } from "../../store/useAppStore.js";

let _dispatch = null;

export function addNotification({ title, message, type = "info" }) {
  _dispatch?.({ id: Date.now(), title, message, type });
}

export function NotificationBadge() {
  const count = useAppStore(s => s.alertas.filter(a => !a.leida).length);
  if (!count) return null;
  return (
    <span style={{
      position: "absolute", top: 6, right: 6,
      width: 16, height: 16, borderRadius: "50%",
      background: "var(--t-danger)", color: "#fff",
      fontSize: "9px", fontWeight: 700,
      display: "flex", alignItems: "center", justifyContent: "center",
    }}>
      {count > 9 ? "9+" : count}
    </span>
  );
}

export function NotificationContainer() {
  const [toasts, setToasts] = useState([]);

  const add = useCallback((notif) => {
    setToasts(t => [...t, notif]);
    setTimeout(() => setToasts(t => t.filter(n => n.id !== notif.id)), 4000);
  }, []);

  useEffect(() => { _dispatch = add; return () => { _dispatch = null; }; }, [add]);

  if (!toasts.length) return null;

  return (
    <div style={{
      position: "fixed", bottom: "1.5rem", right: "1.5rem",
      zIndex: 99999, display: "flex", flexDirection: "column", gap: ".5rem",
      pointerEvents: "none",
    }}>
      {toasts.map(t => (
        <div key={t.id} className="glass-modal animate-fade-in" style={{
          padding: ".75rem 1rem", borderRadius: 12, minWidth: 240, maxWidth: 340,
          borderLeft: `3px solid ${t.type === "error" ? "var(--t-danger)" : t.type === "success" ? "var(--t-success)" : "var(--t-accent)"}`,
        }}>
          {t.title && <div style={{ fontWeight: 600, fontSize: ".8rem", color: "var(--t-text)", marginBottom: 2 }}>{t.title}</div>}
          <div style={{ fontSize: ".75rem", color: "var(--t-text-muted)" }}>{t.message}</div>
        </div>
      ))}
    </div>
  );
}
