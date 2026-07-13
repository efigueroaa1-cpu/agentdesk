/**
 * MetricsPanel.jsx — Pestaña "Métricas": CPU/RAM en tiempo real (Tauri
 * sysinfo), latencia por guardrail del pipeline y estado acumulado de
 * ejecuciones (OK / abortados / errores), alimentado por el WebSocket de
 * telemetría.
 *
 * Reconstruido desde el bundle de producción (react_dist/assets/index-CRDO1T5r.js,
 * función `Fb`): el fuente original de este componente no estaba versionado.
 */
import { useState, useEffect } from "react";
import { Cpu, Activity, CheckCircle2, XCircle, Zap } from "../../icons.js";
import { AgentService } from "../../services/agent.service";

const GUARD_COLOR = {
  "Recursion Guard": "#f59e0b",
  "Tone Guard": "#ef4444",
  "Grounding Guard": "#8b5cf6",
  "Logic Integrity Filter": "#06b6d4",
};

function Sparkline({ data, color, label, height = 50 }) {
  if (data.length < 2) {
    return (
      <div
        style={{
          height,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          color: "var(--t-text-muted)",
          fontSize: ".68rem",
        }}
      >
        Esperando datos...
      </div>
    );
  }
  const max = Math.max(...data, 1),
    min = Math.min(...data),
    range = max - min || 1;
  const points = data
    .map((v, i) => {
      const x = (i / (data.length - 1)) * 100;
      const y = (1 - (v - min) / range) * (height - 4) + 2;
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(" ");
  return (
    <div>
      {label && (
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            fontSize: ".68rem",
            marginBottom: 3,
          }}
        >
          <span style={{ color: "var(--t-text-muted)" }}>{label}</span>
          <span style={{ color, fontWeight: 700 }}>
            {data[data.length - 1].toFixed(1)}%
          </span>
        </div>
      )}
      <svg
        width="100%"
        height={height}
        viewBox={`0 0 100 ${height}`}
        preserveAspectRatio="none"
        style={{ overflow: "visible" }}
      >
        <polyline
          points={points}
          fill="none"
          stroke={color}
          strokeWidth="1.5"
          strokeLinejoin="round"
          strokeLinecap="round"
          vectorEffect="non-scaling-stroke"
        />
      </svg>
    </div>
  );
}

function Barra({ label, value, max, color, unit = "" }) {
  const pct = max > 0 ? Math.min((value / max) * 100, 100) : 0;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          fontSize: ".7rem",
        }}
      >
        <span style={{ color: "var(--t-text-muted)" }}>{label}</span>
        <span style={{ color, fontWeight: 700 }}>
          {value}
          {unit}
        </span>
      </div>
      <div
        style={{
          height: 6,
          background: "var(--t-border)",
          borderRadius: 3,
          overflow: "hidden",
        }}
      >
        <div
          style={{
            width: `${pct}%`,
            height: "100%",
            background: color,
            borderRadius: 3,
            transition: "width .4s ease",
          }}
        />
      </div>
    </div>
  );
}

function StatCard({ icon, label, value, pct, sub, color }) {
  return (
    <div
      style={{
        padding: "12px 14px",
        borderRadius: 10,
        border: `1px solid ${color}30`,
        background: `${color}08`,
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          marginBottom: 8,
        }}
      >
        <div
          style={{
            width: 32,
            height: 32,
            borderRadius: 7,
            background: `${color}18`,
            border: `1px solid ${color}30`,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          {icon}
        </div>
        <div>
          <div
            style={{
              fontSize: ".65rem",
              color: "var(--t-text-muted)",
              textTransform: "uppercase",
              letterSpacing: ".05em",
            }}
          >
            {label}
          </div>
          <div
            style={{
              fontSize: "1.3rem",
              fontWeight: 800,
              color,
              lineHeight: 1,
            }}
          >
            {value}
          </div>
        </div>
      </div>
      {pct !== undefined && (
        <div
          style={{
            height: 3,
            background: "var(--t-border)",
            borderRadius: 2,
            overflow: "hidden",
          }}
        >
          <div
            style={{
              width: `${pct}%`,
              height: "100%",
              background: color,
              transition: "width .4s",
            }}
          />
        </div>
      )}
      {sub && (
        <div
          style={{
            fontSize: ".62rem",
            color: "var(--t-text-muted)",
            marginTop: 4,
          }}
        >
          {sub}
        </div>
      )}
    </div>
  );
}

function SectionTitle({ icon, children }) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 6,
        marginBottom: ".6rem",
        fontSize: ".7rem",
        fontWeight: 700,
        textTransform: "uppercase",
        letterSpacing: ".06em",
        color: "var(--t-text-muted)",
      }}
    >
      {icon} {children}
    </div>
  );
}

export default function MetricsPanel() {
  const [cpuHist, setCpuHist] = useState([]);
  const [ramHist, setRamHist] = useState([]);
  const [hw, setHw] = useState(null);
  const [latencias, setLatencias] = useState({});
  const [pipeline, setPipeline] = useState({ ok: 0, abortados: 0, errores: 0 });

  useEffect(() => {
    const unsubHw = AgentService.onHardwareMetrics((m) => {
      setHw(m);
      setCpuHist((h) => [...h, m.cpu_pct].slice(-40));
      setRamHist((h) => [...h, m.ram_pct].slice(-40));
    });
    const unsubWs = AgentService.onWsMessage((msg) => {
      if (msg.tipo === "telemetria" && msg.filtro && msg.duracion_s != null) {
        setLatencias((prev) => {
          const arr = [...(prev[msg.filtro] ?? []), msg.duracion_s * 1000];
          return { ...prev, [msg.filtro]: arr.slice(-50) };
        });
        setPipeline((p) =>
          msg.status !== "ok"
            ? { ...p, errores: p.errores + 1 }
            : { ...p, ok: p.ok + 1 },
        );
      }
      if (msg.tipo === "pipeline_abortado") {
        setPipeline((p) => ({ ...p, abortados: p.abortados + 1 }));
      }
    });
    return () => {
      unsubHw();
      unsubWs();
    };
  }, []);

  const total = pipeline.ok + pipeline.abortados + pipeline.errores;
  const promedio = (arr) =>
    arr.length ? Math.round(arr.reduce((a, b) => a + b, 0) / arr.length) : 0;
  const maxLatencia = Math.max(...Object.values(latencias).map(promedio), 1);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "1.2rem" }}>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fill,minmax(148px,1fr))",
          gap: ".7rem",
        }}
      >
        <StatCard
          icon={<Cpu size={15} color="#00d4ff" />}
          label="CPU"
          color="#00d4ff"
          value={hw ? `${hw.cpu_pct.toFixed(1)}%` : "—"}
          pct={hw?.cpu_pct}
          sub="en tiempo real"
        />
        <StatCard
          icon={<Activity size={15} color="#7c3aed" />}
          label="RAM"
          color="#7c3aed"
          value={hw ? `${hw.ram_pct.toFixed(1)}%` : "—"}
          pct={hw?.ram_pct}
          sub={
            hw
              ? `${(hw.ram_used_mb / 1024).toFixed(1)} / ${(hw.ram_total_mb / 1024).toFixed(1)} GB`
              : ""
          }
        />
        <StatCard
          icon={<CheckCircle2 size={15} color="#00ff9d" />}
          label="OK"
          color="#00ff9d"
          value={pipeline.ok}
          pct={total > 0 ? (pipeline.ok / total) * 100 : 0}
          sub="filtros exitosos"
        />
        <StatCard
          icon={<XCircle size={15} color="#ff2d55" />}
          label="Fallos"
          color="#ff2d55"
          value={pipeline.abortados + pipeline.errores}
          pct={
            total > 0
              ? ((pipeline.abortados + pipeline.errores) / total) * 100
              : 0
          }
          sub="del pipeline"
        />
      </div>

      <div
        style={{
          padding: "1rem 1.2rem",
          borderRadius: 12,
          border: "1px solid var(--t-border)",
          background: "var(--t-bg-card)",
        }}
      >
        <SectionTitle icon={<Activity size={13} />}>
          CPU &amp; RAM en tiempo real
        </SectionTitle>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "1fr 1fr",
            gap: "1rem",
          }}
        >
          <Sparkline data={cpuHist} color="#00d4ff" label="CPU" />
          <Sparkline data={ramHist} color="#7c3aed" label="RAM" />
        </div>
      </div>

      <div
        style={{
          padding: "1rem 1.2rem",
          borderRadius: 12,
          border: "1px solid var(--t-border)",
          background: "var(--t-bg-card)",
        }}
      >
        <SectionTitle icon={<Zap size={13} />}>
          Latencia por guardrail (ms)
        </SectionTitle>
        {Object.keys(latencias).length === 0 ? (
          <div
            style={{
              padding: "1rem 0",
              textAlign: "center",
              color: "var(--t-text-muted)",
              fontSize: ".76rem",
            }}
          >
            Ejecuta un agente para ver las latencias.
          </div>
        ) : (
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              gap: ".5rem",
              marginTop: ".5rem",
            }}
          >
            {Object.entries(latencias).map(([nombre, arr]) => (
              <Barra
                key={nombre}
                label={nombre.replace(" Guard", "").replace(" Filter", "")}
                value={promedio(arr)}
                max={maxLatencia}
                color={GUARD_COLOR[nombre] ?? "#64748b"}
                unit="ms"
              />
            ))}
          </div>
        )}
      </div>

      <div
        style={{
          padding: "1rem 1.2rem",
          borderRadius: 12,
          border: "1px solid var(--t-border)",
          background: "var(--t-bg-card)",
        }}
      >
        <SectionTitle icon={<Cpu size={13} />}>
          Estado acumulado del pipeline
        </SectionTitle>
        {total === 0 ? (
          <div
            style={{
              padding: "1rem 0",
              textAlign: "center",
              color: "var(--t-text-muted)",
              fontSize: ".76rem",
            }}
          >
            Sin ejecuciones todavía. Ve a Pipeline → Ejecutar.
          </div>
        ) : (
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              gap: ".5rem",
              marginTop: ".5rem",
            }}
          >
            <Barra
              label={`OK (${pipeline.ok})`}
              value={pipeline.ok}
              max={total}
              color="#00ff9d"
            />
            <Barra
              label={`Abortados (${pipeline.abortados})`}
              value={pipeline.abortados}
              max={total}
              color="#f59e0b"
            />
            <Barra
              label={`Errores (${pipeline.errores})`}
              value={pipeline.errores}
              max={total}
              color="#ff2d55"
            />
          </div>
        )}
      </div>
    </div>
  );
}
