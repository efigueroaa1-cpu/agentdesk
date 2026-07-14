/**
 * LatencyChart.jsx — Latencia promedio + sparkline de barras (últimas 8 tareas).
 */
export default function LatencyChart({ latencias, promedio }) {
  const ultimas = latencias.slice(-8);
  const max = Math.max(...ultimas, 1);
  return (
    <div>
      <div className="font-bold text-[.88rem] text-[var(--t-text)]">
        {promedio ? `${promedio}s` : "—"}
      </div>
      <div className="mt-1 flex h-3.5 items-end gap-px">
        {ultimas.map((l, i) => (
          <div
            key={i}
            className={`w-1 rounded-sm opacity-80 ${
              l > 2 ? "bg-neon-red" : l > 0.5 ? "bg-amber-500" : "bg-neon-green"
            }`}
            style={{ height: Math.max(2, (l / max) * 14) }}
          />
        ))}
      </div>
    </div>
  );
}
