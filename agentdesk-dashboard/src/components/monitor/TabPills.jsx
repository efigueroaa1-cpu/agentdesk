/**
 * TabPills.jsx — Fila de pestañas tipo pill, reutilizada en el módulo Monitor.
 */
export default function TabPills({ items, active, onChange, accent = "blue" }) {
  const ACTIVA = {
    blue: "border-[var(--t-accent)] bg-neon-blue/10 text-[var(--t-accent)]",
    amber: "border-amber-500 bg-amber-500/10 text-amber-500",
  }[accent];
  return (
    <div className="flex flex-wrap gap-1.5">
      {items.map((t) => (
        <button
          key={t.id}
          onClick={() => onChange(t.id)}
          className={`cursor-pointer rounded-full border px-4 py-1.5 font-[inherit] text-[.76rem] font-semibold ${
            active === t.id
              ? ACTIVA
              : "border-[var(--t-border)] bg-transparent text-[var(--t-text-muted)]"
          }`}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}
