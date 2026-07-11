import { useEffect, useState } from "react";
import { AUTH_CONFIG }  from "../../config/auth.config";
import { useAuth }      from "../../context/AuthContext";
import Login            from "./Login";
import AccessDenied     from "./AccessDenied";

// Tauri event listener loaded dynamically inside useEffect — no top-level await
// so Vite can bundle this file without ES2022 top-level-await support.

const BACKEND_URL = "http://localhost:8000/health";
const POLL_INTERVAL_MS = 1500;
const POLL_TIMEOUT_MS  = 30_000;   // give backend 30 s before showing error

function useSplash() {
  // "connecting" | "ready" | "error" | "skip"
  const [phase, setPhase] = useState("connecting");
  const [detail, setDetail] = useState("Starting backend...");

  useEffect(() => {
    let cancelled = false;
    let unlistenReady  = null;
    let unlistenError  = null;
    let pollTimer      = null;
    let deadlineTimer  = null;

    async function probe() {
      try {
        const res = await fetch(BACKEND_URL, { signal: AbortSignal.timeout(2000) });
        if (res.ok && !cancelled) {
          clearTimeout(deadlineTimer);
          clearInterval(pollTimer);
          setDetail("Backend ready");
          setPhase("ready");
        }
      } catch {
        // still connecting — update hint
        if (!cancelled) setDetail("Waiting for Python backend on :8000...");
      }
    }

    async function start() {
      // 1. Subscribe to Tauri events — import() inside useEffect, no top-level await
      try {
        const { listen } = await import("@tauri-apps/api/event");
        unlistenReady = await listen("backend_ready", () => {
          if (cancelled) return;
          clearTimeout(deadlineTimer);
          clearInterval(pollTimer);
          setDetail("Backend ready");
          setPhase("ready");
        });
        unlistenError = await listen("backend_error", (ev) => {
          if (cancelled) return;
          clearTimeout(deadlineTimer);
          clearInterval(pollTimer);
          setDetail(ev.payload?.error ?? "Backend failed to start.");
          setPhase("error");
        });
      } catch {
        // Not inside Tauri (browser preview) — polling only
      }

      // 2. Probe immediately and keep polling
      probe();
      pollTimer = setInterval(probe, POLL_INTERVAL_MS);

      // 3. Hard deadline — if backend never replies, show error
      deadlineTimer = setTimeout(() => {
        if (cancelled) return;
        clearInterval(pollTimer);
        setDetail(
          "Backend did not respond in 30 s. " +
          "Check that AgentDesk.exe is installed correctly."
        );
        setPhase("error");
      }, POLL_TIMEOUT_MS);
    }

    start();

    return () => {
      cancelled = true;
      clearInterval(pollTimer);
      clearTimeout(deadlineTimer);
      if (unlistenReady) unlistenReady();
      if (unlistenError) unlistenError();
    };
  }, []);

  return { phase, detail };
}

// Splash screen shown while the backend is starting
function Splash({ phase, detail }) {
  const isError = phase === "error";

  return (
    <div style={{
      minHeight: "100vh",
      background: "#ffffff",
      display: "flex",
      flexDirection: "column",
      alignItems: "center",
      justifyContent: "center",
      gap: "1.5rem",
      fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
      color: "#1e293b",
      userSelect: "none",
    }}>
      {/* Logo mark */}
      <div style={{
        width: 64, height: 64,
        borderRadius: 16,
        background: "linear-gradient(135deg, #00d4ff 0%, #7c3aed 100%)",
        display: "flex", alignItems: "center", justifyContent: "center",
        fontSize: 28, fontWeight: 700, color: "#fff",
        boxShadow: "0 0 32px rgba(0,212,255,.35)",
      }}>A</div>

      {/* App name */}
      <div style={{ textAlign: "center" }}>
        <div style={{ fontSize: "1.5rem", fontWeight: 700, letterSpacing: ".05em", color: "#00d4ff" }}>
          AgentDesk
        </div>
        <div style={{ fontSize: ".75rem", color: "#475569", marginTop: 4 }}>
          Professional
        </div>
      </div>

      {/* Status indicator */}
      <div style={{
        display: "flex", flexDirection: "column", alignItems: "center", gap: ".5rem",
        minHeight: 56,
      }}>
        {!isError && (
          /* Spinner */
          <div style={{
            width: 28, height: 28,
            borderRadius: "50%",
            border: "3px solid #162454",
            borderTopColor: "#00d4ff",
            animation: "spin 0.8s linear infinite",
          }} />
        )}
        {isError && (
          /* Error icon */
          <div style={{
            width: 28, height: 28,
            borderRadius: "50%",
            background: "#ff2d55",
            display: "flex", alignItems: "center", justifyContent: "center",
            fontSize: 16, fontWeight: 700,
          }}>!</div>
        )}
        <div style={{
          fontSize: ".7rem",
          color: isError ? "#dc2626" : "#64748b",
          maxWidth: 320,
          textAlign: "center",
          lineHeight: 1.5,
        }}>
          {detail}
        </div>
        {isError && (
          <button
            onClick={() => window.location.reload()}
            style={{
              marginTop: 8,
              padding: "6px 20px",
              borderRadius: 8,
              border: "1px solid #ff2d55",
              background: "transparent",
              color: "#ff2d55",
              fontSize: ".7rem",
              cursor: "pointer",
              fontFamily: "inherit",
            }}
          >
            Retry
          </button>
        )}
      </div>

      {/* CSS keyframe injected inline */}
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );
}

export default function ProtectedRoute({ children }) {
  const { estaAutenticado, cargando, isKilled, killMsg } = useAuth();
  const { phase, detail } = useSplash();

  // Static kill switch (compile-time lock)
  if (AUTH_CONFIG.IS_LOCKED) {
    return <AccessDenied mensaje={AUTH_CONFIG.LOCK_MESSAGE} />;
  }

  // Remote kill switch activated
  if (isKilled) return <AccessDenied mensaje={killMsg} />;

  // Wait for auth context to resolve session from localStorage
  if (cargando) return <Splash phase="connecting" detail="Initializing..." />;

  // Wait for backend to be reachable
  if (phase === "connecting" || phase === "error") {
    return <Splash phase={phase} detail={detail} />;
  }

  // Backend is up — show login or the protected content
  if (!estaAutenticado) return <Login />;
  return children;
}
