# gate.ps1 — Quality Gate del monorepo AgentDesk
#
# Guardián de calidad previo a commit/push. Bloquea (exit 1) si:
#   1. Hay etiquetas TODO / FIXME / PATCH en el código fuente (excluye este script).
#   2. Alguna prueba de test_security.py falla.
#   3. Existen residuos de parches manuales (*.bak, *.orig, *.rej, *.patch).
#   4. scripts/gate.py detecta violaciones de arquitectura hexagonal (ADR-0002).
#
# Uso:  .\gate.ps1          (desde la raíz del monorepo)
# Compatible con Windows PowerShell 5.1.

$ErrorActionPreference = "Stop"
$raiz = $PSScriptRoot
Set-Location $raiz

$fallos = @()

Write-Host "=== AgentDesk Quality Gate ===" -ForegroundColor Cyan

# ── Inventario de archivos fuente ──────────────────────────────────────────────
# git ls-files respeta .gitignore (excluye node_modules, target, dist, builds…)
# e incluye también archivos nuevos aún sin trackear (--others --exclude-standard).
$extensiones = '\.(py|ts|tsx|js|jsx|rs|ps1|psm1|css|html|json|toml|yml|yaml)$'
$archivos = @(git ls-files --cached --others --exclude-standard) |
    Where-Object { $_ -match $extensiones } |
    Where-Object { $_ -ne 'gate.ps1' } |
    Where-Object { $_ -notmatch '(^|/)(node_modules|dist|build|react_dist|loading)/' } |
    Where-Object { Test-Path (Join-Path $raiz $_) }

Write-Host ("Archivos fuente analizados: {0}" -f $archivos.Count)

# ── Check 1: etiquetas TODO / FIXME / PATCH ────────────────────────────────────
# Solo etiquetas reales de marcador: al inicio de un comentario (#, //, /*, <!--)
# o seguidas de ':'. Evita falsos positivos con la palabra española "todo".
Write-Host "`n[1/4] Buscando etiquetas TODO / FIXME / PATCH..." -ForegroundColor Cyan
$patronTags = '(#|//|/\*|<!--)\s*(TODO|FIXME|PATCH)\b|\b(TODO|FIXME|PATCH):'
$tags = @()
foreach ($f in $archivos) {
    $hits = Select-String -Path (Join-Path $raiz $f) -Pattern $patronTags -CaseSensitive
    if ($hits) { $tags += $hits }
}
if ($tags.Count -gt 0) {
    Write-Host ("  BLOQUEADO: {0} etiqueta(s) encontrada(s):" -f $tags.Count) -ForegroundColor Red
    foreach ($t in $tags) {
        Write-Host ("    {0}:{1}  {2}" -f $t.Path.Replace("$raiz\", ""), $t.LineNumber, $t.Line.Trim()) -ForegroundColor Yellow
    }
    $fallos += "Etiquetas TODO/FIXME/PATCH en el código fuente."
} else {
    Write-Host "  OK: sin etiquetas pendientes." -ForegroundColor Green
}

# ── Check 2: suite de seguridad ────────────────────────────────────────────────
Write-Host "`n[2/4] Ejecutando test_security.py..." -ForegroundColor Cyan
python -m unittest test_security -v
if ($LASTEXITCODE -ne 0) {
    Write-Host "  BLOQUEADO: la suite de seguridad falló." -ForegroundColor Red
    $fallos += "test_security.py con pruebas fallidas."
} else {
    Write-Host "  OK: suite de seguridad en verde." -ForegroundColor Green
}

# ── Check 3: residuos de parches manuales ──────────────────────────────────────
Write-Host "`n[3/4] Buscando residuos de parches (*.bak, *.orig, *.rej, *.patch)..." -ForegroundColor Cyan
$residuos = @(git ls-files --cached --others --exclude-standard) |
    Where-Object { $_ -match '\.(bak|orig|rej|patch)$' }
if ($residuos.Count -gt 0) {
    Write-Host "  BLOQUEADO: residuos encontrados:" -ForegroundColor Red
    $residuos | ForEach-Object { Write-Host ("    {0}" -f $_) -ForegroundColor Yellow }
    $fallos += "Archivos residuales de parches manuales."
} else {
    Write-Host "  OK: sin residuos." -ForegroundColor Green
}

# ── Check 4: Guardián de Arquitectura hexagonal (ADR-0002) ─────────────────────
Write-Host "`n[4/4] Ejecutando scripts/gate.py (arquitectura hexagonal)..." -ForegroundColor Cyan
python scripts\gate.py
if ($LASTEXITCODE -ne 0) {
    Write-Host "  BLOQUEADO: violaciones de arquitectura." -ForegroundColor Red
    $fallos += "scripts/gate.py detectó violaciones de arquitectura."
} else {
    Write-Host "  OK: arquitectura hexagonal respetada." -ForegroundColor Green
}

# ── Veredicto ──────────────────────────────────────────────────────────────────
Write-Host ""
if ($fallos.Count -gt 0) {
    Write-Host "=== GATE BLOQUEADO ===" -ForegroundColor Red
    $fallos | ForEach-Object { Write-Host (" - {0}" -f $_) -ForegroundColor Red }
    exit 1
}
Write-Host "=== GATE APROBADO: el código puede subir ===" -ForegroundColor Green
exit 0
