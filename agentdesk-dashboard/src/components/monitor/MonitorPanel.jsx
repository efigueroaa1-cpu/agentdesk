export default function MonitorPanel() {
  return (
    <div style={{ padding: "2rem", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", minHeight: 200, gap: ".75rem" }}>
      <div style={{ fontSize: "2.5rem" }}>🌐</div>
      <div style={{ color: "var(--t-accent)", fontWeight: 600, fontSize: ".9rem" }}>MonitorPanel</div>
      <div style={{ color: "var(--t-text-muted)", fontSize: ".78rem", textAlign: "center", maxWidth: 320 }}>Monitor de sitios web y APIs</div>
    </div>
  );
}
