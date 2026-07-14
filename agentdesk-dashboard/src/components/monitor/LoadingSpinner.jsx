/**
 * LoadingSpinner.jsx — Indicador de carga compartido del módulo Monitor.
 */
import { RefreshCw } from "../../icons.js";

export default function LoadingSpinner({ texto = "" }) {
  return (
    <div className="flex items-center justify-center gap-2.5 p-8 text-[.85rem] text-[var(--t-text-muted)]">
      <RefreshCw size={18} className="animate-spin text-[var(--t-accent)]" />
      {texto}
    </div>
  );
}
