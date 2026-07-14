/**
 * LeaguesTab.jsx — Pestaña "Ligas & Tablas": orquesta sidebar, tarjetas de
 * estadísticas y las vistas tabla/recientes/próximos (TheSportsDB vía backend).
 */
import { useState, useEffect, useCallback } from "react";
import { API_BASE } from "../../services/agent.service";
import { addNotification } from "../ui/NotificationSystem";
import { LeagueHeader, LeagueStatsCards } from "./LeagueHeader";
import LeagueSidebar from "./LeagueSidebar";
import LeagueStandingsTable from "./LeagueStandingsTable";
import LeagueMatchList from "./LeagueMatchList";
import LoadingSpinner from "./LoadingSpinner";
import TabPills from "./TabPills";

export default function LeaguesTab() {
  const [porGrupo, setPorGrupo] = useState({});
  const [liga, setLiga] = useState(null);
  const [datos, setDatos] = useState(null);
  const [cargando, setCargando] = useState(false);
  const [vista, setVista] = useState("tabla");

  useEffect(() => {
    fetch(`${API_BASE}/monitor/equipos-preset`)
      .then((r) => r.json())
      .then((d) => {
        const ligas = d.ligas ?? [];
        const grupos = {};
        ligas.forEach(
          (l) => (grupos[l.grupo] = [...(grupos[l.grupo] ?? []), l]),
        );
        setPorGrupo(grupos);
        if (ligas.length > 0) setLiga(ligas[0]);
      })
      .catch(() => {});
  }, []);

  const cargarLiga = useCallback(async (l) => {
    if (!l) return;
    setCargando(true);
    setDatos(null);
    setVista("tabla");
    try {
      const r = await fetch(
        `${API_BASE}/monitor/liga/${l.id}?nombre=${encodeURIComponent(l.nombre)}`,
      ).then((res) => res.json());
      if (r.ok) {
        setDatos(r.data);
        if (
          (r.data?.equipos_tabla ?? []).length === 0 &&
          (r.data?.partidos_recientes ?? []).length > 0
        )
          setVista("recientes");
      } else {
        addNotification({
          message: r.error || "Error al cargar liga",
          type: "error",
        });
      }
    } catch (e) {
      addNotification({
        message: "Error de conexión: " + e.message,
        type: "error",
      });
    } finally {
      setCargando(false);
    }
  }, []);

  useEffect(() => {
    if (liga) cargarLiga(liga);
  }, [liga, cargarLiga]);

  const tabla = datos?.equipos_tabla ?? [];
  const recientes = datos?.partidos_recientes ?? [];
  const proximos = datos?.proximos_partidos ?? [];
  const stats = datos?.estadisticas_liga ?? {};

  return (
    <div className="flex min-h-[500px] gap-4">
      <LeagueSidebar porGrupo={porGrupo} liga={liga} onSelect={setLiga} />
      <div className="flex min-w-0 flex-1 flex-col gap-3">
        {liga && (
          <LeagueHeader
            liga={liga}
            datos={datos}
            stats={stats}
            cargando={cargando}
            onRefrescar={() => cargarLiga(liga)}
          />
        )}

        {cargando && (
          <LoadingSpinner texto={`Cargando ${liga?.nombre ?? ""}...`} />
        )}

        {datos && !cargando && (
          <>
            <LeagueStatsCards stats={stats} />

            <TabPills
              items={[
                { id: "tabla", label: `📊 Tabla (${tabla.length})` },
                {
                  id: "recientes",
                  label: `🕐 Recientes (${recientes.length})`,
                },
                { id: "proximos", label: `📅 Próximos (${proximos.length})` },
              ]}
              active={vista}
              onChange={setVista}
            />

            {vista === "tabla" && <LeagueStandingsTable tabla={tabla} />}
            {vista === "recientes" && (
              <LeagueMatchList partidos={recientes} modo="recientes" />
            )}
            {vista === "proximos" && (
              <LeagueMatchList partidos={proximos} modo="proximos" />
            )}
          </>
        )}

        {!datos && !cargando && (
          <div className="flex min-h-[200px] flex-1 flex-col items-center justify-center gap-3 text-[.85rem] text-[var(--t-text-muted)]">
            <span className="text-[32px]">⚽</span>
            <div>Selecciona una liga del panel izquierdo</div>
          </div>
        )}
      </div>
    </div>
  );
}
