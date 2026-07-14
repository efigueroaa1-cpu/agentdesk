/**
 * ProgressBar.jsx — Barra de progreso de tarea: determinada (%) o
 * indeterminada (animación slide) mientras no hay estimación de duración.
 */
export default function ProgressBar({ activo, progreso }) {
  if (!activo) {
    return (
      <div className="h-1.5 rounded-md bg-[var(--t-border)]">
        <div className="h-full w-full rounded-md bg-slate-800" />
      </div>
    );
  }
  return (
    <>
      <div className="mb-1 flex items-center justify-between">
        <span className="text-[.7rem] font-bold text-neon-green">
          {progreso !== null ? `${progreso}%` : "Procesando..."}
        </span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-md bg-[var(--t-border)]">
        {progreso !== null ? (
          <div
            className="h-full rounded-md bg-gradient-to-r from-neon-green to-neon-blue transition-[width] duration-500"
            style={{ width: `${progreso}%` }}
          />
        ) : (
          <div className="h-full w-[30%] animate-slide rounded-md bg-gradient-to-r from-neon-green to-neon-blue" />
        )}
      </div>
    </>
  );
}
