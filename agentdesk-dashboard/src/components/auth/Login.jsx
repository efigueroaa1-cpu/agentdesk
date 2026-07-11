import { useState } from "react";
import { useAuth } from "../../context/AuthContext";
import { Eye, EyeOff, Lock, User, AlertCircle } from "../../icons.js";

export default function Login() {
  const { login } = useAuth();
  const [form, setForm] = useState({ username: "", password: "" });
  const [showPw, setShowPw] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleChange = (e) => { setForm(p => ({ ...p, [e.target.name]: e.target.value })); setError(""); };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!form.username.trim() || !form.password.trim()) { setError("Completa usuario y contrasena."); return; }
    setLoading(true);
    await new Promise(r => setTimeout(r, 600));
    if (!login(form.username.trim(), form.password.trim())) setError("Usuario o contrasena incorrectos.");
    setLoading(false);
  };

  return (
    /* Solid dark background — intentionally overrides body's --t-bg-deep so the
       card is always visible regardless of OS dark/light mode preference. */
    <div style={{ minHeight:"100vh", background:"#020818", display:"flex",
                  alignItems:"center", justifyContent:"center", padding:"1rem" }}>
      <div className="w-full max-w-sm">
        <div className="text-center mb-8">
          <div style={{
            width:56, height:56, borderRadius:14, margin:"0 auto 1rem",
            background:"linear-gradient(135deg,#00d4ff,#7c3aed)",
            display:"flex", alignItems:"center", justifyContent:"center",
            boxShadow:"0 0 28px rgba(0,212,255,.3)",
          }}><Lock size={24} color="#fff" /></div>
          <h1 style={{ color:"#e2e8f0", fontSize:"1.5rem", fontWeight:700, margin:0 }}>AgentDesk</h1>
          <p  style={{ color:"#64748b", fontSize:".85rem", marginTop:4 }}>Sign in to continue</p>
        </div>
        <form onSubmit={handleSubmit}
          style={{ background:"#0d1a3e", borderRadius:16, border:"1px solid #162454",
                   padding:"1.5rem", display:"flex", flexDirection:"column", gap:"1rem" }}>
          <div style={{ display:"flex", flexDirection:"column", gap:6 }}>
            <label style={{ color:"#94a3b8", fontSize:".8rem", fontWeight:500 }}>Username</label>
            <div style={{ position:"relative" }}>
              <User size={15} style={{ position:"absolute", left:10, top:"50%", transform:"translateY(-50%)", color:"#475569", pointerEvents:"none" }} />
              <input type="text" name="username" value={form.username} onChange={handleChange}
                placeholder="admin" autoComplete="username"
                style={{ width:"100%", boxSizing:"border-box", paddingLeft:32, paddingRight:12,
                         paddingTop:9, paddingBottom:9, borderRadius:10,
                         border:"1px solid #162454", background:"#060d24",
                         color:"#e2e8f0", fontSize:".85rem", outline:"none",
                         fontFamily:"inherit" }} />
            </div>
          </div>
          <div style={{ display:"flex", flexDirection:"column", gap:6 }}>
            <label style={{ color:"#94a3b8", fontSize:".8rem", fontWeight:500 }}>Password</label>
            <div style={{ position:"relative" }}>
              <Lock size={15} style={{ position:"absolute", left:10, top:"50%", transform:"translateY(-50%)", color:"#475569", pointerEvents:"none" }} />
              <input type={showPw ? "text" : "password"} name="password" value={form.password} onChange={handleChange}
                placeholder="••••••••" autoComplete="current-password"
                style={{ width:"100%", boxSizing:"border-box", paddingLeft:32, paddingRight:36,
                         paddingTop:9, paddingBottom:9, borderRadius:10,
                         border:"1px solid #162454", background:"#060d24",
                         color:"#e2e8f0", fontSize:".85rem", outline:"none",
                         fontFamily:"inherit" }} />
              <button type="button" onClick={() => setShowPw(v => !v)}
                style={{ position:"absolute", right:10, top:"50%", transform:"translateY(-50%)",
                         background:"none", border:"none", color:"#475569", cursor:"pointer", padding:0 }}>
                {showPw ? <EyeOff size={15} /> : <Eye size={15} />}
              </button>
            </div>
          </div>
          {error && (
            <div style={{ display:"flex", alignItems:"center", gap:6,
                          background:"rgba(255,45,85,.12)", borderRadius:8,
                          padding:"8px 12px", color:"#ff2d55" }}>
              <AlertCircle size={14} />
              <span style={{ fontSize:".75rem" }}>{error}</span>
            </div>
          )}
          <button type="submit" disabled={loading}
            style={{ width:"100%", padding:"10px 0", borderRadius:10, border:"none",
                     background: loading ? "#1e3a5f" : "linear-gradient(90deg,#00d4ff,#7c3aed)",
                     color:"#fff", fontWeight:600, fontSize:".85rem", cursor: loading ? "default" : "pointer",
                     display:"flex", alignItems:"center", justifyContent:"center", gap:8,
                     fontFamily:"inherit" }}>
            {loading
              ? <><svg style={{width:16,height:16,animation:"spin .8s linear infinite"}} viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" strokeDasharray="30 70"/></svg>Verifying...</>
              : "Sign in"
            }
            <style>{`@keyframes spin{to{transform:rotate(360deg)}}`}</style>
          </button>
        </form>
      </div>
    </div>
  );
}
