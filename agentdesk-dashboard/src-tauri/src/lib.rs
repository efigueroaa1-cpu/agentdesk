use std::collections::HashMap;
use std::sync::Mutex;
use tauri::{AppHandle, Emitter, Manager, State};
use tokio::io::{AsyncBufReadExt, BufReader};
use tokio::process::{Child, Command};
use url::Url;

// ── Estado: agentes individuales en ejecución ─────────────────────────────────
pub struct RunningProcesses {
    pub children: Mutex<HashMap<String, Child>>,
}

// ── Estado: proceso del backend Python (FastAPI / uvicorn) ────────────────────
pub struct BackendState {
    /// Handle del proceso AgentDesk.exe --api (None si no fue lanzado por Tauri)
    pub child: Mutex<Option<Child>>,
}

// ── Agente (estructura mínima para la prueba de fuego) ────────────────────────
#[derive(Debug, serde::Serialize, serde::Deserialize, Clone)]
pub struct Agent {
    pub id:          String,
    pub nombre:      String,
    pub script_path: String,
    pub enabled:     bool,
}


// ═══════════════════════════════════════════════════════════════════════════════
// GESTIÓN DEL BACKEND PYTHON
// ═══════════════════════════════════════════════════════════════════════════════

/// Verifica si hay una instancia del backend respondiendo en `port`
/// con una petición HTTP/1.0 GET /health mínima (sin dependencias extra).
async fn is_backend_alive(port: u16) -> bool {
    use tokio::io::{AsyncReadExt, AsyncWriteExt};

    let Ok(mut stream) = tokio::net::TcpStream::connect(("127.0.0.1", port)).await else {
        return false;
    };
    let req = format!(
        "GET /health HTTP/1.0\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\n\r\n"
    );
    if stream.write_all(req.as_bytes()).await.is_err() {
        return false;
    }
    let mut buf = [0u8; 256];
    match stream.read(&mut buf).await {
        Ok(n) if n > 12 => {
            let s = String::from_utf8_lossy(&buf[..n]);
            // Acepta "HTTP/1.0 200" y "HTTP/1.1 200"
            s.starts_with("HTTP/") && s.contains(" 200 ")
        }
        _ => false,
    }
}

/// Fuente del ejecutable del backend, resuelta en tiempo de ejecución.
enum BackendSource {
    /// Producción: AgentDesk.exe bundleado como recurso de Tauri.
    /// La carpeta AgentDesk/ está en el resource_dir del sistema.
    Bundled(std::path::PathBuf),

    /// Desarrollo: python main.py --api desde la raíz del proyecto Python.
    Development { python_root: std::path::PathBuf },
}

/// Localiza el backend en producción (recursos bundleados) o desarrollo
/// (buscando main.py subiendo desde el directorio de trabajo).
fn localizar_backend(app: &AppHandle) -> Result<BackendSource, String> {
    // ── 1. Producción ─────────────────────────────────────────────────────────
    // Tauri copia AgentDesk/ dentro del resource_dir vía bundle.resources.
    if let Ok(res_dir) = app.path().resource_dir() {
        let exe = res_dir.join("AgentDesk").join("AgentDesk.exe");
        if exe.exists() {
            log::info!("Backend localizado (producción): {}", exe.display());
            return Ok(BackendSource::Bundled(exe));
        }
    }

    // ── 2. Desarrollo ─────────────────────────────────────────────────────────
    // En `tauri dev`, el cwd es agentdesk-dashboard/.
    // El proyecto Python está uno o dos niveles arriba.
    let cwd = std::env::current_dir().map_err(|e| e.to_string())?;

    let candidatos: &[std::path::PathBuf] = &[
        cwd.clone(),
        cwd.parent().map(|p| p.to_path_buf()).unwrap_or_default(),
        cwd.parent()
            .and_then(|p| p.parent())
            .map(|p| p.to_path_buf())
            .unwrap_or_default(),
    ];

    for dir in candidatos {
        if dir.join("main.py").exists() && dir.join("core").is_dir() {
            log::info!("Backend localizado (desarrollo): {}", dir.display());
            return Ok(BackendSource::Development {
                python_root: dir.clone(),
            });
        }
    }

    Err(
        "No se encontró el backend de Python.\n\
         • Producción: AgentDesk\\AgentDesk.exe debe estar en los recursos de la app.\n\
         • Desarrollo: ejecuta tauri dev desde agentdesk-dashboard/ \
           con main.py en el directorio padre."
            .into(),
    )
}

/// Inicia el backend Python si no hay una instancia activa en `port`.
/// Espera hasta 15 s a que el servidor responda en /health.
async fn iniciar_backend(app: &AppHandle, port: u16) -> Result<(), String> {
    // ── ¿Ya hay una instancia activa? ─────────────────────────────────────────
    if is_backend_alive(port).await {
        log::info!(
            "Backend ya activo en el puerto {port} — no se inicia otro proceso."
        );
        return Ok(());
    }

    // ── ¿Ya registramos un proceso? ───────────────────────────────────────────
    {
        let backend_state = app.state::<BackendState>();
        let guard = backend_state
            .child
            .lock()
            .map_err(|_| "Mutex envenenado en BackendState")?;
        if guard.is_some() {
            return Err(
                "Proceso backend ya registrado pero no responde aún. \
                 Espera unos segundos e intenta de nuevo."
                    .into(),
            );
        }
    }

    // ── Construir el comando según la fuente ──────────────────────────────────
    let fuente = localizar_backend(app)?;

    let mut cmd = match &fuente {
        BackendSource::Bundled(exe) => {
            let mut c = Command::new(exe);
            c.args(["--api", "--port", &port.to_string()]);
            c
        }
        BackendSource::Development { python_root } => {
            // En Windows "python", en Unix "python3"
            let python = if cfg!(windows) { "python" } else { "python3" };
            let mut c = Command::new(python);
            c.args(["main.py", "--api", "--port", &port.to_string()])
                .current_dir(python_root);
            c
        }
    };

    // Silenciar stdout/stderr del backend — usa su propio sistema de logging
    // en logs/sistema.log. Los errores críticos se capturan vía is_backend_alive.
    let child = cmd
        .env("PYTHONUNBUFFERED", "1")
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .spawn()
        .map_err(|e| {
            if e.kind() == std::io::ErrorKind::NotFound {
                "Python no encontrado. Instala Python o verifica la distribución del backend.".into()
            } else {
                format!("No se pudo lanzar el backend: {e}")
            }
        })?;

    // Registrar el proceso
    {
        let backend_state = app.state::<BackendState>();
        let mut guard = backend_state
            .child
            .lock()
            .map_err(|_| "Mutex envenenado en BackendState")?;
        *guard = Some(child);
    }

    // ── Polling hasta que /health responda (timeout 15 s) ─────────────────────
    let deadline = std::time::Instant::now() + std::time::Duration::from_secs(15);
    loop {
        if is_backend_alive(port).await {
            log::info!("Backend Python listo en el puerto {port}.");
            return Ok(());
        }
        if std::time::Instant::now() >= deadline {
            // Limpiar el handle del proceso si no arrancó
            let backend_state = app.state::<BackendState>();
            if let Ok(mut guard) = backend_state.child.lock() {
                if let Some(mut c) = guard.take() {
                    let _ = c.start_kill();
                }
            }
            return Err(format!(
                "El backend no respondió en 15 segundos (puerto {port}). \
                 Revisa logs/sistema.log para el detalle."
            ));
        }
        tokio::time::sleep(tokio::time::Duration::from_millis(300)).await;
    }
}

/// Detiene el proceso backend registrado, si existe.
fn detener_backend(app: &AppHandle) {
    if let Ok(mut guard) = app.state::<BackendState>().child.lock() {
        if let Some(mut child) = guard.take() {
            let _ = child.start_kill();
            log::info!("Backend Python detenido.");
        }
    }
}

/// Detiene TODOS los procesos gestionados: agentes individuales + backend Python.
/// Llamar al cerrar la ventana principal para evitar procesos huerfanos.
fn detener_todo(app: &AppHandle) {
    // 1. Matar todos los procesos de agentes individuales
    if let Ok(mut mapa) = app.state::<RunningProcesses>().children.lock() {
        let n = mapa.len();
        for (_id, mut child) in mapa.drain() {
            let _ = child.start_kill();
        }
        if n > 0 {
            log::info!("Detenidos {} proceso(s) de agentes.", n);
        }
    }
    // 2. Matar el backend Python
    detener_backend(app);
}

// ── Comando: arrancar backend desde el frontend ───────────────────────────────
/// Permite que el frontend llame `invoke("start_backend")` para iniciar
/// o reconectar el servidor Python. Útil si el usuario lo cerró manualmente.
#[tauri::command]
async fn start_backend(app: AppHandle) -> Result<serde_json::Value, String> {
    iniciar_backend(&app, 8000).await?;
    Ok(serde_json::json!({ "ok": true, "port": 8000 }))
}

// ── Comando: estado actual del backend ───────────────────────────────────────
#[tauri::command]
async fn backend_status(app: AppHandle) -> serde_json::Value {
    let alive       = is_backend_alive(8000).await;
    let has_process = app
        .state::<BackendState>()
        .child
        .lock()
        .map(|g| g.is_some())
        .unwrap_or(false);

    serde_json::json!({
        "alive":      alive,
        "managed":    has_process,  // true si Tauri lanzó el proceso
        "port":       8000,
    })
}


// ═══════════════════════════════════════════════════════════════════════════════
// AGENTES DE PRUEBA (run_agent / stop_agent)
// ═══════════════════════════════════════════════════════════════════════════════

/// En producción el Python backend se distribuye como:
///   <tauri_exe_dir>\AgentDesk\AgentDesk.exe   (PyInstaller onedir)
///
/// Esta función lo busca junto al ejecutable de Tauri.
/// Si no existe (entorno de desarrollo) devuelve None → se usa "python" del sistema.
fn bundled_python_exe() -> Option<std::path::PathBuf> {
    let exe_dir = std::env::current_exe().ok()?.parent()?.to_path_buf();
    let candidate = exe_dir.join("AgentDesk").join("AgentDesk.exe");
    if candidate.exists() { Some(candidate) } else { None }
}

/// Ruta del script Python para el modo desarrollo.
fn script_path_para(id: &str) -> String {
    let base = std::env::current_dir().unwrap_or_default();
    match id {
        "agente_test_fire" => base.join("test_fire.py").to_string_lossy().into_owned(),
        _ => base.join(format!("{id}.py")).to_string_lossy().into_owned(),
    }
}

// ── get_agents ────────────────────────────────────────────────────────────────
#[tauri::command]
fn get_agents() -> Vec<Agent> {
    vec![Agent {
        id:          "agente_test_fire".into(),
        nombre:      "Test Fire Agent".into(),
        script_path: script_path_para("agente_test_fire"),
        enabled:     true,
    }]
}

// ── run_agent — el botón "Iniciar" llama: invoke("run_agent", { id }) ─────────
#[tauri::command]
async fn run_agent(
    id:        String,
    app:       AppHandle,
    processes: State<'_, RunningProcesses>,
) -> Result<(), String> {

    // Evitar doble ejecución
    {
        let mapa = processes.children.lock().map_err(|_| "Error de lock.")?;
        if mapa.contains_key(&id) {
            return Err(format!("El agente '{}' ya está en ejecución.", id));
        }
    }

    let mut cmd = if let Some(exe) = bundled_python_exe() {
        let mut c = Command::new(exe);
        c.arg("--config").arg(&id);
        c
    } else {
        let script = script_path_para(&id);
        if !std::path::Path::new(&script).exists() {
            return Err(format!(
                "Script no encontrado: {script}\n\
                 Coloca test_fire.py en la raíz del proyecto \
                 o distribuye AgentDesk\\AgentDesk.exe junto al dashboard."
            ));
        }
        let mut c = Command::new("python");
        c.arg(&script).arg("--config").arg(&id);
        c
    };

    let mut child = cmd
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped())
        .env("PYTHONUNBUFFERED", "1")
        .spawn()
        .map_err(|e| {
            if e.kind() == std::io::ErrorKind::NotFound {
                "Python no encontrado. Instala Python o coloca AgentDesk.exe junto al ejecutable.".into()
            } else {
                format!("No se pudo iniciar el agente: {e}")
            }
        })?;

    let stdout = child.stdout.take().ok_or("No se pudo capturar stdout.")?;
    let stderr = child.stderr.take().ok_or("No se pudo capturar stderr.")?;

    {
        let mut mapa = processes.children.lock().map_err(|_| "Error de lock.")?;
        mapa.insert(id.clone(), child);
    }

    app.emit("agent_started", serde_json::json!({ "id": &id })).ok();

    // stdout → agent_log info
    let (app_o, id_o) = (app.clone(), id.clone());
    tokio::spawn(async move {
        let mut lines = BufReader::new(stdout).lines();
        while let Ok(Some(line)) = lines.next_line().await {
            app_o.emit("agent_log", serde_json::json!({
                "id": &id_o, "message": line, "level": "info"
            })).ok();
        }
    });

    // stderr → agent_log error
    let (app_e, id_e) = (app.clone(), id.clone());
    tokio::spawn(async move {
        let mut lines = BufReader::new(stderr).lines();
        while let Ok(Some(line)) = lines.next_line().await {
            app_e.emit("agent_log", serde_json::json!({
                "id": &id_e, "message": line, "level": "error"
            })).ok();
        }
    });

    // Watcher: detecta cuando el proceso termina.
    let app_w = app.clone();
    let id_w  = id.clone();
    tokio::spawn(async move {
        loop {
            tokio::time::sleep(tokio::time::Duration::from_millis(250)).await;
            let state = app_w.state::<RunningProcesses>();
            let Ok(mut mapa) = state.children.lock() else { break; };
            match mapa.get_mut(&id_w) {
                None => break,
                Some(child) => match child.try_wait() {
                    Ok(Some(status)) => {
                        mapa.remove(&id_w);
                        drop(mapa);
                        app_w.emit("agent_stopped", serde_json::json!({
                            "id":      &id_w,
                            "code":    status.code(),
                            "success": status.success(),
                            "crash":   !status.success(),
                        })).ok();
                        break;
                    }
                    Ok(None) => {}
                    Err(e) => {
                        mapa.remove(&id_w);
                        drop(mapa);
                        app_w.emit("agent_stopped", serde_json::json!({
                            "id": &id_w, "code": null,
                            "crash": true, "error": e.to_string()
                        })).ok();
                        break;
                    }
                }
            }
        }
    });

    Ok(())
}

// ── stop_agent ────────────────────────────────────────────────────────────────
#[tauri::command]
async fn stop_agent(
    id:        String,
    app:       AppHandle,
    processes: State<'_, RunningProcesses>,
) -> Result<(), String> {

    let mut child = {
        let mut mapa = processes.children.lock()
            .map_err(|_| "Error de lock.")?;
        mapa.remove(&id)
            .ok_or_else(|| format!("Agente '{}' no está en ejecución.", id))?
    };

    child.kill().await
        .map_err(|e| format!("No se pudo terminar el proceso: {e}"))?;

    app.emit("agent_stopped", serde_json::json!({
        "id": &id, "code": null, "success": false, "crash": false
    })).ok();

    Ok(())
}


// ═══════════════════════════════════════════════════════════════════════════════
// SISTEMA DE USUARIOS — users.json en AppConfig
// ═══════════════════════════════════════════════════════════════════════════════

use bcrypt::{hash, verify, DEFAULT_COST};
use uuid::Uuid;
use std::path::PathBuf;
use sysinfo::System;

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize, PartialEq)]
#[serde(rename_all = "lowercase")]
pub enum Role { Admin, Viewer }

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct User {
    pub id:            String,
    pub username:      String,
    pub password_hash: String,
    pub role:          Role,
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct UserPublic {
    pub id:       String,
    pub username: String,
    pub role:     Role,
}

impl From<&User> for UserPublic {
    fn from(u: &User) -> Self {
        UserPublic { id: u.id.clone(), username: u.username.clone(), role: u.role.clone() }
    }
}

fn users_path(app: &AppHandle) -> PathBuf {
    app.path()
        .app_config_dir()
        .expect("No se pudo obtener AppConfigDir")
        .join("users.json")
}

fn leer_usuarios(app: &AppHandle) -> Result<Vec<User>, String> {
    let path = users_path(app);
    if !path.exists() {
        let admin_hash = hash("admin123", DEFAULT_COST)
            .map_err(|e| format!("Error hasheando contraseña: {e}"))?;
        let admin = User {
            id:            Uuid::new_v4().to_string(),
            username:      "admin".into(),
            password_hash: admin_hash,
            role:          Role::Admin,
        };
        guardar_usuarios_raw(app, &[admin.clone()])?;
        return Ok(vec![admin]);
    }
    let json = std::fs::read_to_string(&path)
        .map_err(|e| format!("Error leyendo users.json: {e}"))?;
    serde_json::from_str(&json)
        .map_err(|e| format!("users.json inválido: {e}"))
}

fn guardar_usuarios_raw(app: &AppHandle, users: &[User]) -> Result<(), String> {
    let path     = users_path(app);
    let tmp_path = path.with_extension("json.tmp");
    if let Some(dir) = path.parent() {
        std::fs::create_dir_all(dir).map_err(|e| e.to_string())?;
    }
    let json = serde_json::to_string_pretty(users)
        .map_err(|e| format!("Error serializando usuarios: {e}"))?;
    std::fs::write(&tmp_path, &json).map_err(|e| e.to_string())?;
    std::fs::rename(&tmp_path, &path).map_err(|e| {
        let _ = std::fs::remove_file(&tmp_path);
        e.to_string()
    })
}

#[tauri::command]
fn login_user(username: String, password: String, app: AppHandle) -> Result<UserPublic, String> {
    let usuarios = leer_usuarios(&app)?;
    let usuario  = usuarios.iter()
        .find(|u| u.username.eq_ignore_ascii_case(username.trim()))
        .ok_or("Usuario o contraseña incorrectos.")?;
    let valida = verify(&password, &usuario.password_hash)
        .map_err(|_| "Error al verificar credenciales.")?;
    if !valida { return Err("Usuario o contraseña incorrectos.".into()); }
    Ok(UserPublic::from(usuario))
}

#[tauri::command]
fn list_users(caller_role: String, app: AppHandle) -> Result<Vec<UserPublic>, String> {
    if caller_role != "admin" {
        return Err("Solo un administrador puede listar usuarios.".into());
    }
    let usuarios = leer_usuarios(&app)?;
    Ok(usuarios.iter().map(UserPublic::from).collect())
}

#[tauri::command]
fn create_user(
    username:    String,
    password:    String,
    role:        String,
    caller_role: String,
    app:         AppHandle,
) -> Result<UserPublic, String> {
    if caller_role != "admin" {
        return Err("Solo un administrador puede crear usuarios.".into());
    }
    if username.trim().is_empty() || password.trim().is_empty() {
        return Err("Usuario y contraseña son obligatorios.".into());
    }
    let mut usuarios = leer_usuarios(&app)?;
    if usuarios.iter().any(|u| u.username.eq_ignore_ascii_case(username.trim())) {
        return Err(format!("El usuario '{}' ya existe.", username.trim()));
    }
    let parsed_role = match role.to_lowercase().as_str() {
        "admin" => Role::Admin,
        _       => Role::Viewer,
    };
    let password_hash = hash(password.trim(), DEFAULT_COST)
        .map_err(|e| format!("Error hasheando contraseña: {e}"))?;
    let nuevo = User {
        id: Uuid::new_v4().to_string(), username: username.trim().to_string(),
        password_hash, role: parsed_role,
    };
    let publico = UserPublic::from(&nuevo);
    usuarios.push(nuevo);
    guardar_usuarios_raw(&app, &usuarios)?;
    Ok(publico)
}

#[tauri::command]
fn change_password(
    username:     String,
    old_password: String,
    new_password: String,
    app:          AppHandle,
) -> Result<(), String> {
    if new_password.trim().len() < 8 {
        return Err("La nueva contraseña debe tener al menos 8 caracteres.".into());
    }
    let mut usuarios = leer_usuarios(&app)?;
    let usuario = usuarios.iter_mut()
        .find(|u| u.username.eq_ignore_ascii_case(username.trim()))
        .ok_or("Usuario no encontrado.")?;
    if !verify(&old_password, &usuario.password_hash).map_err(|_| "Error verificando contraseña.")? {
        return Err("Contraseña actual incorrecta.".into());
    }
    usuario.password_hash = hash(new_password.trim(), DEFAULT_COST)
        .map_err(|e| format!("Error hasheando contraseña: {e}"))?;
    guardar_usuarios_raw(&app, &usuarios)
}

#[tauri::command]
fn delete_user(
    username:    String,
    caller_role: String,
    app:         AppHandle,
) -> Result<(), String> {
    if caller_role != "admin" {
        return Err("Solo un administrador puede eliminar usuarios.".into());
    }
    let mut usuarios = leer_usuarios(&app)?;
    let es_el_ultimo_admin = usuarios.iter()
        .filter(|u| u.role == Role::Admin && !u.username.eq_ignore_ascii_case(username.trim()))
        .count() == 0;
    if es_el_ultimo_admin {
        return Err("No puedes eliminar el último administrador del sistema.".into());
    }
    let len_antes = usuarios.len();
    usuarios.retain(|u| !u.username.eq_ignore_ascii_case(username.trim()));
    if usuarios.len() == len_antes {
        return Err(format!("Usuario '{}' no encontrado.", username));
    }
    guardar_usuarios_raw(&app, &usuarios)
}


// ═══════════════════════════════════════════════════════════════════════════════
// MÉTRICAS DE HARDWARE
// ═══════════════════════════════════════════════════════════════════════════════

async fn hardware_metrics_loop(app: AppHandle) {
    let mut sys = System::new_all();
    loop {
        tokio::time::sleep(tokio::time::Duration::from_secs(2)).await;
        sys.refresh_cpu_usage();
        sys.refresh_memory();
        let cpus    = sys.cpus();
        let cpu_pct = if cpus.is_empty() { 0.0 }
                      else { cpus.iter().map(|c| c.cpu_usage()).sum::<f32>() / cpus.len() as f32 };
        let ram_used_mb  = sys.used_memory()  / 1_048_576;
        let ram_total_mb = sys.total_memory() / 1_048_576;
        let ram_pct      = if ram_total_mb == 0 { 0.0 }
                           else { ram_used_mb as f32 / ram_total_mb as f32 * 100.0 };
        app.emit("hardware_metrics", serde_json::json!({
            "cpu_pct":      (cpu_pct  * 10.0).round() / 10.0,
            "ram_used_mb":  ram_used_mb,
            "ram_total_mb": ram_total_mb,
            "ram_pct":      (ram_pct  * 10.0).round() / 10.0,
        })).ok();
    }
}


// ═══════════════════════════════════════════════════════════════════════════════
// PUNTO DE ENTRADA
// ═══════════════════════════════════════════════════════════════════════════════

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        // ── Plugins ────────────────────────────────────────────────────────────
        .plugin(tauri_plugin_notification::init())
        // ── Estado global ──────────────────────────────────────────────────────
        .manage(RunningProcesses {
            children: Mutex::new(HashMap::new()),
        })
        .manage(BackendState {
            child: Mutex::new(None),
        })
        // ── Setup ──────────────────────────────────────────────────────────────
        .setup(|app| {
            if cfg!(debug_assertions) {
                app.handle().plugin(
                    tauri_plugin_log::Builder::default()
                        .level(log::LevelFilter::Info)
                        .build(),
                )?;
            }

            // Hardware metrics en background
            let handle_hw = app.handle().clone();
            tauri::async_runtime::spawn(hardware_metrics_loop(handle_hw));

            // ── Auto-arranque del backend Python + navegación al React UI ────────
            //
            // Arquitectura:
            //   1. Tauri carga ../loading/index.html (página mínima embebida)
            //   2. Rust inicia AgentDesk.exe --api y espera /health (hasta 15s)
            //   3. Cuando el backend responde, Rust navega el WebView a
            //      http://127.0.0.1:8000/ui/ donde FastAPI sirve el bundle React
            //   4. React corre desde HTTP — ES modules funcionan perfectamente,
            //      sin singlefile IIFE, sin "v is not a function"
            let handle_backend = app.handle().clone();
            tauri::async_runtime::spawn(async move {
                match iniciar_backend(&handle_backend, 8000).await {
                    Ok(()) => {
                        log::info!("Backend Python activo — navegando a /ui/");
                        handle_backend
                            .emit("backend_ready", serde_json::json!({ "port": 8000 }))
                            .ok();

                        // Navigate the main window to the React UI served by Python
                        if let Some(window) = handle_backend.get_webview_window("main") {
                            match Url::parse("http://127.0.0.1:8000/ui/") {
                                Ok(url) => {
                                    if let Err(e) = window.navigate(url) {
                                        log::error!("navigate() failed: {e}");
                                    }
                                }
                                Err(e) => log::error!("URL parse failed: {e}"),
                            }
                        }
                    }
                    Err(e) => {
                        log::error!("Backend no iniciado: {e}");
                        handle_backend
                            .emit("backend_error", serde_json::json!({ "error": e }))
                            .ok();

                        // Muestra pagina de error directamente en el WebView.
                        // Funciona antes de que React cargue (la loading page ya esta activa).
                        if let Some(window) = handle_backend.get_webview_window("main") {
                            let safe = e
                                .replace('\\', "\\\\")
                                .replace('\'', "\\'")
                                .replace('\n', "\\n");
                            let _ = window.eval(&format!(
                                "document.open();\
                                 document.write('<html><body style=\"font-family:monospace;\
                                 background:#060f1c;color:#a8c0da;padding:2rem;margin:0\">\
                                 <h2 style=\"color:#ff3d60;margin-bottom:1rem\">AgentDesk &mdash; Error de inicio</h2>\
                                 <pre style=\"background:#0d2038;border:1px solid rgba(0,212,255,.2);\
                                 padding:1rem;border-radius:6px;color:#7dd3fc;white-space:pre-wrap\">{safe}</pre>\
                                 <p style=\"margin-top:1rem;color:#3d5a78;font-size:.85rem\">\
                                 Revisa logs/sistema.log &bull; Cierra y vuelve a abrir la aplicacion.\
                                 </p></body></html>');\
                                 document.close();"
                            ));
                        }
                    }
                }
            });

            // ── Matar TODOS los procesos al destruir la ventana principal ────────
            // detener_todo() elimina agentes individuales + backend Python
            // evitando procesos huerfanos tras cerrar la app.
            let handle_close = app.handle().clone();
            if let Some(window) = app.get_webview_window("main") {
                window.on_window_event(move |event| {
                    if let tauri::WindowEvent::Destroyed = event {
                        detener_todo(&handle_close);
                    }
                });
            }

            Ok(())
        })
        // ── Comandos disponibles para el frontend ──────────────────────────────
        .invoke_handler(tauri::generate_handler![
            // Ciclo de vida del backend Python
            start_backend,
            backend_status,
            // Agentes de prueba
            get_agents,
            run_agent,
            stop_agent,
            // Gestión de usuarios
            login_user,
            list_users,
            create_user,
            change_password,
            delete_user,
        ])
        .run(tauri::generate_context!())
        .expect("Error al iniciar Tauri");
}
