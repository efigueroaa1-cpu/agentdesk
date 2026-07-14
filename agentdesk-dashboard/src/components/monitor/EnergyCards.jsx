/**
 * EnergyCards.jsx — Tarjetas presentacionales de la pestaña Energía:
 * panel renovable (solar/eólico), grilla de demanda y grilla de precio spot.
 */
export function PanelRenovable({ titulo, cls, filas }) {
  return (
    <div className={`rounded-[14px] border-2 p-5 ${cls.box}`}>
      <div className={`mb-2.5 text-[.72rem] font-bold uppercase ${cls.text}`}>
        {titulo}
      </div>
      {filas.map(([k, v]) => (
        <div
          key={k}
          className={`flex justify-between border-b py-[5px] text-[.78rem] ${cls.divider}`}
        >
          <span className="text-[var(--t-text-muted)]">{k}</span>
          <span className={`font-semibold ${cls.text}`}>{v}</span>
        </div>
      ))}
    </div>
  );
}

export function DemandaGrid({ dias }) {
  return (
    <div className="grid grid-cols-3 gap-2.5">
      {dias.map(([label, temp, dem]) => (
        <div
          key={label}
          className="rounded-xl border-2 border-[var(--t-border)] bg-[var(--t-bg-base)] p-4 text-center"
        >
          <div className="mb-1.5 text-[.72rem] text-[var(--t-text-muted)]">
            {label}
          </div>
          <div className="text-[1.6rem] font-extrabold text-[var(--t-text)]">
            {temp}°C
          </div>
          <div className="mt-1.5 inline-block rounded-full bg-amber-500/15 px-2.5 py-[3px] text-[.7rem] font-bold text-amber-500">
            Demanda {dem}
          </div>
        </div>
      ))}
    </div>
  );
}

export function SpotGrid({ tarjetas }) {
  return (
    <div className="grid grid-cols-[repeat(auto-fill,minmax(160px,1fr))] gap-2.5">
      {tarjetas.map(([label, val, cls]) => (
        <div key={label} className={`rounded-xl border px-3.5 py-3 ${cls}`}>
          <div className="mb-[5px] text-[.64rem] text-[var(--t-text-muted)]">
            {label}
          </div>
          <div className="text-[1.2rem] font-extrabold">{val}</div>
        </div>
      ))}
    </div>
  );
}
