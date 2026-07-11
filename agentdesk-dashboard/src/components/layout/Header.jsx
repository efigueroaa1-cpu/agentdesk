import { useState } from "react";
import { Search, X, Bell, Plus, Sun, Moon, Menu } from "../../icons.js";
import { NotificationBadge } from "../ui/NotificationSystem";
import { useAlertasSinLeer, useAppStore } from "../../store/useAppStore.js";

export default function Header({ title = "Dashboard", onMenuClick, query = "", onQueryChange, onAction, actionLabel = "Nuevo", isDark, onToggleDark }) {
  const [focused, setFocused] = useState(false);
  return (
    <header className="h-16 bg-white dark:bg-gray-800 border-b border-gray-100 dark:border-gray-700 flex items-center gap-4 px-5 shrink-0 transition-colors">
      <button onClick={onMenuClick} className="lg:hidden text-gray-500 dark:text-gray-400 hover:text-gray-800 dark:hover:text-white shrink-0"><Menu size={22} /></button>
      <h1 className="text-lg font-semibold text-gray-800 dark:text-white hidden sm:block shrink-0">{title}</h1>
      <div className="hidden sm:block w-px h-5 bg-gray-200 dark:bg-gray-600 shrink-0" />
      <div className="flex-1 max-w-md">
        <div className={`relative flex items-center rounded-xl overflow-hidden transition-all ${focused ? "ring-2 ring-blue-400 bg-white dark:bg-gray-700" : "bg-gray-100 dark:bg-gray-700"}`}>
          <Search size={15} className="absolute left-3 text-gray-400 pointer-events-none" />
          <input type="text" value={query}
            onChange={e => onQueryChange?.(e.target.value)}
            onFocus={() => {
              setFocused(true);
              // Abrir GlobalSearch al hacer clic en la barra
              window.dispatchEvent(new KeyboardEvent("keydown", { key:"k", ctrlKey:true, bubbles:true }));
            }}
            onBlur={() => setFocused(false)}
            placeholder="Buscar agentes, reportes... (Ctrl+K)"
            className="w-full bg-transparent pl-9 pr-9 py-2.5 text-sm text-gray-700 dark:text-gray-200 placeholder-gray-400 outline-none"
            readOnly
          />
          {query && <button onClick={() => onQueryChange?.("")} className="absolute right-3 text-gray-400 hover:text-gray-600"><X size={14} /></button>}
        </div>
      </div>
      <div className="flex items-center gap-2 ml-auto shrink-0">
        {onToggleDark && (
          <button onClick={onToggleDark} className="w-9 h-9 flex items-center justify-center rounded-xl text-gray-500 dark:text-yellow-400 hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors">
            {isDark ? <Sun size={18} /> : <Moon size={18} />}
          </button>
        )}
        <button style={{ position:"relative" }} className="w-9 h-9 flex items-center justify-center rounded-xl text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors">
          <Bell size={18} />
          <NotificationBadge />
        </button>
        {onAction && (
          <button onClick={onAction} className="flex items-center gap-1.5 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm font-semibold rounded-xl transition-colors">
            <Plus size={16} /><span className="hidden sm:inline">{actionLabel}</span>
          </button>
        )}
      </div>
    </header>
  );
}
