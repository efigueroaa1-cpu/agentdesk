/**
 * MainLayout.jsx — Shell principal de la aplicación.
 *
 * Compone Sidebar + Header + área de contenido con scroll propio.
 * Reconstruido desde el bundle de producción (react_dist/assets/index-CRDO1T5r.js,
 * función `Sb`): el fuente original de este componente no estaba versionado.
 */
import { useState } from "react";
import Sidebar from "./Sidebar";
import Header from "./Header";

export default function MainLayout({
  user,
  navItems,
  children,
  query,
  onQueryChange,
  isDark,
  onToggleDark,
  onLogout,
  pageTitle,
  onAction,
  actionLabel,
  onNavChange,
}) {
  const [sidebarOpen, setSidebarOpen] = useState(false);

  return (
    <div className="flex h-screen bg-gray-50 dark:bg-gray-900 overflow-hidden transition-colors">
      <Sidebar
        navItems={navItems}
        user={user}
        isOpen={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
        onLogout={onLogout}
        onNavChange={onNavChange}
      />
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        <Header
          title={pageTitle}
          onMenuClick={() => setSidebarOpen(true)}
          query={query}
          onQueryChange={onQueryChange}
          isDark={isDark}
          onToggleDark={onToggleDark}
          onAction={onAction}
          actionLabel={actionLabel}
        />
        <main className="flex-1 overflow-y-auto p-5 min-h-0">{children}</main>
      </div>
    </div>
  );
}
