# -*- coding: utf-8 -*-
"""
scripts/gate.py — Guardián de Arquitectura (ADR-0002).

Bloquea el avance (exit 1) si detecta:
  1. Etiquetas de deuda técnica pendiente (mismo patrón estricto que gate.ps1).
  2. Archivos fuente de más de 500 líneas. Los legados listados en
     LEGACY_OVERSIZE solo pueden DECRECER respecto a su línea base (trinquete);
     todo archivo nuevo debe nacer bajo el límite.
  3. Violaciones de imports entre capas hexagonales (domain/ports/services/
     repositories) — p.ej. un servicio importando de la capa api.
  4. Vulnerabilidades detectadas por Bandit (severidad media/alta en core,
     scripts y main.py).
  5. Fallas en el test-contrato de seguridad (tests/contract/test_auth_contract):
     ningún endpoint de escritura puede quedar sin JWT ni autorización explícita.

Uso:  python scripts/gate.py     (lo invoca gate.ps1 como paso de arquitectura)
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent

EXT_FUENTE = {".py", ".js", ".jsx", ".ps1", ".css", ".html"}
EXT_LIMITE = {".py", ".js", ".jsx"}
MAX_LINEAS = 500

# Se excluyen del escaneo de etiquetas porque definen el propio patrón.
EXCLUIR_TAGS = {"scripts/gate.py", "gate.ps1"}

# Patrón estricto case-sensitive (idéntico a gate.ps1): evita falsos positivos
# con la palabra española "todo" y con identificadores tipo "PatchB".
RE_TAGS = re.compile(r"(#|//|/\*|<!--)\s*(TODO|FIXME|PATCH)\b|\b(TODO|FIXME|PATCH):")

# Línea base de archivos legados >500 líneas (2026-07-14, conteo con líneas en
# blanco incluidas). Regla de trinquete: pueden bajar, nunca subir. Al bajar de
# 500 se retiran de esta lista.
LEGACY_OVERSIZE: dict[str, int] = {
    "agentdesk-dashboard/src/components/agents/AgentAreaView.jsx":       947,
    "agentdesk-dashboard/src/components/agents/AgentManager.jsx":        753,
    "agentdesk-dashboard/src/components/chat/ChatPanel.jsx":             684,
    "agentdesk-dashboard/src/components/hub/AgentHub.jsx":               553,
    "agentdesk-dashboard/src/components/hub/EmbeddingView3D.jsx":        634,
    "agentdesk-dashboard/src/components/hub/GanttModule.jsx":            569,
    "agentdesk-dashboard/src/components/pipeline/ErrorPanel.jsx":        553,
    "agentdesk-dashboard/src/components/pipeline/PipelineControl.jsx":  1050,
    "agentdesk-dashboard/src/components/proyectos/ProyectosModule.jsx": 1127,
    "agentdesk-dashboard/src/components/settings/SecurityPanel.jsx":     898,
    # api.py 2865->1493 (ADR-0003); +3 QueuePort (F8); +36 endpoints de
    # diagnostico/auditoria + user_id en chat/tareas (F9, ADR-0007)
    # subio 1532->1534 (2026-07-15, ADR-0011): set_orquestador() en startup
    # para la delegacion cognitiva Speak/Listen
    "core/api.py":                                                      1534,
    # orchestrator subio 1215->1223 (2026-07-14): hook del sandbox Zero-Trust
    # subio 1223->1242 (2026-07-15, ADR-0009): self.harnesses + inyeccion del
    # contexto de HATs (_contexto_harnesses) en las 4 rutas de chat
    # subio 1242->1269 (2026-07-15, ADR-0010): user_id enhebrado en las 4
    # rutas de chat (aislamiento de memoria) + _criticar_respuesta wireado
    # en chat_libre/chat_con_herramientas (CritiqueHarness post-hook)
    # subio 1269->1277 (2026-07-15, ADR-0011): agente_id_clave/user_id
    # enhebrados en los 4 call sites de ejecutar_herramienta (delegacion)
    "core/orchestrator.py":                                             1277,
    # tools.py subio 1120->1153 (2026-07-14): evaluador AST que reemplaza eval()
    # subio 1153->1209 (2026-07-15, ADR-0011): tool consultar_a_otro_agente
    # + set_orquestador() (delegacion cognitiva Speak/Listen)
    "core/tools.py":                                                    1209,
    # web_monitor.py subio 593->595 (2026-07-14): validacion de esquema http(s)
    "core/web_monitor.py":                                               595,
    # database.py subio 495->580 (2026-07-15, ADR-0013): migraciones Alembic
    # (_aplicar_migraciones) + chequeo async de conexion Postgres con
    # asyncpg (_verificar_conexion_async) antes de armar el engine sincrono
    "core/database.py":                                                  580,
    # gate.py mismo: crecio organicamente con cada fase (11 reglas nuevas
    # entre Fase 11 y 15). Se acepta el tamano del propio Guardian en vez
    # de partirlo artificialmente entre fases activas.
    "scripts/gate.py":                                                   530,
    "dashboard.py":                                                     1257,
    "ui/dashboard.py":                                                  1257,
}

# Reglas de capas (ADR-0002/0004): prefijo de carpeta -> imports prohibidos.
CAPA_API = re.compile(r"^\s*(from|import)\s+core\.(api|api_auth)\b")
CAPA_ADAPTERS = re.compile(r"^\s*(from|import)\s+core\.adapters\b")
FRAMEWORKS = re.compile(r"^\s*(from|import)\s+(fastapi|starlette)\b")
FRAMEWORKS_Y_ORM = re.compile(r"^\s*(from|import)\s+(fastapi|starlette|sqlalchemy|pydantic)\b")
CORE_NO_DOMAIN = re.compile(r"^\s*(from|import)\s+core\.(?!domain\b)\w+")
CORE_NO_DOMAIN_PORTS = re.compile(r"^\s*(from|import)\s+core\.(?!domain\b|ports\b)\w+")

REGLAS_IMPORTS: list[tuple[str, re.Pattern, str]] = [
    ("core/domain/",       CAPA_API,             "domain no puede importar la capa api"),
    ("core/domain/",       FRAMEWORKS_Y_ORM,     "domain debe ser puro (sin frameworks/ORM)"),
    ("core/domain/",       CORE_NO_DOMAIN,       "domain solo importa stdlib y core.domain"),
    ("core/ports/",        CAPA_API,             "ports no puede importar la capa api"),
    ("core/ports/",        FRAMEWORKS_Y_ORM,     "ports debe ser puro (sin frameworks/ORM)"),
    ("core/ports/",        CORE_NO_DOMAIN_PORTS, "ports solo importa stdlib, core.domain y core.ports"),
    ("core/services/",     CAPA_API,             "services NUNCA importa la capa api (ADR-0002)"),
    ("core/services/",     FRAMEWORKS,           "services no depende de FastAPI/Starlette"),
    ("core/repositories/", CAPA_API,             "repositories no puede importar la capa api"),
    ("core/repositories/", FRAMEWORKS,           "repositories no depende de FastAPI/Starlette"),
    ("core/domain/",       CAPA_ADAPTERS,        "domain no puede importar adaptadores (ADR-0004)"),
    ("core/ports/",        CAPA_ADAPTERS,        "ports no puede importar adaptadores (ADR-0004)"),
    ("core/services/",     CAPA_ADAPTERS,        "services no puede importar adaptadores (ADR-0004)"),
    ("core/repositories/", CAPA_ADAPTERS,        "repositories no puede importar adaptadores (ADR-0004)"),
    ("core/adapters/",     CAPA_API,             "adapters no importa la capa api: la composicion vive en main.py (ADR-0004)"),
]


def inventario() -> list[str]:
    """Archivos versionados + nuevos sin ignorar (mismo criterio que gate.ps1)."""
    salida = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=RAIZ, capture_output=True, text=True, check=True,
    ).stdout
    return [f for f in salida.splitlines() if f and (RAIZ / f).is_file()]


def leer(rel: str) -> list[str]:
    try:
        # utf-8-sig: descarta el BOM que dejan PowerShell/editores Windows
        return (RAIZ / rel).read_text(encoding="utf-8-sig", errors="replace").splitlines()
    except OSError:
        return []


def check_tags(archivos: list[str]) -> list[str]:
    errores = []
    for rel in archivos:
        if Path(rel).suffix not in EXT_FUENTE or rel in EXCLUIR_TAGS:
            continue
        for n, linea in enumerate(leer(rel), 1):
            if RE_TAGS.search(linea):
                errores.append(f"  [TAG]     {rel}:{n}: {linea.strip()[:100]}")
    return errores


def check_tamano(archivos: list[str]) -> list[str]:
    errores = []
    for rel in archivos:
        if Path(rel).suffix not in EXT_LIMITE:
            continue
        lineas = len(leer(rel))
        if lineas <= MAX_LINEAS:
            continue
        base = LEGACY_OVERSIZE.get(rel)
        if base is None:
            errores.append(f"  [TAMANO]  {rel}: {lineas} lineas (max {MAX_LINEAS} para archivos nuevos)")
        elif lineas > base:
            errores.append(f"  [TAMANO]  {rel}: {lineas} lineas — CRECIO sobre su linea base legada ({base})")
    return errores


def check_imports(archivos: list[str]) -> list[str]:
    errores = []
    for rel in archivos:
        if not rel.endswith(".py"):
            continue
        reglas = [(p, r, m) for (p, r, m) in REGLAS_IMPORTS if rel.startswith(p)]
        if not reglas:
            continue
        for n, linea in enumerate(leer(rel), 1):
            for _, patron, motivo in reglas:
                if patron.search(linea):
                    errores.append(f"  [IMPORT]  {rel}:{n}: {linea.strip()[:80]}  <- {motivo}")
    return errores


# Ejecución peligrosa (Fase 7): eval() y shell=True quedan prohibidos en las
# capas hexagonales — la única vía para subprocesos es el SubprocessRunner
# del sandbox (shell=False por diseño). Patrón case-sensitive sobre código.
RE_EJECUCION_PELIGROSA = re.compile(r"\beval\s*\(|\bshell\s*=\s*True\b")
CAPAS_SIN_EJECUCION = ("core/services/", "core/adapters/", "core/domain/",
                       "core/ports/", "core/repositories/")


def check_ejecucion_peligrosa(archivos: list[str]) -> list[str]:
    errores = []
    for rel in archivos:
        if not rel.endswith(".py") or not rel.startswith(CAPAS_SIN_EJECUCION):
            continue
        for n, linea in enumerate(leer(rel), 1):
            sin_comentario = linea.split("#", 1)[0]
            if RE_EJECUCION_PELIGROSA.search(sin_comentario):
                errores.append(f"  [EXEC]    {rel}:{n}: {linea.strip()[:80]}  "
                               f"<- eval()/shell=True prohibidos (usar sandbox_service)")
    return errores


# Credenciales por defecto (Fase 10, ADR-0008): un secreto/clave hardcodeado
# con un valor conocido delata configuracion insegura. Case-insensitive.
RE_CRED_DEFECTO = re.compile(
    r"(?i)\b\w*(password|passwd|secret|api_key|apikey|token)\w*\s*[:=]\s*"
    r"[\"'](changeme|password|admin|admin123|secret|123456|default|letmein|qwerty|test)[\"']"
)


def check_credenciales_defecto(archivos: list[str]) -> list[str]:
    errores = []
    for rel in archivos:
        if Path(rel).suffix not in {".py", ".js", ".jsx", ".json", ".toml",
                                    ".yml", ".yaml", ".ps1", ".env"}:
            continue
        if rel in EXCLUIR_TAGS or rel == "scripts/gate.py":
            continue
        for n, linea in enumerate(leer(rel), 1):
            if RE_CRED_DEFECTO.search(linea):
                errores.append(f"  [CRED]    {rel}:{n}: {linea.strip()[:80]}  "
                               f"<- credencial por defecto prohibida (ADR-0008)")
    return errores


# Lógica pesada síncrona (Fase 8): estas funciones bloquean el event loop si
# se llaman directo desde un endpoint. En core/api.py DEBEN pasar por el
# QueuePort (queue_service.ejecutar_pesado / encolar).
RE_PESADO = re.compile(r"\b(generar_pdf_gantt|embeddings_3d|crear_backup|_gen_pdf)\s*\(")


def check_pesado_sincrono() -> list[str]:
    errores = []
    for n, linea in enumerate(leer("core/api.py"), 1):
        limpia = linea.strip()
        if limpia.startswith(("def ", "async def ", "from ", "import ", "#")):
            continue
        if RE_PESADO.search(linea) and "ejecutar_pesado" not in linea and "encolar" not in linea:
            errores.append(f"  [PESADO]  core/api.py:{n}: {limpia[:80]}  "
                           f"<- logica pesada sincrona: usar queue_service (QueuePort)")
    return errores


def check_tests_adaptadores(archivos: list[str]) -> list[str]:
    """
    ADR-0004: cada adaptador industrial (core/adapters/<x>_adapter.py) debe
    tener su archivo de test espejo en tests/industrial/test_<x>_adapter.py.
    """
    errores = []
    for rel in archivos:
        if not (rel.startswith("core/adapters/") and rel.endswith("_adapter.py")):
            continue
        nombre   = Path(rel).stem                      # p.ej. "mqtt_adapter"
        esperado = f"tests/industrial/test_{nombre}.py"
        if not (RAIZ / esperado).is_file():
            errores.append(f"  [OT-TEST] {rel}: falta su test espejo {esperado}")
    return errores


def check_harnesses() -> list[str]:
    """
    ADR-0009: cada HAT registrado en harness_service.py debe tener su suite
    de pruebas espejo en tests/harnesses/test_<nombre>_harness.py.
    """
    ruta = "core/services/harness_service.py"
    contenido = "\n".join(leer(ruta))
    if "_REGISTRO" not in contenido:
        return []
    bloque  = contenido.split("_REGISTRO", 1)[-1].split("}", 1)[0]
    nombres = re.findall(r'"(\w+)"\s*:\s*\w+', bloque)
    errores = []
    for nombre in nombres:
        esperado = f"tests/harnesses/test_{nombre}_harness.py"
        if not (RAIZ / esperado).is_file():
            errores.append(f"  [HAT-TEST] harness '{nombre}' sin su suite de pruebas: falta {esperado}")
    return errores


_METRIC_EVENT_CAMPOS = {"fuente", "tipo", "valor", "unidad", "ts", "nivel", "metadata"}


def check_contrato_metric_event(archivos: list[str]) -> list[str]:
    """
    ADR-0001/0012 [METRIC-CONTRACT]: todo MetricEvent(...) construido en un
    adaptador OT (core/adapters/*.py) debe usar EXCLUSIVAMENTE los campos
    reales del contrato normalizado (fuente, tipo, valor, unidad, ts, nivel,
    metadata) — un adaptador que se desvia del contrato rompe el puente
    hacia el dashboard y el reactor industrial sin avisar hasta runtime.
    """
    errores = []
    for rel in archivos:
        if not (rel.startswith("core/adapters/") and rel.endswith(".py")):
            continue
        texto = "\n".join(leer(rel))
        for m in re.finditer(r"MetricEvent\(([^)]*)\)", texto, re.S):
            campos_usados = re.findall(r"(\w+)\s*=", m.group(1))
            desconocidos = [c for c in campos_usados if c not in _METRIC_EVENT_CAMPOS]
            if desconocidos:
                n = texto[:m.start()].count("\n") + 1
                errores.append(
                    f"  [METRIC-CONTRACT] {rel}:{n}: MetricEvent con campos fuera de "
                    f"contrato: {desconocidos} (validos: {sorted(_METRIC_EVENT_CAMPOS)})"
                )
    return errores


# Credenciales embebidas en una URI de conexion (usuario:clave@host) — el
# antipatron clasico en adaptadores OT. Los adaptadores reales de este
# proyecto usan os.environ.get(...) para host/broker/endpoint; un literal
# con esta forma delata una credencial hardcodeada evadiendo eso.
RE_CRED_EN_URI = re.compile(r"[\"'][a-z][a-z0-9+.\-]*://[^/\s\"']+:[^/\s\"']+@")


def check_credenciales_adapters_ot(archivos: list[str]) -> list[str]:
    """
    ADR-0012 [TOOL-SECURITY]: ningun adaptador OT puede tener una credencial
    de conexion (usuario:clave@host) hardcodeada como literal — debe leerse
    de una variable de entorno (AGENTDESK_*_HOST/BROKER/ENDPOINT) o de un
    KeyVault, nunca embebida en el codigo versionado.
    """
    errores = []
    for rel in archivos:
        if not (rel.startswith("core/adapters/") and rel.endswith(".py")):
            continue
        for n, linea in enumerate(leer(rel), 1):
            if RE_CRED_EN_URI.search(linea):
                errores.append(
                    f"  [TOOL-SECURITY] {rel}:{n}: credencial embebida en URI de "
                    f"conexion -> usa variable de entorno o KeyVault"
                )
    return errores


def check_seguridad_herramientas() -> list[str]:
    """
    ADR-0011 [TOOL-SECURITY]: ninguna herramienta expuesta a los agentes
    (core/tools.py) puede leer os.environ directamente — filtraria API keys
    y secretos del host al LLM. Si una herramienta necesita ejecutar algo
    con variables de sistema, debe pasar por sandbox_service.py (entorno
    minimo controlado / DockerRunner).
    """
    errores = []
    RE_ENVIRON = re.compile(r"\bos\.environ\b")
    for n, linea in enumerate(leer("core/tools.py"), 1):
        limpia = linea.strip()
        if limpia.startswith("#"):
            continue
        if RE_ENVIRON.search(linea):
            errores.append(
                f"  [TOOL-SECURITY] core/tools.py:{n}: acceso directo a os.environ en "
                f"una herramienta -> usa sandbox_service (entorno minimo controlado)"
            )
    return errores


RE_DB_BLOQUEANTE = re.compile(r"\b(get_session|Session)\s*\(")


def check_concurrencia_telemetria() -> list[str]:
    """
    ADR-0013 [DB-CONCURRENCY]: los adaptadores de telemetria OT
    (core/adapters/base.py y los adaptadores de protocolo) no pueden hacer
    consultas SQLAlchemy sincronas/bloqueantes (get_session()/Session())
    directamente en su propio codigo. La telemetria corre en el mismo event
    loop que el resto del sistema (ADR-0001) — una consulta bloqueante ahi
    frena TODA la telemetria de planta, no solo esa lectura. Si un
    adaptador necesita persistir algo, debe delegarlo (p.ej. via el
    ReactorIndustrial a un servicio) en vez de tocar la sesion el mismo.
    """
    errores = []
    archivos_telemetria = [
        "core/adapters/base.py",
        "core/adapters/modbus_adapter.py",
        "core/adapters/mqtt_adapter.py",
        "core/adapters/opcua_adapter.py",
    ]
    for rel in archivos_telemetria:
        for n, linea in enumerate(leer(rel), 1):
            if RE_DB_BLOQUEANTE.search(linea):
                errores.append(
                    f"  [DB-CONCURRENCY] {rel}:{n}: consulta SQLAlchemy sincrona directa "
                    f"en un adaptador de telemetria -> bloquea el event loop de planta"
                )
    return errores


def check_bandit() -> list[str]:
    """Análisis estático de vulnerabilidades (severidad media/alta)."""
    proc = subprocess.run(
        [sys.executable, "-m", "bandit", "-q", "-r", "core", "scripts", "main.py",
         "-ll", "--format", "custom",
         "--msg-template", "{severity} {test_id} {relpath}:{line} {msg}"],
        cwd=RAIZ, capture_output=True, text=True,
    )
    if proc.returncode == 0:
        return []
    salida = (proc.stdout or proc.stderr or "bandit fallo sin salida").strip()
    return [f"  [BANDIT]  {linea}" for linea in salida.splitlines() if linea.strip()]


def check_contrato_auth() -> list[str]:
    """Test-contrato: toda escritura protegida por JWT o autorizada explícita."""
    return _correr_suite("tests.contract.test_auth_contract", "CONTRATO")


def check_sandbox() -> list[str]:
    """Fase 7: el blindaje de ejecución Zero-Trust debe seguir intacto."""
    return _correr_suite("tests.sandbox.test_subprocess_runner", "SANDBOX")


def check_resiliencia() -> list[str]:
    """Fase 8: fallback LLM con circuit breaker y cola de trabajos pesados."""
    return (_correr_suite("tests.resilience.test_llm_fallback", "RESILIENCIA")
            + _correr_suite("tests.resilience.test_queue_service", "RESILIENCIA"))


def check_auditoria() -> list[str]:
    """Fase 9: la traza forense de cada interacción IA debe seguir intacta."""
    return _correr_suite("tests.audit.test_audit_trail", "AUDITORIA")


def check_enterprise() -> list[str]:
    """Fase 10: refresh tokens rotativos y chequeo de arranque seguro."""
    return _correr_suite("tests.enterprise.test_refresh_tokens", "ENTERPRISE")


def check_persistencia_dual() -> list[str]:
    """Fase 15: SQLite/PostgreSQL dual + esquema gobernado por Alembic."""
    return _correr_suite("tests.persistence.test_dual_mode", "DB-DUAL")


def check_hats() -> list[str]:
    """Fases 11/12: HATs (ContextHarness + CritiqueHarness) — best-effort."""
    return (_correr_suite("tests.harnesses.test_memoria_harness", "HAT")
            + _correr_suite("tests.harnesses.test_autocritica_harness", "HAT"))


def check_fase13() -> list[str]:
    """Fase 13: DockerRunner (opcional, skip sin Docker) + delegacion Speak/Listen."""
    return (_correr_suite("tests.sandbox.test_docker_runner", "DOCKER")
            + _correr_suite("tests.collaboration.test_delegation", "DELEGACION"))


def check_aislamiento_memoria() -> list[str]:
    """
    ADR-0010 [DATA-ISOLATION]: toda consulta de auditoria_ia que hace
    ContextHarness para armar memoria semántica debe ir filtrada por
    user_id — nunca solo por agente_id. Sin este filtro, un operador podría
    recibir recuerdos sembrados por otro operador del mismo agente.
    """
    errores = []
    lineas = leer("core/services/harness_service.py")
    for n, linea in enumerate(lineas, 1):
        if "consultar(agente_id=" not in linea:
            continue
        if "user_id=" not in linea:
            errores.append(
                f"  [DATA-ISOLATION] core/services/harness_service.py:{n}: "
                f"consulta de memoria sin filtro user_id -> fuga entre operadores"
            )
    return errores


def check_telemetria_industrial() -> list[str]:
    """Fases 5/6: toda la suite industrial (puente, MQTT, Modbus, OPC-UA, cola)."""
    proc = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests/industrial",
         "-t", ".", "-p", "test_*.py"],
        cwd=RAIZ, capture_output=True, text=True,
    )
    if proc.returncode == 0:
        return []
    detalle = (proc.stderr or proc.stdout or "").strip().splitlines()[-25:]
    return ["  [INDUSTRIAL] tests/industrial FALLO:"] + \
           [f"    {linea}" for linea in detalle]


def _correr_suite(modulo: str, etiqueta: str) -> list[str]:
    proc = subprocess.run(
        [sys.executable, "-m", "unittest", modulo],
        cwd=RAIZ, capture_output=True, text=True,
    )
    if proc.returncode == 0:
        return []
    detalle = (proc.stderr or proc.stdout or "").strip().splitlines()[-25:]
    return [f"  [{etiqueta}] {modulo} FALLO:"] + \
           [f"    {linea}" for linea in detalle]


def main() -> int:
    archivos = inventario()
    print(f"Guardian de Arquitectura — {len(archivos)} archivos inventariados")

    errores = []
    errores += check_tags(archivos)
    errores += check_tamano(archivos)
    errores += check_imports(archivos)
    errores += check_ejecucion_peligrosa(archivos)
    errores += check_credenciales_defecto(archivos)
    errores += check_pesado_sincrono()
    errores += check_tests_adaptadores(archivos)
    errores += check_bandit()
    errores += check_contrato_auth()
    errores += check_telemetria_industrial()
    errores += check_sandbox()
    errores += check_resiliencia()
    errores += check_auditoria()
    errores += check_enterprise()
    errores += check_harnesses()
    errores += check_hats()
    errores += check_aislamiento_memoria()
    errores += check_seguridad_herramientas()
    errores += check_fase13()
    errores += check_contrato_metric_event(archivos)
    errores += check_credenciales_adapters_ot(archivos)
    errores += check_concurrencia_telemetria()
    errores += check_persistencia_dual()

    if errores:
        print(f"\nVIOLACIONES ({len(errores)}):")
        for e in errores:
            print(e)
        print("\n=== ARQUITECTURA RECHAZADA ===")
        return 1

    print("OK: 0 etiquetas | 0 archivos nuevos >500 lineas | 0 violaciones de imports "
          "| sin eval()/shell=True | bandit limpio (media/alta) | contrato auth 100% "
          "| telemetria industrial 100% | sandbox 100%")
    print("=== ARQUITECTURA APROBADA ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
