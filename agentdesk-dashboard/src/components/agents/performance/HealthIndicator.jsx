/**
 * HealthIndicator.jsx — Salud del agente según su tasa de éxito (emoji + etiqueta).
 */
import { estadoDeTasa } from "./statsUtils";

export default function HealthIndicator({ tasa }) {
  const estado = estadoDeTasa(tasa);
  return (
    <div className="text-center">
      <div className="text-[22px]">{estado.emoji}</div>
      <div className={`mt-0.5 text-[.62rem] font-semibold ${estado.textCls}`}>
        {estado.label}
      </div>
    </div>
  );
}
