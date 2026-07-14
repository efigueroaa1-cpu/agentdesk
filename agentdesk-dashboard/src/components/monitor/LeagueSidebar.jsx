/**
 * LeagueSidebar.jsx — Selector lateral de ligas agrupadas (TheSportsDB).
 */
export default function LeagueSidebar({ porGrupo, liga, onSelect }) {
  return (
    <div className="flex max-h-[75vh] w-[220px] shrink-0 flex-col gap-1 overflow-y-auto rounded-xl border border-[var(--t-border)] bg-[var(--t-bg-surface)] p-2">
      {Object.entries(porGrupo).map(([grupo, ligas]) => (
        <div key={grupo}>
          <div className="mb-1 border-b border-[var(--t-border)] px-2 pb-1 pt-3 text-[.7rem] font-extrabold uppercase tracking-[.1em] text-amber-500">
            ⚽ {grupo}
          </div>
          {ligas.map((l) => {
            const activa = liga?.id === l.id;
            return (
              <button
                key={l.id}
                onClick={() => onSelect(l)}
                className={`mb-[3px] w-full cursor-pointer rounded-[10px] border-none border-l-[3px] px-3 py-[9px] text-left font-[inherit] ${
                  activa
                    ? "border-l-amber-500 bg-gradient-to-r from-amber-500/25 to-amber-500/[.08]"
                    : "border-l-transparent bg-transparent"
                }`}
              >
                <div
                  className={`text-[.82rem] ${
                    activa
                      ? "font-bold text-amber-400"
                      : "font-medium text-[var(--t-text)]"
                  }`}
                >
                  {l.nombre}
                </div>
                <div
                  className={`mt-0.5 text-[.68rem] ${
                    activa ? "text-amber-500" : "text-[var(--t-text-muted)]"
                  }`}
                >
                  {l.pais}
                </div>
              </button>
            );
          })}
        </div>
      ))}
    </div>
  );
}
