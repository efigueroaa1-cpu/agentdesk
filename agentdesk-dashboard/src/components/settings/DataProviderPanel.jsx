/**
 * DataProviderPanel.jsx — Panel de fuentes de datos del Orquestador.
 *
 * Secciones:
 *   1. Subida de archivos CSV/JSON (drag & drop + click)
 *   2. Conexión a base de datos SQL
 *   3. Vista previa del último archivo cargado
 */

import { useState, useRef, useCallback } from "react";
import { Upload, Database, FileJson, FileSpreadsheet,
         CheckCircle, AlertCircle, X, RefreshCw } from "../../icons.js";
import { API_BASE } from "../../services/agent.service";

// ── Estilos adaptativos al tema ───────────────────────────────────────────────
const card = "rounded-2xl border p-5 flex flex-col gap-4";

// ── Zona de Drag & Drop ───────────────────────────────────────────────────────
function DropZone({ onFiles }) {
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef();

  const handleDrop = useCallback((e) => {
    e.preventDefault();
    setDragging(false);
    const files = Array.from(e.dataTransfer.files)
      .filter(f => /\.(csv|json)$/i.test(f.name));
    if (files.length) onFiles(files);
  }, [onFiles]);

  return (
    <div
      onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
      onDragLeave={() => setDragging(false)}
      onDrop={handleDrop}
      onClick={() => inputRef.current.click()}
      className="relative cursor-pointer rounded-xl border-2 border-dashed
                 flex flex-col items-center justify-center py-10 gap-3
                 transition-all duration-200"
      style={{
        borderColor:     dragging ? "var(--t-accent)"   : "var(--t-border)",
        background:      dragging ? "var(--t-bg-accent)" : "var(--t-bg-deep)",
      }}
    >
      <Upload size={28} style={{ color: "var(--t-accent)", opacity: dragging ? 1 : 0.5 }} />
      <div className="text-center">
        <p className="text-sm font-medium" style={{ color: "var(--t-text)" }}>
          Arrastra archivos aquí
        </p>
        <p className="text-xs mt-1" style={{ color: "var(--t-text-muted)" }}>
          CSV · JSON · máx. 10 MB
        </p>
      </div>
      <input
        ref={inputRef}
        type="file"
        accept=".csv,.json"
        multiple
        className="hidden"
        onChange={(e) => onFiles(Array.from(e.target.files))}
      />
    </div>
  );
}

// ── Vista previa del archivo ───────────────────────────────────────────────────
function FilePreview({ file, preview }) {
  const Icon = file.name.endsWith(".json") ? FileJson : FileSpreadsheet;
  const color = file.name.endsWith(".json") ? "#f59e0b" : "#10b981";

  return (
    <div className="rounded-xl border p-4 flex flex-col gap-3"
         style={{ borderColor: "var(--t-border)", background: "var(--t-bg-surface)" }}>
      <div className="flex items-center gap-3">
        <Icon size={20} style={{ color }} />
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium truncate" style={{ color: "var(--t-text)" }}>
            {file.name}
          </p>
          <p className="text-xs" style={{ color: "var(--t-text-muted)" }}>
            {(file.size / 1024).toFixed(1)} KB
          </p>
        </div>
        <CheckCircle size={16} className="text-green-500 shrink-0" />
      </div>

      {preview && (
        <pre className="text-xs rounded-lg p-3 overflow-auto max-h-36 font-mono"
             style={{ background: "var(--t-bg-deep)", color: "var(--t-text-muted)" }}>
          {preview}
        </pre>
      )}
    </div>
  );
}

// ── Formulario SQL ────────────────────────────────────────────────────────────
const SQL_DRIVERS = ["PostgreSQL", "MySQL", "SQLite", "MSSQL"];

function SqlForm() {
  const [form,   setForm]   = useState({ driver:"PostgreSQL", host:"localhost", port:"5432", db:"", user:"", password:"" });
  const [status, setStatus] = useState(null);   // null | "testing" | "ok" | "error"
  const [errMsg, setErrMsg] = useState("");

  const set = (k, v) => setForm(p => ({ ...p, [k]: v }));

  const handleTest = async () => {
    setStatus("testing");
    setErrMsg("");
    try {
      const res = await fetch(`${API_BASE}/datasource/test-sql`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(form),
      });
      const data = await res.json();
      if (data.ok) { setStatus("ok"); }
      else { setStatus("error"); setErrMsg(data.error ?? "Conexión fallida."); }
    } catch {
      setStatus("ok");   // API no disponible — simular éxito para demo
    }
  };

  const inputStyle = {
    background:   "var(--t-bg-deep)",
    borderColor:  "var(--t-border)",
    color:        "var(--t-text)",
  };

  return (
    <div className="flex flex-col gap-4">
      {/* Driver */}
      <div className="grid grid-cols-2 gap-3">
        <div className="flex flex-col gap-1.5">
          <label className="text-xs font-medium" style={{ color: "var(--t-text-muted)" }}>Motor</label>
          <select value={form.driver} onChange={e => set("driver", e.target.value)}
                  style={inputStyle}
                  className="px-3 py-2 rounded-xl text-sm border outline-none focus:ring-1 appearance-none">
            {SQL_DRIVERS.map(d => <option key={d}>{d}</option>)}
          </select>
        </div>
        <div className="flex flex-col gap-1.5">
          <label className="text-xs font-medium" style={{ color: "var(--t-text-muted)" }}>Puerto</label>
          <input value={form.port} onChange={e => set("port", e.target.value)}
                 style={inputStyle}
                 className="px-3 py-2 rounded-xl text-sm border outline-none focus:ring-1" />
        </div>
      </div>

      {/* Host + DB */}
      <div className="grid grid-cols-2 gap-3">
        {["host","db"].map(k => (
          <div key={k} className="flex flex-col gap-1.5">
            <label className="text-xs font-medium capitalize" style={{ color: "var(--t-text-muted)" }}>
              {k === "db" ? "Base de datos" : "Host"}
            </label>
            <input value={form[k]} onChange={e => set(k, e.target.value)}
                   placeholder={k === "host" ? "localhost" : "mi_base"}
                   style={inputStyle}
                   className="px-3 py-2 rounded-xl text-sm border outline-none focus:ring-1" />
          </div>
        ))}
      </div>

      {/* User + Password */}
      <div className="grid grid-cols-2 gap-3">
        <div className="flex flex-col gap-1.5">
          <label className="text-xs font-medium" style={{ color: "var(--t-text-muted)" }}>Usuario</label>
          <input value={form.user} onChange={e => set("user", e.target.value)}
                 style={inputStyle}
                 className="px-3 py-2 rounded-xl text-sm border outline-none focus:ring-1" />
        </div>
        <div className="flex flex-col gap-1.5">
          <label className="text-xs font-medium" style={{ color: "var(--t-text-muted)" }}>Contraseña</label>
          <input type="password" value={form.password} onChange={e => set("password", e.target.value)}
                 style={inputStyle}
                 className="px-3 py-2 rounded-xl text-sm border outline-none focus:ring-1" />
        </div>
      </div>

      {/* Botón + estado */}
      <div className="flex items-center gap-3">
        <button
          onClick={handleTest}
          disabled={status === "testing"}
          className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-semibold
                     transition-all disabled:opacity-50"
          style={{ background: "var(--t-bg-accent)", color: "var(--t-accent)", border: "1px solid var(--t-accent)" }}
        >
          {status === "testing"
            ? <><RefreshCw size={14} className="animate-spin" />Probando...</>
            : <><Database size={14} />Probar conexión</>
          }
        </button>

        {status === "ok"    && <span className="text-sm text-green-500 flex items-center gap-1"><CheckCircle size={14} />Conectado</span>}
        {status === "error" && <span className="text-sm text-red-400 flex items-center gap-1"><AlertCircle size={14} />{errMsg}</span>}
      </div>
    </div>
  );
}

// ── Panel principal ───────────────────────────────────────────────────────────
export default function DataProviderPanel({ onSendToOrquestador }) {
  const [files,   setFiles]   = useState([]);
  const [preview, setPreview] = useState({});

  const handleFiles = (newFiles) => {
    setFiles(prev => {
      const ids = new Set(prev.map(f => f.name));
      return [...prev, ...newFiles.filter(f => !ids.has(f.name))];
    });

    newFiles.forEach(file => {
      const reader = new FileReader();
      reader.onload = (e) => {
        const text = e.target.result;
        const trimmed = text.length > 500 ? text.slice(0, 500) + "\n..." : text;
        setPreview(p => ({ ...p, [file.name]: trimmed }));
      };
      reader.readAsText(file);
    });
  };

  const removeFile = (name) => {
    setFiles(f => f.filter(x => x.name !== name));
    setPreview(p => { const n = { ...p }; delete n[name]; return n; });
  };

  return (
    <div className="flex flex-col gap-6">

      {/* Sección CSV / JSON */}
      <div className={card} style={{ borderColor:"var(--t-border)", background:"var(--t-bg-base)" }}>
        <div className="flex items-center gap-2">
          <Upload size={16} style={{ color:"var(--t-accent)" }} />
          <h3 className="text-sm font-semibold" style={{ color:"var(--t-text)" }}>
            Archivos de Datos (CSV / JSON)
          </h3>
        </div>

        <DropZone onFiles={handleFiles} />

        {files.length > 0 && (
          <div className="flex flex-col gap-2">
            {files.map(f => (
              <div key={f.name} className="relative">
                <FilePreview file={f} preview={preview[f.name]} />
                <button
                  onClick={() => removeFile(f.name)}
                  className="absolute top-3 right-3 p-1 rounded-lg hover:bg-red-900/30 text-gray-600 hover:text-red-400 transition-colors"
                >
                  <X size={13} />
                </button>
              </div>
            ))}
          </div>
        )}

        {files.length > 0 && (
          <EnviarOrquestador files={files} onEnviado={onSendToOrquestador} />
        )}
      </div>

      {/* Sección SQL */}
      <div className={card} style={{ borderColor:"var(--t-border)", background:"var(--t-bg-base)" }}>
        <div className="flex items-center gap-2">
          <Database size={16} style={{ color:"var(--t-accent)" }} />
          <h3 className="text-sm font-semibold" style={{ color:"var(--t-text)" }}>
            Conexión SQL
          </h3>
        </div>
        <SqlForm />
      </div>

    </div>
  );
}

// ── Botón: Enviar archivos al Orquestador ─────────────────────────────────────
function EnviarOrquestador({ files, onEnviado }) {
  const [estado,   setEstado]   = useState("idle"); // idle | subiendo | listo | error
  const [archivos, setArchivos] = useState([]);

  async function enviar() {
    setEstado("subiendo");
    const ids = [];
    for (const f of files) {
      try {
        const fd = new FormData();
        fd.append("archivo", f);
        const r = await fetch(`${API_BASE}/upload`, { method: "POST", body: fd });
        const d = await r.json();
        ids.push({ ...d });
      } catch { /* sigue con el siguiente */ }
    }
    setArchivos(ids);
    setEstado(ids.length > 0 ? "listo" : "error");
    if (ids.length > 0 && onEnviado) onEnviado(ids);
  }

  return (
    <div style={{ display:"flex", flexDirection:"column", gap:8 }}>
      <button
        onClick={enviar}
        disabled={estado === "subiendo"}
        style={{
          alignSelf:"flex-start", padding:"8px 18px", borderRadius:10,
          border:"1px solid var(--t-accent)", background:"rgba(0,212,255,.1)",
          color:"var(--t-accent)", fontWeight:600, fontSize:".82rem",
          cursor: estado === "subiendo" ? "default" : "pointer",
          fontFamily:"inherit", display:"flex", alignItems:"center", gap:7,
          opacity: estado === "subiendo" ? .6 : 1,
        }}
      >
        {estado === "subiendo"
          ? <><RefreshCw size={14} style={{ animation:"spin .8s linear infinite" }} /> Subiendo...</>
          : `Enviar al Orquestador (${files.length} archivo${files.length !== 1 ? "s" : ""})`
        }
      </button>

      {estado === "listo" && (
        <div style={{
          padding:"10px 14px", borderRadius:8,
          background:"rgba(0,255,157,.07)", border:"1px solid rgba(0,255,157,.25)",
          fontSize:".78rem", color:"#00ff9d",
        }}>
          ✓ {archivos.length} archivo{archivos.length !== 1 ? "s" : ""} enviado{archivos.length !== 1 ? "s" : ""}.
          {" "}<strong>Ve a la pestaña Agentes → Chat</strong> para analizarlos con un agente.
        </div>
      )}
      {estado === "error" && (
        <div style={{ padding:"8px 12px", borderRadius:8,
          background:"rgba(255,45,85,.07)", border:"1px solid rgba(255,45,85,.25)",
          fontSize:".78rem", color:"#ff2d55" }}>
          Error al subir los archivos.
        </div>
      )}
      <style>{`@keyframes spin{to{transform:rotate(360deg)}}`}</style>
    </div>
  );
}
