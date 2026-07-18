# scripts/sign_release.ps1 — Firma Authenticode del release (Fase 27, ADR-0022/0025)
# PowerShell 5.1+
#
# Firma y VERIFICA el instalador NSIS (y opcionalmente AgentDesk.exe) con el
# certificado de codigo configurado:
#   $env:AGENTDESK_SIGN_CERT = "C:\ruta\certificado.pfx"   (EV u OV)
#   $env:AGENTDESK_SIGN_PASS = "<clave del .pfx>"
#
# Uso:
#   .\scripts\sign_release.ps1                      # firma el instalador mas reciente
#   .\scripts\sign_release.ps1 -Path <archivo.exe>  # firma un artefacto especifico
#   .\scripts\sign_release.ps1 -SelfSignedTest      # prueba el pipeline con un
#                                                   # certificado self-signed efimero
#
# VERDAD TECNICA sobre SmartScreen (documentada, no maquillada):
#   - Un certificado EV elimina la advertencia de inmediato (reputacion
#     instantanea). Un OV la elimina gradualmente (reputacion acumulada por
#     descargas). Un self-signed NUNCA la elimina — el modo -SelfSignedTest
#     existe solo para validar que ESTE pipeline funciona de punta a punta,
#     de modo que al llegar el certificado real sea un cambio de env var.

param(
    [string]$Path = "",
    [switch]$SelfSignedTest
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)

function OK   { param([string]$M) Write-Host "  OK: $M"    -ForegroundColor Green }
function Warn { param([string]$M) Write-Host "  AVISO: $M" -ForegroundColor Yellow }
function Fail { param([string]$M) Write-Host "  ERROR: $M" -ForegroundColor Red; exit 1 }

# ── Localizar signtool ───────────────────────────────────────────────────────
$signtool = (Get-Command signtool.exe -ErrorAction SilentlyContinue).Source
if (-not $signtool) {
    $sdk = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\bin\*\x64\signtool.exe" -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending | Select-Object -First 1
    if ($sdk) { $signtool = $sdk.FullName } else { Fail "signtool.exe no encontrado (instala el Windows SDK)." }
}
OK "signtool: $signtool"

# ── Localizar el artefacto ───────────────────────────────────────────────────
if (-not $Path) {
    $instalador = Get-ChildItem (Join-Path $Root "AgentDesk_*-setup*.exe") -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $instalador) { Fail "No hay instalador AgentDesk_*-setup*.exe en $Root. Corre build_all.ps1 primero." }
    $Path = $instalador.FullName
}
if (-not (Test-Path $Path)) { Fail "Artefacto inexistente: $Path" }
OK "Artefacto: $Path"

# ── Resolver certificado ─────────────────────────────────────────────────────
$certPfx = $env:AGENTDESK_SIGN_CERT
$certPass = $env:AGENTDESK_SIGN_PASS
$tempPfx = $null

if ($SelfSignedTest) {
    Warn "Modo -SelfSignedTest: certificado efimero SOLO para validar el pipeline."
    Warn "Un self-signed NO elimina SmartScreen — para eso: certificado EV/OV real."
    $cert = New-SelfSignedCertificate -Type CodeSigningCert `
        -Subject "CN=AgentDesk Dev Test" -CertStoreLocation Cert:\CurrentUser\My `
        -NotAfter (Get-Date).AddDays(2)
    $tempPfx  = Join-Path $env:TEMP "agentdesk_selfsigned_test.pfx"
    $certPass = "test-$(Get-Random)"
    $secure   = ConvertTo-SecureString $certPass -AsPlainText -Force
    Export-PfxCertificate -Cert $cert -FilePath $tempPfx -Password $secure | Out-Null
    $certPfx = $tempPfx
} elseif (-not $certPfx) {
    Fail "AGENTDESK_SIGN_CERT no configurada. Con el certificado EV/OV: `$env:AGENTDESK_SIGN_CERT='C:\ruta\cert.pfx'; `$env:AGENTDESK_SIGN_PASS='<clave>'. Para probar el pipeline sin certificado: -SelfSignedTest"
} elseif (-not (Test-Path $certPfx)) {
    Fail "AGENTDESK_SIGN_CERT apunta a un archivo inexistente: $certPfx"
}

# ── Firmar (SHA256 + timestamp RFC3161) ──────────────────────────────────────
& $signtool sign /f $certPfx /p $certPass /fd SHA256 `
    /tr http://timestamp.digicert.com /td SHA256 $Path
if ($LASTEXITCODE -ne 0) { Fail "signtool sign fallo (exit $LASTEXITCODE)." }
OK "Firmado: $(Split-Path $Path -Leaf)"

# ── Verificar la firma ───────────────────────────────────────────────────────
# /pa = politica Authenticode. Con self-signed la CADENA no valida (esperado):
# se verifica en su lugar que la firma exista y el hash coincida.
& $signtool verify /pa $Path
if ($LASTEXITCODE -eq 0) {
    OK "Verificacion /pa: cadena de confianza completa (certificado real)."
} elseif ($SelfSignedTest) {
    $firma = Get-AuthenticodeSignature $Path
    if ($firma.SignerCertificate -and $firma.Status -in @("UnknownError", "NotTrusted", "Valid")) {
        OK "Self-signed: firma presente y hash integro (Status=$($firma.Status))."
        Warn "La cadena no valida con self-signed — comportamiento esperado."
    } else {
        Fail "La firma no quedo aplicada (Status=$($firma.Status))."
    }
} else {
    Fail "signtool verify fallo con el certificado configurado."
}

# ── Limpieza del modo test ───────────────────────────────────────────────────
if ($tempPfx) {
    Remove-Item $tempPfx -Force -ErrorAction SilentlyContinue
    Get-ChildItem Cert:\CurrentUser\My |
        Where-Object { $_.Subject -eq "CN=AgentDesk Dev Test" } |
        Remove-Item -Force -ErrorAction SilentlyContinue
    Warn "Certificado de prueba eliminado del almacen."
}

Write-Host ""
OK "Pipeline de firma completado."
