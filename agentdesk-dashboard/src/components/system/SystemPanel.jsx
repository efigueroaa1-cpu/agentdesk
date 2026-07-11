export default function SystemPanel() {
  return (
    <div style={{ padding: "2rem", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", minHeight: 200, gap: ".75rem" }}>
      <div style={{ fontSize: "2.5rem" }}>🖥️</div>
      <div style={{ color: "var(--t-accent)", fontWeight: 600, fontSize: ".9rem" }}>SystemPanel</div>
      <div style={{ color: "var(--t-text-muted)", fontSize: ".78rem", textAlign: "center", maxWidth: 320 }}>Panel de control del sistema</div>
    </div>
  );
}
