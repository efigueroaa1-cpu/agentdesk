# build_all.ps1 - Build industrial completo para AgentDesk
# PowerShell 5.1+  |  Ejecutar desde la raiz del proyecto Python
#
# Uso:
#   .\build_all.ps1                      # Build completo
#   .\build_all.ps1 -SkipReact           # Saltar compilacion de React
#   .\build_all.ps1 -SkipPython          # Saltar PyInstaller
#   .\build_all.ps1 -SkipTauri           # Saltar tauri build (solo backend)
#   .\build_all.ps1 -DeployLocal         # Instalar en AppData despues del build
#
# Prerequisitos:
#   - Node.js >= 18  (npm en PATH)
#   - Python 3.13    (python en PATH)
#   - Rust + Cargo   (para tauri build)
#   - PyInstaller    (pip install pyinstaller)

param(
    [switch]$SkipReact,
    [switch]$SkipPython,
    [switch]$SkipTauri,
    [switch]$DeployLocal
)

$ErrorActionPreference = "Stop"

# ── Guard de integridad: prohibido construir con artefactos de parcheo ──────────
$bakFiles = Get-ChildItem -Path $PSScriptRoot -Recurse -Include "*.bak*" -File -ErrorAction SilentlyContinue |
    Where-Object { $_.FullName -notmatch "node_modules|target|\\dist\\|\\build\\" }
if ($bakFiles) {
    Write-Host "ERROR: Archivos .bak detectados (residuos de parcheo manual):" -ForegroundColor Red
    $bakFiles | ForEach-Object { Write-Host "  $($_.FullName)" -ForegroundColor Red }
    Write-Host "Todo comportamiento debe residir en el codigo fuente. Elimina los .bak y reintenta." -ForegroundColor Red
    exit 1
}

$Root     = Split-Path -Parent $MyInvocation.MyCommand.Path
$Dashboard = Join-Path $Root "agentdesk-dashboard"
$TauriDir  = Join-Path $Dashboard "src-tauri"
$Resources = Join-Path $TauriDir "resources\AgentDesk"
$DistDir   = Join-Path $Root "dist\AgentDesk"
$AppData   = "$env:LOCALAPPDATA\AgentDesk\AgentDesk"

# Timestamp para el instalador
$TS = Get-Date -Format "yyyyMMdd_HHmm"

# ── Colores ──────────────────────────────────────────────────────────────────────
function Step  { param([string]$M) Write-Host "`n==> $M" -ForegroundColor Cyan }
function OK    { param([string]$M) Write-Host "    OK: $M" -ForegroundColor Green }
function Warn  { param([string]$M) Write-Host "    AVISO: $M" -ForegroundColor Yellow }
function Fail  { param([string]$M) Write-Host "`n    ERROR: $M" -ForegroundColor Red; exit 1 }

# ── Verificar prerequisitos ───────────────────────────────────────────────────────
Step "Verificando prerequisitos..."
try { $null = (Get-Command node -ErrorAction Stop); OK "Node.js: $((node --version))" } catch { Fail "Node.js no encontrado. Instala desde nodejs.org" }
try { $null = (Get-Command npm  -ErrorAction Stop); OK "npm: $((npm --version))" }   catch { Fail "npm no encontrado." }
try { $null = (Get-Command python -ErrorAction Stop) } catch { Fail "Python no encontrado." }

# Verificar version minima de Python (3.11+)
$pyVer = python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
if ($LASTEXITCODE -ne 0) { Fail "No se pudo determinar la version de Python." }
$pyParts = $pyVer.Split(".")
if ([int]$pyParts[0] -lt 3 -or ([int]$pyParts[0] -eq 3 -and [int]$pyParts[1] -lt 11)) {
    Fail "Python 3.11+ requerido. Version actual: $pyVer. Instala desde python.org"
}
OK "Python: $pyVer"

if (-not $SkipPython) {
    $piResult = python -c "import PyInstaller; print(PyInstaller.__version__)" 2>$null
    if ($LASTEXITCODE -ne 0) { Fail "PyInstaller no instalado. Ejecuta: pip install pyinstaller" }
    OK "PyInstaller: $piResult"
}

if (-not $SkipTauri) {
    try { $null = (Get-Command cargo -ErrorAction Stop); OK "Rust/Cargo: $((cargo --version))" } catch { Fail "Rust/Cargo no encontrado. Instala desde rustup.rs" }

    # Verificar WebView2 Runtime (requerido por Tauri en Windows)
    $wv2Paths = @(
        "HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}",
        "HKCU:\SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}",
        "HKLM:\SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
    )
    $wv2Found = $false
    foreach ($p in $wv2Paths) {
        if (Test-Path $p) {
            $wv2Ver = (Get-ItemProperty -Path $p -ErrorAction SilentlyContinue).pv
            if ($wv2Ver) { OK "WebView2 Runtime: $wv2Ver"; $wv2Found = $true; break }
        }
    }
    if (-not $wv2Found) {
        Warn "WebView2 Runtime no detectado en el registro."
        Warn "El instalador NSIS de Tauri lo incluye automaticamente (modo bootstrapper)."
        Warn "Para builds de desarrollo: instala desde https://developer.microsoft.com/microsoft-edge/webview2/"
    }
}

# ── 1. Build React (Vite) ─────────────────────────────────────────────────────────
if (-not $SkipReact) {
    Step "Compilando React con Vite..."
    Set-Location $Dashboard
    npm ci --prefer-offline --legacy-peer-deps 2>$null
    if ($LASTEXITCODE -ne 0) { npm install --legacy-peer-deps }
    npm run build
    if ($LASTEXITCODE -ne 0) { Fail "npm run build fallo" }

    # Copiar dist → react_dist/ en raiz del proyecto Python (usado por PyInstaller)
    $src = Join-Path $Dashboard "dist"
    $dst = Join-Path $Root "react_dist"
    if (Test-Path $dst) { Remove-Item $dst -Recurse -Force }
    Copy-Item $src $dst -Recurse
    OK "React bundle copiado a react_dist/ ($(((Get-ChildItem $dst -Recurse | Measure-Object Length -Sum).Sum / 1MB).ToString('F1')) MB)"
    Set-Location $Root
}

# ── 2. PyInstaller — Backend Python ──────────────────────────────────────────────
if (-not $SkipPython) {
    Step "Compilando backend Python con PyInstaller..."
    Set-Location $Root

    # Limpiar builds anteriores para evitar conflictos
    if (Test-Path "dist") { Remove-Item "dist" -Recurse -Force }
    if (Test-Path "build") { Remove-Item "build" -Recurse -Force }

    python -m PyInstaller agentdesk.spec --clean --noconfirm
    if ($LASTEXITCODE -ne 0) { Fail "PyInstaller fallo. Revisa el log de arriba." }

    if (-not (Test-Path "$DistDir\AgentDesk.exe")) {
        Fail "AgentDesk.exe no fue generado en $DistDir"
    }
    $exeSize = (Get-Item "$DistDir\AgentDesk.exe").Length / 1MB
    OK "Backend compilado: AgentDesk.exe ($($exeSize.ToString('F1')) MB)"
    OK "Directorio completo: $DistDir"

    # Copiar output de PyInstaller a recursos de Tauri
    Step "Copiando backend a recursos Tauri..."
    if (Test-Path $Resources) { Remove-Item $Resources -Recurse -Force }
    New-Item -ItemType Directory -Force $Resources | Out-Null
    Copy-Item "$DistDir\*" $Resources -Recurse -Force
    OK "Backend copiado a $Resources"
}

# ── 3. Tauri Build — Instalador NSIS ─────────────────────────────────────────────
if (-not $SkipTauri) {
    Step "Compilando Tauri (instalador Windows NSIS)..."
    Set-Location $Dashboard

    $env:TAURI_SKIP_SIDECAR_VALIDATION = "1"   # no hay sidecar, el exe se bundlea como recurso
    npm run tauri build
    if ($LASTEXITCODE -ne 0) { Fail "tauri build fallo. Revisa el log de arriba." }

    $nsisDir  = Join-Path $TauriDir "target\release\bundle\nsis"
    $installer = Get-ChildItem $nsisDir -Filter "*.exe" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($installer) {
        $newName = [System.IO.Path]::GetFileNameWithoutExtension($installer.Name) + "_$TS.exe"
        $dest    = Join-Path $Root $newName
        Copy-Item $installer.FullName $dest
        OK "Instalador: $newName ($([Math]::Round($installer.Length/1MB,1)) MB)"
        OK "Copiado a: $dest"
    } else {
        Warn "No se encontro el instalador .exe en $nsisDir"
    }
    Set-Location $Root
}

# ── 4. Deploy local (opcional) ────────────────────────────────────────────────────
if ($DeployLocal) {
    Step "Instalando en AppData para prueba rapida..."
    if (-not (Test-Path $DistDir)) {
        Fail "dist\AgentDesk\ no existe. Ejecuta sin -SkipPython primero."
    }

    # Parar procesos activos
    @("AgentDesk", "app") | ForEach-Object {
        $proc = Get-Process -Name $_ -ErrorAction SilentlyContinue
        if ($proc) { $proc | Stop-Process -Force; Warn "Proceso $_ detenido." }
    }
    Start-Sleep -Milliseconds 800

    # Crear estructura de AppData si no existe (primer arranque)
    # Incluye logs, reportes y db para que el backend los encuentre sin fallos de I/O
    $AppDataDirs = @(
        $AppData,
        (Join-Path $AppData "_internal"),
        (Join-Path $AppData "_internal\logs"),
        (Join-Path $AppData "_internal\data"),
        (Join-Path $AppData "_internal\reportes"),
        (Join-Path $AppData "_internal\db")
    )
    foreach ($d in $AppDataDirs) {
        if (-not (Test-Path $d)) {
            New-Item -ItemType Directory -Force $d | Out-Null
            OK "Creado directorio: $d"
        }
    }

    # Copiar backend
    Copy-Item "$DistDir\*" $AppData -Recurse -Force
    OK "Backend actualizado en $AppData"

    # Copiar .env si existe en la raiz del proyecto (primer arranque)
    $envSrc = Join-Path $Root ".env"
    $envDst = Join-Path $AppData ".env"
    if ((Test-Path $envSrc) -and -not (Test-Path $envDst)) {
        Copy-Item $envSrc $envDst
        OK ".env copiado a AppData (primer arranque)"
    } elseif (-not (Test-Path $envSrc)) {
        Warn ".env no encontrado en $Root — crea uno con MASTER_PASSWORD_HASH y GEMINI_API_KEY"
    }

    # Copiar config.json por defecto si no existe
    $cfgSrc = Join-Path $Root "config.json"
    $cfgDst = Join-Path $AppData "_internal\config.json"
    if ((Test-Path $cfgSrc) -and -not (Test-Path $cfgDst)) {
        Copy-Item $cfgSrc $cfgDst
        OK "config.json copiado a AppData (primer arranque)"
    }
}

# ── Resumen ───────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host " Build AgentDesk completado  $TS" -ForegroundColor Cyan
Write-Host "================================================================" -ForegroundColor Cyan
if (-not $SkipReact)  { Write-Host "  React bundle : react_dist/" -ForegroundColor Green }
if (-not $SkipPython) { Write-Host "  Backend      : dist\AgentDesk\AgentDesk.exe" -ForegroundColor Green }
if (-not $SkipTauri)  { Write-Host "  Instalador   : AgentDesk_*_$TS.exe" -ForegroundColor Green }
Write-Host ""
Write-Host "Arquitectura HTTP definitiva:" -ForegroundColor Yellow
Write-Host "  app.exe (Tauri)  ──►  AgentDesk.exe (PyInstaller/FastAPI en 127.0.0.1:8000)"
Write-Host "  Dashboard React  ──►  http://127.0.0.1:8000/ui/  (StaticFiles, Vite bundle)"
Write-Host "  WebSocket        ──►  ws://127.0.0.1:8000/ws/telemetria?token=<JWT>"
Write-Host ""
Write-Host "Notas de despliegue:" -ForegroundColor Yellow
Write-Host "  1. Copia .env junto a AgentDesk.exe con tus API keys."
Write-Host "  2. Genera MASTER_PASSWORD_HASH con:"
Write-Host "       python -c ""import bcrypt; print(bcrypt.hashpw(b'tupassword',bcrypt.gensalt()).decode())"""
Write-Host "  3. Agrega MASTER_PASSWORD_HASH=<hash> al .env para el primer arranque."
Write-Host "  4. En el primer login usa el usuario 'admin' con la contrasena del hash."
Write-Host "  5. AppData crea automaticamente: logs/, reportes/, db/ en primer arranque."
Write-Host "  6. El manual de usuario PDF se genera desde: GET /docs/manual?empresa=NombreEmpresa"
Write-Host ""
