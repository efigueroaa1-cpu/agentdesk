/**
 * LeagueMatchList.jsx — Partidos recientes (con marcador) o próximos (VS).
 */
function Vacio({ texto }) {
  return (
    <div className="rounded-xl border-2 border-dashed border-[var(--t-border)] p-8 text-center text-[.85rem] text-[var(--t-text-muted)]">
      {texto}
    </div>
  );
}

export default function LeagueMatchList({ partidos, modo }) {
  if (partidos.length === 0)
    return (
      <Vacio
        texto={
          modo === "recientes"
            ? "Sin datos de partidos recientes."
            : "Sin próximos partidos disponibles."
        }
      />
    );

  if (modo === "proximos")
    return (
      <div className="flex flex-col gap-2">
        {partidos.map((p, i) => (
          <div
            key={i}
            className="grid grid-cols-[120px_1fr_auto_1fr_60px] items-center gap-4 rounded-xl border border-neon-blue/30 bg-neon-blue/[.04] px-[18px] py-3.5"
          >
            <div>
              <div className="text-[.82rem] font-extrabold text-[var(--t-accent)]">
                {p.fecha}
              </div>
              {p.hora && (
                <div className="mt-0.5 text-[.78rem] text-[var(--t-text-muted)]">
                  🕐 {p.hora}
                </div>
              )}
            </div>
            <div className="text-right font-bold text-[var(--t-text)]">
              {p.local}
            </div>
            <div className="min-w-[50px] rounded-[10px] border border-neon-blue/40 bg-neon-blue/10 px-3 py-1.5 text-center text-[.85rem] font-black text-[var(--t-accent)]">
              VS
            </div>
            <div className="text-left font-bold text-[var(--t-text)]">
              {p.visita}
            </div>
            <div className="text-center text-[.7rem] text-[var(--t-text-muted)]">
              {p.ronda}
            </div>
          </div>
        ))}
      </div>
    );

  return (
    <div className="flex flex-col gap-2">
      {[...partidos].reverse().map((p, i) => {
        const gl = Number(p.gl ?? -1);
        const gv = Number(p.gv ?? -1);
        const localGana = gl > gv;
        return (
          <div
            key={i}
            className="grid grid-cols-[100px_1fr_auto_1fr_80px] items-center gap-4 rounded-xl border border-[var(--t-border)] bg-[var(--t-bg-base)] px-[18px] py-3.5"
          >
            <div>
              <div className="text-[.8rem] font-bold text-[var(--t-accent)]">
                {p.fecha}
              </div>
              {p.ronda && (
                <div className="mt-0.5 text-[.68rem] text-[var(--t-text-muted)]">
                  {p.ronda}
                </div>
              )}
            </div>
            <div
              className={`text-right font-bold ${
                localGana
                  ? "text-[var(--t-text)]"
                  : "text-[var(--t-text-muted)]"
              }`}
            >
              {p.local}
            </div>
            <div className="min-w-[80px] rounded-[10px] border-2 border-[var(--t-border)] bg-[var(--t-bg-surface)] px-3.5 py-2 text-center text-[1.3rem] font-black">
              {gl >= 0 ? `${gl} - ${gv}` : "?"}
            </div>
            <div
              className={`text-left font-bold ${
                gv > gl ? "text-[var(--t-text)]" : "text-[var(--t-text-muted)]"
              }`}
            >
              {p.visita}
            </div>
            <div className="text-center">
              {gl === gv ? (
                <span className="rounded-full bg-amber-500/15 px-2 py-[3px] text-[.72rem] font-bold text-amber-500">
                  EMPATE
                </span>
              ) : (
                <span className="rounded-full bg-neon-green/[.12] px-2 py-[3px] text-[.72rem] font-bold text-neon-green">
                  {localGana ? "L" : "V"} gana
                </span>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
