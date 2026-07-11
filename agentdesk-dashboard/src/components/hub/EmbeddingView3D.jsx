/**
 * EmbeddingView3D — Visualizador 3D interactivo de embeddings.
 *
 * Controles:
 *   Arrastra      → rotar vista
 *   Scroll/Pinch  → zoom
 *   Click         → seleccionar agente (panel de detalle)
 *   Doble clic    → resetear vista
 *   F             → pantalla completa
 */
import { useRef, useState, useEffect, useCallback } from "react";
import { RefreshCw, Maximize2, RotateCcw } from "../../icons.js";

const API_BASE = import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8000";

const AREA_COLORS = {
  Finanzas:"#00d4ff", Mecánica:"#00ff9d", RRHH:"#f59e0b",
  Logística:"#8b5cf6", Marketing:"#ef4444", Legal:"#f97316",
  Tecnología:"#06b6d4", Operaciones:"#84cc16", General:"#64748b",
};
const AREA_IDX = { Finanzas:0, Mecánica:1, RRHH:2, Logística:3, Marketing:4, Legal:5, Tecnología:6, Operaciones:7, General:8 };
const DEFAULT_RX = 0.25, DEFAULT_RY = 0.4;

function project3D(x, y, z, rx, ry, cx, cy, fov, scale) {
  const s = scale ?? 30;
  const cy1 = Math.cos(ry), sy1 = Math.sin(ry);
  const rx1  = x * cy1 - z * sy1;
  const rz1  = x * sy1 + z * cy1;
  const cx2 = Math.cos(rx), sx2 = Math.sin(rx);
  const ry2  = y * cx2 - rz1 * sx2;
  const rz2  = y * sx2 + rz1 * cx2;
  const d    = fov / (fov + rz2 + 10);
  return { px: cx + rx1 * d * s, py: cy + ry2 * d * s, d, z: rz2 };
}

function lcg(seed) {
  let s = seed % 2147483647;
  return () => { s = (s * 16807) % 2147483647; return (s-1)/2147483646; };
}

function computePuntos(agentes) {
  const pts = [];
  agentes.forEach((ag, idx) => {
    const area  = ag.area || "General";
    const aidx  = AREA_IDX[area] ?? 8;
    const color = AREA_COLORS[area] ?? "#64748b";
    const rand  = lcg(idx * 7919 + 31337);
    const angle = (aidx / Object.keys(AREA_IDX).length) * 2 * Math.PI;
    const r = 3.5 + aidx * 0.5;
    const cx = r * Math.cos(angle), cy2 = (aidx-4)*1.4, cz = r * Math.sin(angle);
    pts.push({ id:ag.id, nombre:ag.nombre, area, color, size:0.9, tipo:"agente",
               x:cx, y:cy2, z:cz,
               modelo:(ag.modelo||"").replace("models/",""),
               temperatura:ag.temperatura??0.4,
               info:`${(ag.modelo||"").replace("models/","")} · T=${ag.temperatura??0.4}` });
    const n = 12 + aidx * 2;
    for (let i = 0; i < n; i++) {
      const sp = 1.8;
      pts.push({ id:`${ag.id}_${i}`, parentId:ag.id, nombre:ag.nombre, area, color,
                 size:(0.3+rand()*0.5)*0.45, tipo:"satélite",
                 x:cx+(rand()-.5)*sp*2, y:cy2+(rand()-.5)*sp, z:cz+(rand()-.5)*sp*2 });
    }
  });
  const tieneAgente = new Set(agentes.map(a=>a.area||"General"));
  Object.entries(AREA_COLORS).forEach(([area,color],idx) => {
    if (tieneAgente.has(area)) return;
    const rand = lcg(idx*2311+9973);
    const aidx = AREA_IDX[area]??8;
    const angle = (aidx/Object.keys(AREA_IDX).length)*2*Math.PI;
    const r = 3.5+aidx*0.5;
    const cx = r*Math.cos(angle), cy2=(aidx-4)*1.4, cz=r*Math.sin(angle);
    for (let i=0;i<6;i++) pts.push({
      id:`demo_${area}_${i}`, nombre:`${area} (demo)`, area, color,
      size:0.35, tipo:"satélite",
      x:cx+(rand()-.5)*2, y:cy2+(rand()-.5)*1.5, z:cz+(rand()-.5)*2,
    });
  });
  return pts;
}

const CUBE_EDGES = (() => {
  const v=[[-1,-1,-1],[1,-1,-1],[1,1,-1],[-1,1,-1],[-1,-1,1],[1,-1,1],[1,1,1],[-1,1,1]];
  const e=[[0,1],[1,2],[2,3],[3,0],[4,5],[5,6],[6,7],[7,4],[0,4],[1,5],[2,6],[3,7]];
  const s=6.5;
  return e.map(([a,b])=>({a:v[a].map(c=>c*s),b:v[b].map(c=>c*s)}));
})();

export default function EmbeddingView3D() {
  const containerRef = useRef(null);
  const canvasRef    = useRef(null);
  const wrapRef      = useRef(null);
  const stateRef     = useRef({
    rx:DEFAULT_RX, ry:DEFAULT_RY,
    drag:false, lx:0, ly:0,
    stop:false, zoom:1.0,
    dragDist:0,                   // detectar click vs drag
    touch:null,                   // para pinch zoom
    pinchDist0:0,
  });
  const puntosRef = useRef([]);
  const rafRef    = useRef(null);

  const [agentCount, setAgentCount] = useState(0);
  const [satCount,   setSatCount]   = useState(0);
  const [loading,    setLoading]    = useState(true);
  const [hoverName,  setHoverName]  = useState("");
  const [filter,     setFilter]     = useState("Todos");
  const [areas,      setAreas]      = useState([]);
  const [selected,   setSelected]   = useState(null);   // agente seleccionado
  const [autoRot,    setAutoRot]    = useState(true);
  const [isFullscreen, setIsFullscreen] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    const tryEmb = fetch(`${API_BASE}/embeddings`)
      .then(r=>{ if(!r.ok) throw 0; return r.json(); })
      .then(d=>d.puntos??[]);
    const tryAg = fetch(`${API_BASE}/agentes`)
      .then(r=>r.json())
      .then(d=>computePuntos(d.agentes??[]));
    tryEmb.catch(()=>tryAg)
      .then(pts=>{
        puntosRef.current = pts;
        setAgentCount(pts.filter(p=>p.tipo==="agente").length);
        setSatCount(pts.filter(p=>p.tipo!=="agente").length);
        setAreas(["Todos",...new Set(pts.filter(p=>p.tipo==="agente").map(p=>p.area))]);
        setLoading(false);
      })
      .catch(()=>setLoading(false));
  }, []);

  useEffect(()=>{ load(); }, [load]);

  // Sincronizar autoRot con stateRef
  useEffect(()=>{ stateRef.current.stop = !autoRot; }, [autoRot]);

  // Fullscreen API
  function toggleFullscreen() {
    const el = wrapRef.current;
    if (!isFullscreen) {
      if (el.requestFullscreen) el.requestFullscreen();
      else if (el.webkitRequestFullscreen) el.webkitRequestFullscreen();
    } else {
      if (document.exitFullscreen) document.exitFullscreen();
      else if (document.webkitExitFullscreen) document.webkitExitFullscreen();
    }
  }
  useEffect(()=>{
    const h = ()=>setIsFullscreen(!!document.fullscreenElement);
    document.addEventListener("fullscreenchange", h);
    document.addEventListener("webkitfullscreenchange", h);
    return ()=>{ document.removeEventListener("fullscreenchange",h); document.removeEventListener("webkitfullscreenchange",h); };
  },[]);

  // ── Loop de render ────────────────────────────────────────────────────────────
  useEffect(()=>{
    const canvas = canvasRef.current;
    const cont   = containerRef.current;
    if (!canvas || !cont || loading) return;

    const resize = ()=>{
      const r = cont.getBoundingClientRect();
      canvas.width  = Math.floor(r.width)  || 800;
      canvas.height = Math.floor(r.height) || 500;
    };
    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(cont);

    const ctx = canvas.getContext("2d");
    const st  = stateRef.current;
    let hovId = null, selId = null;

    function frame() {
      const W=canvas.width, H=canvas.height;
      if (!W||!H) { rafRef.current=requestAnimationFrame(frame); return; }
      const cx=W/2, cy=H/2;
      const fov   = 300;
      const scale = Math.min(W,H) * 0.055 * st.zoom;

      // Fondo degradado radial
      const bg=ctx.createRadialGradient(cx,cy,0,cx,cy,Math.max(W,H)*0.75);
      bg.addColorStop(0,"#070f28"); bg.addColorStop(1,"#020610");
      ctx.fillStyle=bg; ctx.fillRect(0,0,W,H);

      // Auto-rotación
      if (!st.drag && !st.stop) st.ry += 0.006;

      // Wireframe cubo
      ctx.strokeStyle="rgba(22,36,84,.7)"; ctx.lineWidth=0.8;
      CUBE_EDGES.forEach(({a,b})=>{
        const pa=project3D(a[0],a[1],a[2],st.rx,st.ry,cx,cy,fov,scale);
        const pb=project3D(b[0],b[1],b[2],st.rx,st.ry,cx,cy,fov,scale);
        ctx.beginPath(); ctx.moveTo(pa.px,pa.py); ctx.lineTo(pb.px,pb.py); ctx.stroke();
      });

      // Ejes
      [["#ff2d55",[7,0,0],"X"],["#00ff9d",[0,7,0],"Y"],["#00d4ff",[0,0,7],"Z"]].forEach(([col,pt,lbl])=>{
        const o=project3D(0,0,0,st.rx,st.ry,cx,cy,fov);
        const e=project3D(pt[0],pt[1],pt[2],st.rx,st.ry,cx,cy,fov,scale);
        ctx.strokeStyle=col; ctx.lineWidth=1.5;
        ctx.beginPath(); ctx.moveTo(o.px,o.py); ctx.lineTo(e.px,e.py); ctx.stroke();
        ctx.fillStyle=col; ctx.font="bold 10px monospace"; ctx.textAlign="center";
        ctx.fillText(lbl,e.px,e.py-5);
      });

      const visible = filter==="Todos"
        ? puntosRef.current
        : puntosRef.current.filter(p=>p.area===filter);

      const projected = visible.map(p=>({
        ...p, ...project3D(p.x,p.y,p.z,st.rx,st.ry,cx,cy,fov,scale)
      })).sort((a,b)=>b.z-a.z);

      // Líneas de conexión: satélites → agente seleccionado/hover
      const activeId = selId || hovId;
      if (activeId) {
        const parent = projected.find(p=>p.id===activeId && p.tipo==="agente");
        if (parent) {
          projected.filter(p=>p.parentId===activeId).forEach(sat=>{
            ctx.strokeStyle = parent.color+"40";
            ctx.lineWidth = 0.5;
            ctx.beginPath(); ctx.moveTo(parent.px,parent.py); ctx.lineTo(sat.px,sat.py); ctx.stroke();
          });
        }
      }

      // Puntos
      for (const p of projected) {
        const isHov = p.id===hovId;
        const isSel = p.id===selId;
        const r = p.size*(scale*0.22)*p.d*(isHov||isSel ? 2.4 : 1);

        // Glow
        if (p.tipo==="agente"||isHov||isSel) {
          const g=ctx.createRadialGradient(p.px,p.py,0,p.px,p.py,r*4);
          g.addColorStop(0,p.color+(isSel?"88":"44"));
          g.addColorStop(1,"transparent");
          ctx.fillStyle=g;
          ctx.beginPath(); ctx.arc(p.px,p.py,r*4,0,Math.PI*2); ctx.fill();
        }

        // Punto
        ctx.beginPath(); ctx.arc(p.px,p.py,Math.max(r,1.2),0,Math.PI*2);
        const alpha = p.tipo==="agente" ? 1 : 0.6+p.size*0.4;
        ctx.fillStyle=p.color+Math.round(alpha*255).toString(16).padStart(2,"0");
        ctx.fill();

        if (isHov||isSel) {
          ctx.strokeStyle = isSel ? "#fff" : p.color;
          ctx.lineWidth = isSel ? 2.5 : 1.5;
          ctx.stroke();
          // Pulso para seleccionado
          if (isSel) {
            ctx.strokeStyle=p.color+"60"; ctx.lineWidth=1;
            ctx.beginPath(); ctx.arc(p.px,p.py,r*2+Math.sin(Date.now()/300)*3,0,Math.PI*2); ctx.stroke();
          }
        }

        // Label agentes
        if (p.tipo==="agente" && r>2) {
          ctx.shadowColor=p.color; ctx.shadowBlur=6;
          ctx.fillStyle="#e2e8f0"; ctx.font=`bold ${Math.max(10,r*1.8)}px monospace`;
          ctx.textAlign="center";
          ctx.fillText(p.nombre,p.px,p.py-r-5);
          ctx.shadowBlur=0;
        }
      }

      // Tooltip hover (solo si no hay selección)
      if (!selId) {
        const hp=projected.find(p=>p.id===hovId&&p.tipo==="agente");
        if (hp) {
          const lines=[hp.nombre,hp.area,hp.info].filter(Boolean);
          const tw=180,lh=17,pad=10;
          const tx=Math.min(hp.px+14,W-tw-8);
          const ty=Math.max(hp.py-lines.length*lh/2,8);
          ctx.fillStyle="rgba(6,13,36,.95)";
          ctx.strokeStyle=hp.color; ctx.lineWidth=1.2;
          ctx.beginPath(); ctx.roundRect(tx,ty,tw,lines.length*lh+pad,6);
          ctx.fill(); ctx.stroke();
          lines.forEach((l,i)=>{
            ctx.fillStyle=i===0?hp.color:"#94a3b8";
            ctx.font=`${i===0?"bold 12":"11"}px monospace`; ctx.textAlign="left";
            ctx.fillText(l,tx+7,ty+pad/2+(i+1)*lh-3);
          });
          setHoverName(hp.nombre);
        } else { setHoverName(""); }
      }

      // HUD — ángulos
      ctx.fillStyle="rgba(255,255,255,.12)"; ctx.font="9px monospace"; ctx.textAlign="left";
      ctx.fillText(`Rx:${(st.rx*57.3).toFixed(0)}°  Ry:${(st.ry*57.3).toFixed(0)}°  Zoom:${st.zoom.toFixed(2)}x`,10,H-10);

      // Ayuda
      ctx.textAlign="right"; ctx.fillStyle="rgba(255,255,255,.08)"; ctx.font="9px sans-serif";
      ctx.fillText("Arrastra · Scroll zoom · Click agente · Doble clic = reset", W-10, H-10);

      rafRef.current=requestAnimationFrame(frame);
    }

    // ── Eventos Mouse ────────────────────────────────────────────────────────────
    function getPos(e) {
      const rect=canvas.getBoundingClientRect();
      return [(e.clientX-rect.left)*canvas.width/rect.width,
              (e.clientY-rect.top)*canvas.height/rect.height];
    }

    function nearestAgent(mx,my) {
      const W2=canvas.width,H2=canvas.height;
      const vis=filter==="Todos"?puntosRef.current:puntosRef.current.filter(p=>p.area===filter);
      let best=null,bestD=22;
      vis.forEach(p=>{
        if(p.tipo!=="agente") return;
        const pr=project3D(p.x,p.y,p.z,st.rx,st.ry,W2/2,H2/2,300,Math.min(W2,H2)*0.055*st.zoom);
        const d=Math.hypot(mx-pr.px,my-pr.py);
        if(d<bestD){bestD=d;best=p;}
      });
      return best;
    }

    function onMove(e) {
      const [mx,my]=getPos(e);
      if (st.drag) {
        const dx=e.clientX-st.lx, dy=e.clientY-st.ly;
        st.ry+=dx*0.007; st.rx+=dy*0.007;
        st.lx=e.clientX; st.ly=e.clientY;
        st.dragDist+=Math.hypot(dx,dy);
        return;
      }
      const ag=nearestAgent(mx,my);
      hovId = ag?.id ?? null;
      canvas.style.cursor = ag ? "pointer" : "grab";
    }

    function onDown(e) {
      st.drag=true; st.stop=true; st.lx=e.clientX; st.ly=e.clientY; st.dragDist=0;
      canvas.style.cursor="grabbing";
    }

    function onUp(e) {
      st.drag=false;
      canvas.style.cursor="grab";
      // Click (no drag) → seleccionar
      if (st.dragDist < 5) {
        const [mx,my]=getPos(e);
        const ag=nearestAgent(mx,my);
        if (ag) {
          selId=ag.id;
          setSelected(ag);
          setAutoRot(false);
        } else {
          selId=null;
          setSelected(null);
          setAutoRot(true);
        }
      }
    }

    function onDblClick() {
      st.rx=DEFAULT_RX; st.ry=DEFAULT_RY; st.zoom=1.0;
      selId=null; setSelected(null); setAutoRot(true);
    }

    function onWheel(e) {
      e.preventDefault();
      const delta = e.deltaY > 0 ? -0.12 : 0.12;
      st.zoom = Math.max(0.3, Math.min(5.0, st.zoom * (1 + delta)));
    }

    // ── Eventos Touch ────────────────────────────────────────────────────────────
    function getTouchDist(t) {
      return Math.hypot(t[0].clientX-t[1].clientX, t[0].clientY-t[1].clientY);
    }

    function onTouchStart(e) {
      e.preventDefault();
      if (e.touches.length===1) {
        st.drag=true; st.stop=true;
        st.lx=e.touches[0].clientX; st.ly=e.touches[0].clientY; st.dragDist=0;
      } else if (e.touches.length===2) {
        st.drag=false;
        st.pinchDist0=getTouchDist(e.touches);
      }
    }

    function onTouchMove(e) {
      e.preventDefault();
      if (e.touches.length===1 && st.drag) {
        const dx=e.touches[0].clientX-st.lx, dy=e.touches[0].clientY-st.ly;
        st.ry+=dx*0.007; st.rx+=dy*0.007;
        st.lx=e.touches[0].clientX; st.ly=e.touches[0].clientY;
        st.dragDist+=Math.hypot(dx,dy);
      } else if (e.touches.length===2) {
        const dist=getTouchDist(e.touches);
        if (st.pinchDist0>0) {
          const ratio=dist/st.pinchDist0;
          st.zoom=Math.max(0.3,Math.min(5.0,st.zoom*ratio));
          st.pinchDist0=dist;
        }
      }
    }

    function onTouchEnd(e) {
      e.preventDefault();
      if (e.touches.length===0) {
        if (st.drag && st.dragDist<10) {
          // Tap → seleccionar
          const rect=canvas.getBoundingClientRect();
          const tx=(e.changedTouches[0].clientX-rect.left)*canvas.width/rect.width;
          const ty=(e.changedTouches[0].clientY-rect.top)*canvas.height/rect.height;
          const ag=nearestAgent(tx,ty);
          if(ag){selId=ag.id;setSelected(ag);setAutoRot(false);}
          else{selId=null;setSelected(null);setAutoRot(true);}
        }
        st.drag=false; canvas.style.cursor="grab";
        st.pinchDist0=0;
      }
    }

    canvas.addEventListener("mousemove",  onMove);
    canvas.addEventListener("mousedown",  onDown);
    canvas.addEventListener("mouseup",    onUp);
    canvas.addEventListener("mouseleave", onUp);
    canvas.addEventListener("dblclick",   onDblClick);
    canvas.addEventListener("wheel",      onWheel, {passive:false});
    canvas.addEventListener("touchstart", onTouchStart, {passive:false});
    canvas.addEventListener("touchmove",  onTouchMove,  {passive:false});
    canvas.addEventListener("touchend",   onTouchEnd,   {passive:false});

    rafRef.current=requestAnimationFrame(frame);
    return ()=>{
      cancelAnimationFrame(rafRef.current);
      ro.disconnect();
      canvas.removeEventListener("mousemove",  onMove);
      canvas.removeEventListener("mousedown",  onDown);
      canvas.removeEventListener("mouseup",    onUp);
      canvas.removeEventListener("mouseleave", onUp);
      canvas.removeEventListener("dblclick",   onDblClick);
      canvas.removeEventListener("wheel",      onWheel);
      canvas.removeEventListener("touchstart", onTouchStart);
      canvas.removeEventListener("touchmove",  onTouchMove);
      canvas.removeEventListener("touchend",   onTouchEnd);
    };
  }, [loading, filter]);

  function resetVista() {
    const st=stateRef.current;
    st.rx=DEFAULT_RX; st.ry=DEFAULT_RY; st.zoom=1.0;
    setSelected(null); setAutoRot(true);
  }

  return (
    <div ref={wrapRef} style={{ display:"flex", flexDirection:"column", gap:".8rem",
      height: isFullscreen ? "100vh" : "calc(100vh - 175px)", minHeight:480,
      background: isFullscreen ? "#020610" : "transparent",
      padding: isFullscreen ? "1rem" : 0,
    }}>

      {/* Header */}
      <div style={{ display:"flex", alignItems:"center", justifyContent:"space-between", flexWrap:"wrap", gap:".4rem" }}>
        <div>
          <span style={{ fontWeight:700, fontSize:".9rem", color:"var(--t-text)" }}>
            Visualizador 3D de Embeddings
          </span>
          {"  "}
          <span style={{ fontSize:".72rem", color:"var(--t-text-muted)" }}>
            {agentCount} agentes · {satCount} satélites
            {hoverName && !selected && <span style={{ color:"var(--t-accent)", marginLeft:8 }}>● {hoverName}</span>}
          </span>
        </div>

        {/* Controles */}
        <div style={{ display:"flex", gap:".35rem", flexWrap:"wrap", alignItems:"center" }}>
          {/* Filtros de área */}
          {areas.map(a=>{
            const c=a==="Todos"?"#64748b":(AREA_COLORS[a]??"#64748b");
            return (
              <button key={a} onClick={()=>{setFilter(a);setSelected(null);}} style={{
                padding:"3px 10px", borderRadius:20, fontSize:".7rem", fontWeight:600,
                cursor:"pointer", fontFamily:"inherit",
                border: filter===a?`1px solid ${c}`:"1px solid var(--t-border)",
                background: filter===a?`${c}22`:"transparent",
                color: filter===a?c:"var(--t-text-muted)",
              }}>{a}</button>
            );
          })}

          {/* Botón pausa */}
          <button onClick={()=>setAutoRot(v=>!v)} style={{
            padding:"3px 10px", borderRadius:20, fontSize:".7rem", fontWeight:600,
            cursor:"pointer", fontFamily:"inherit",
            border:`1px solid ${autoRot?"var(--t-accent)":"var(--t-border)"}`,
            background: autoRot?"rgba(0,212,255,.1)":"transparent",
            color: autoRot?"var(--t-accent)":"var(--t-text-muted)",
          }}>{autoRot?"⏸ Auto":"▶ Rotar"}</button>

          {/* Reset */}
          <button onClick={resetVista} title="Reset vista (doble clic en canvas)" style={{
            padding:"3px 9px", borderRadius:20, fontSize:".75rem", cursor:"pointer",
            border:"1px solid var(--t-border)", background:"transparent",
            color:"var(--t-text-muted)", fontFamily:"inherit", display:"flex", alignItems:"center", gap:4,
          }}><RotateCcw size={12} /> Reset</button>

          {/* Fullscreen */}
          <button onClick={toggleFullscreen} title="Pantalla completa" style={{
            padding:"3px 9px", borderRadius:20, fontSize:".75rem", cursor:"pointer",
            border:`1px solid ${isFullscreen?"var(--t-accent)":"var(--t-border)"}`,
            background:isFullscreen?"rgba(0,212,255,.1)":"transparent",
            color:isFullscreen?"var(--t-accent)":"var(--t-text-muted)",
            fontFamily:"inherit", display:"flex", alignItems:"center", gap:4,
          }}><Maximize2 size={12} /> {isFullscreen?"Salir":"Ampliar"}</button>

          {/* Reload */}
          <button onClick={load} title="Recargar datos" style={{
            padding:"3px 9px", borderRadius:20, fontSize:".75rem", cursor:"pointer",
            border:"1px solid var(--t-border)", background:"transparent",
            color:"var(--t-text-muted)", fontFamily:"inherit",
          }}><RefreshCw size={12} /></button>
        </div>
      </div>

      {/* Canvas + Panel lateral */}
      <div style={{ flex:1, display:"flex", gap:".8rem", minHeight:0 }}>

        {/* Canvas */}
        <div ref={containerRef} style={{
          flex:1, borderRadius:12, overflow:"hidden",
          border:"1px solid var(--t-border)", background:"#020610", position:"relative",
          minHeight:0,
        }}>
          {loading ? (
            <div style={{ height:"100%", display:"flex", alignItems:"center",
                          justifyContent:"center", color:"var(--t-text-muted)", fontSize:".84rem" }}>
              <RefreshCw size={18} style={{ animation:"spin .8s linear infinite", marginRight:8 }} />
              Cargando embeddings...
              <style>{`@keyframes spin{to{transform:rotate(360deg)}}`}</style>
            </div>
          ) : (
            <canvas ref={canvasRef}
              style={{ width:"100%", height:"100%", display:"block", cursor:"grab", touchAction:"none" }} />
          )}
        </div>

        {/* Panel de detalle (aparece al hacer click) */}
        {selected && (
          <div style={{
            width:220, flexShrink:0, display:"flex", flexDirection:"column", gap:".7rem",
            padding:"1rem", borderRadius:12,
            border:`1px solid ${AREA_COLORS[selected.area]??"#64748b"}50`,
            background:`${AREA_COLORS[selected.area]??"#64748b"}0c`,
          }}>
            {/* Header del agente */}
            <div style={{ display:"flex", alignItems:"center", justifyContent:"space-between" }}>
              <div style={{
                width:36, height:36, borderRadius:"50%", flexShrink:0,
                background:`${AREA_COLORS[selected.area]??"#64748b"}25`,
                border:`2px solid ${AREA_COLORS[selected.area]??"#64748b"}`,
                display:"flex", alignItems:"center", justifyContent:"center",
                fontSize:18,
              }}>🤖</div>
              <button onClick={()=>{setSelected(null);setAutoRot(true);}} style={{
                background:"none", border:"none", color:"#64748b",
                cursor:"pointer", fontSize:18, lineHeight:1,
              }}>×</button>
            </div>

            <div>
              <div style={{ fontWeight:800, fontSize:".92rem", color:"var(--t-text)", marginBottom:3 }}>
                {selected.nombre}
              </div>
              <div style={{
                display:"inline-block", padding:"2px 9px", borderRadius:20,
                background:`${AREA_COLORS[selected.area]??"#64748b"}20`,
                color:AREA_COLORS[selected.area]??"#64748b",
                fontSize:".7rem", fontWeight:600,
              }}>{selected.area}</div>
            </div>

            <div style={{ display:"flex", flexDirection:"column", gap:".4rem" }}>
              {[
                ["Modelo",      (selected.modelo||"gemini-2.5-flash").split("/").pop()],
                ["Temperatura", String(selected.temperatura??0.4)],
                ["ID",          selected.id],
                ["Satélites",   String(puntosRef.current.filter(p=>p.parentId===selected.id).length)],
              ].map(([k,v])=>(
                <div key={k} style={{
                  display:"flex", justifyContent:"space-between", alignItems:"center",
                  padding:"5px 8px", borderRadius:7,
                  background:"rgba(255,255,255,.04)", fontSize:".73rem",
                }}>
                  <span style={{ color:"#64748b" }}>{k}</span>
                  <span style={{ color:"var(--t-text)", fontWeight:600, fontFamily:"monospace",
                    maxWidth:110, overflow:"hidden", textOverflow:"ellipsis", whiteSpace:"nowrap",
                  }}>{v}</span>
                </div>
              ))}
            </div>

            {/* Área de color */}
            <div style={{
              height:4, borderRadius:4,
              background:`linear-gradient(90deg,${AREA_COLORS[selected.area]??"#64748b"},transparent)`,
              marginTop:2,
            }}/>

            <div style={{ fontSize:".67rem", color:"#475569", textAlign:"center", lineHeight:1.5 }}>
              Haz clic en el canvas para deseleccionar
            </div>
          </div>
        )}
      </div>

      {/* Leyenda + controles ayuda */}
      <div style={{ display:"flex", gap:".8rem", flexWrap:"wrap", fontSize:".68rem", alignItems:"center" }}>
        {Object.entries(AREA_COLORS).map(([a,c])=>(
          <button key={a} onClick={()=>setFilter(f=>f===a?"Todos":a)}
            style={{
              display:"flex", alignItems:"center", gap:4, background:"none",
              border:"none", cursor:"pointer", fontFamily:"inherit",
              opacity: filter==="Todos"||filter===a ? 1 : 0.4,
              transition:"opacity .15s",
            }}>
            <div style={{ width:8,height:8,borderRadius:"50%",background:c,flexShrink:0 }}/>
            <span style={{ color:"var(--t-text-muted)" }}>{a}</span>
          </button>
        ))}
        <span style={{ marginLeft:"auto", color:"#334155", fontSize:".65rem" }}>
          🖱 Arrastra·rotar  |  Scroll·zoom  |  Click·seleccionar  |  Doble clic·reset  |  Toca leyenda·filtrar
        </span>
      </div>
    </div>
  );
}
