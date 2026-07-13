/**
 * SummarySection.jsx — Tarjetas de resumen del Dashboard (KPIs de `data/data.js`).
 *
 * Reconstruido desde el bundle de producción (react_dist/assets/index-CRDO1T5r.js,
 * funciones `Cb`/`_b`/`wb`): el fuente original de este componente no estaba
 * versionado.
 */
const BAR_COLOR = {
  blue: "#00d4ff",
  green: "#00ff9d",
  purple: "#a78bfa",
  amber: "#f59e0b",
  red: "#ff2d55",
};

function ProgressBar({ value, colorClass = "blue" }) {
  const pct = Math.min(Math.max(value, 0), 100);
  return (
    <div
      style={{
        width: "100%",
        height: 8,
        borderRadius: 20,
        background: "var(--t-border)",
        overflow: "hidden",
      }}
    >
      <div
        role="progressbar"
        aria-valuenow={pct}
        style={{
          height: "100%",
          borderRadius: 20,
          width: `${pct}%`,
          background: BAR_COLOR[colorClass] ?? BAR_COLOR.blue,
          transition: "width .5s ease",
        }}
      />
    </div>
  );
}

function SummaryCard({ title, value, total, unit, colorClass }) {
  const pct = total > 0 ? Math.round((value / total) * 100) : 0;
  return (
    <div
      style={{
        background: "var(--t-bg-card)",
        borderRadius: 16,
        padding: "1.1rem 1.2rem",
        boxShadow: "0 1px 2px rgba(0,0,0,.04)",
        border: "1px solid var(--t-border)",
        display: "flex",
        flexDirection: "column",
        gap: 12,
      }}
    >
      <p
        style={{
          margin: 0,
          fontSize: ".82rem",
          color: "var(--t-text-muted)",
          fontWeight: 500,
        }}
      >
        {title}
      </p>
      <div
        style={{
          display: "flex",
          alignItems: "flex-end",
          justifyContent: "space-between",
        }}
      >
        <p
          style={{
            margin: 0,
            fontSize: "1.5rem",
            fontWeight: 700,
            color: "var(--t-text)",
          }}
        >
          {value.toLocaleString("es-ES")}
        </p>
        <p
          style={{
            margin: "0 0 3px",
            fontSize: ".72rem",
            color: "var(--t-text-muted)",
          }}
        >
          {pct}%
        </p>
      </div>
      <ProgressBar value={pct} colorClass={colorClass} />
      <p
        style={{ margin: 0, fontSize: ".72rem", color: "var(--t-text-muted)" }}
      >
        {unit}
      </p>
    </div>
  );
}

export default function SummarySection({ data = [] }) {
  return (
    <section>
      <h2
        style={{
          fontSize: "1.05rem",
          fontWeight: 600,
          color: "var(--t-text)",
          marginBottom: "1rem",
        }}
      >
        Resumen General
      </h2>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
          gap: "1rem",
        }}
      >
        {data.map((item) => (
          <SummaryCard key={item.id} {...item} />
        ))}
      </div>
    </section>
  );
}
