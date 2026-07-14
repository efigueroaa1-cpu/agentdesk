/**
 * StatusBadge.jsx — Pill de estado de ejecución (ACTIVO / LISTO).
 */
export default function StatusBadge({ activo }) {
  return (
    <span
      className={`rounded-full border px-[9px] py-[3px] text-[.68rem] font-bold ${
        activo
          ? "border-neon-green/30 bg-neon-green/15 text-neon-green"
          : "border-slate-500/20 bg-slate-500/10 text-slate-500"
      }`}
    >
      {activo ? "ACTIVO" : "LISTO"}
    </span>
  );
}
