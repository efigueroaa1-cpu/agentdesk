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

import os
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
    # SecurityPanel subio 898->1413 (2026-07-17, ADR-0022): normalizacion
    # prettier (nunca habia pasado por el linter) + seccion licencia RSA
    "agentdesk-dashboard/src/components/settings/SecurityPanel.jsx":    1413,
    # core/api.py (2865->1552 lineas, ADR-0003/0007/0011/0014) se retiro de
    # esta tabla en la Fase 17 (ADR-0015): dejo de ser un archivo unico y
    # paso a ser el paquete core/api/ (un router por dominio, cada archivo
    # nuevo nace bajo MAX_LINEAS por diseno — ver check_pesado_sincrono()
    # mas abajo, que ahora recorre todo el paquete en vez de un solo archivo).
    # orchestrator subio 1215->1223 (2026-07-14): hook del sandbox Zero-Trust
    # subio 1223->1242 (2026-07-15, ADR-0009): self.harnesses + inyeccion del
    # contexto de HATs (_contexto_harnesses) en las 4 rutas de chat
    # subio 1242->1269 (2026-07-15, ADR-0010): user_id enhebrado en las 4
    # rutas de chat (aislamiento de memoria) + _criticar_respuesta wireado
    # en chat_libre/chat_con_herramientas (CritiqueHarness post-hook)
    # subio 1269->1277 (2026-07-15, ADR-0011): agente_id_clave/user_id
    # enhebrados en los 4 call sites de ejecutar_herramienta (delegacion)
    # subio 1277->1288 (2026-07-15, ADR-0014): spans OTEL en chat_libre
    # (llm.generar) + canal lateral ultimo_contexto_hats para auditoria
    # subio 1288->1325 (2026-07-16, ADR-0017): chat_libre/realizar_tarea
    # cableados a llm_service.generar() (cadena de resiliencia real, en vez
    # de core.providers.generate directo); gate de circuit breaker antes
    # del loop de tool-calling nativo en chat_con_herramientas; canales
    # laterales ultimo_proveedor_llm/ultimo_tokens_llm
    "core/orchestrator.py":                                             1325,
    # tools.py subio 1120->1153 (2026-07-14): evaluador AST que reemplaza eval()
    # subio 1153->1209 (2026-07-15, ADR-0011): tool consultar_a_otro_agente
    # + set_orquestador() (delegacion cognitiva Speak/Listen)
    # subio 1209->1217 (2026-07-15, ADR-0014): span OTEL tool.ejecutar
    # envolviendo el dispatcher (_despachar_herramienta)
    # subio 1217->1282 (2026-07-17, ADR-0024): herramienta proponer_comando_ot
    # (schema + dispatch + impl — el agente PROPONE, jamas ejecuta)
    "core/tools.py":                                                    1282,
    # web_monitor.py subio 593->595 (2026-07-14): validacion de esquema http(s)
    "core/web_monitor.py":                                               595,
    # database.py subio 495->580 (2026-07-15, ADR-0013): migraciones Alembic
    # (_aplicar_migraciones) + chequeo async de conexion Postgres con
    # asyncpg (_verificar_conexion_async) antes de armar el engine sincrono
    # subio 580->584 (2026-07-15, ADR-0014): contexto_hats + guardrails_json
    # en AuditoriaIA (auditoria forense completa)
    # subio 584->601 (2026-07-16, ADR-0016): comentario extenso documentando
    # el hallazgo real de Fase 18 (StaticPool corrompia el cursor entre
    # hilos bajo escritura concurrente real; retirado) + PRAGMA busy_timeout
    # subio 601->605 (2026-07-16, ADR-0017): columnas tokens_exactos +
    # costo_usd_estimado en AuditoriaIA (FinOps IA)
    "core/database.py":                                                  605,
    # gate.py mismo: crecio organicamente con cada fase (14 reglas nuevas
    # entre Fase 11 y 16). Se acepta el tamano del propio Guardian en vez
    # de partirlo artificialmente entre fases activas.
    # subio 590->642 (2026-07-16, ADR-0016): regla [BOOT-VALIDATION]
    # subio 642->700 (2026-07-16, ADR-0017): regla [LLM-RESILIENCE]
    # subio 700->748 (2026-07-16, ADR-0018): regla [DATA-HYGIENE]
    # subio 748->798 (2026-07-16, ADR-0019): regla [SCALE-LIMITS]
    # subio 798->808 (2026-07-16, ADR-0019): check_escalabilidad() (suite scale/)
    # subio 808->868 (2026-07-17, ADR-0021): regla [INDUSTRIAL-INTEGRITY]
    # (validacion AST de rangos fisicos en catalogos SENSORES)
    # subio 868->978 (2026-07-17, ADR-0022): regla [DIST-INTEGRITY] (self-check
    # RSA + escaneo de control externo en fuente y binario) + check_onboarding
    # subio 978->1045 (2026-07-17, ADR-0023): regla [SEMANTIC-PRIVACY] (scope
    # user_id+proyecto_id en llamadas Hermes por AST de parentesis) + suite memory
    # subio 1045->1110 (2026-07-17, ADR-0024): regla [INDUSTRIAL-ACTION]
    # (limites fisicos de escritura + filtro determinista + RBAC en /ot/)
    # subio 1110->1154 (2026-07-17, ADR-0025): regla [INTENT-SAFETY]
    # (el Copiloto propone, jamas ejecuta; filtro obligatorio + suite intent)
    "scripts/gate.py":                                                  1154,
    "dashboard.py":                                                     1257,
    "ui/dashboard.py":                                                  1257,
    # providers.py subio de <500 a 528 (2026-07-16, ADR-0017): generate_con_uso()
    # + extraccion de tokens reales (usage) por cada uno de los 5 proveedores
    # (Gemini/OpenAI/DeepSeek/Anthropic/Groq) para la auditoria FinOps
    # subio 528->604 (2026-07-16, ADR-0018): adaptador Ollama/LM Studio
    # (_ollama/_ollama_stream, OpenAI-compatible local) para soberania de datos
    "core/providers.py":                                                 604,
}

# Reglas de capas (ADR-0002/0004): prefijo de carpeta -> imports prohibidos.
# Desde la Fase 17 (ADR-0015) core/api es un paquete (core/api/_state.py,
# core/api/schemas.py, core/api/*_router.py); \b tras "api" ya cubre
# core.api._state, core.api.schemas, core.api.agentes_router, etc. — ningun
# submodulo del paquete api es importable desde domain/ports/services/
# repositories/adapters.
CAPA_API = re.compile(r"^\s*(from|import)\s+core\.api\b")
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
# se llaman directo desde un endpoint. En el paquete core/api/ (Fase 17,
# ADR-0015 — antes un unico core/api.py) DEBEN pasar por el QueuePort
# (queue_service.ejecutar_pesado / encolar), sin importar en que router vivan.
RE_PESADO = re.compile(r"\b(generar_pdf_gantt|embeddings_3d|crear_backup|_gen_pdf)\s*\(")


def check_pesado_sincrono(archivos: list[str]) -> list[str]:
    errores = []
    for rel in archivos:
        if not (rel.startswith("core/api/") and rel.endswith(".py")):
            continue
        for n, linea in enumerate(leer(rel), 1):
            limpia = linea.strip()
            if limpia.startswith(("def ", "async def ", "from ", "import ", "#")):
                continue
            if RE_PESADO.search(linea) and "ejecutar_pesado" not in linea and "encolar" not in linea:
                errores.append(f"  [PESADO]  {rel}:{n}: {limpia[:80]}  "
                               f"<- logica pesada sincrona: usar queue_service (QueuePort)")
    return errores


# Diagnostico de Arranque Enterprise (Fase 18, ADR-0016): el chequeo
# Fail-Hard solo protege al sistema si CORRE de verdad antes de levantar el
# servidor. Un refactor futuro de main.py podria mover/borrar la llamada
# sin que ningun test lo note (nada del arranque real corre en la suite de
# tests). Esta regla exige que el punto de entrada real siga invocando el
# servicio unificado.
_RUTA_ENTRYPOINT = "main.py"


def check_boot_validation() -> list[str]:
    """
    ADR-0016 [BOOT-VALIDATION]: main.py debe importar y llamar a
    diagnostico_arranque_sistema() (core/services/boot_diagnostics_service.py)
    Y el resultado debe seguir gobernando un sys.exit ante criticos — de lo
    contrario el Fail-Hard queda "instalado" pero nunca se ejecuta.
    """
    errores = []
    texto = "\n".join(leer(_RUTA_ENTRYPOINT))
    if not texto.strip():
        return [f"  [BOOT-VALIDATION] {_RUTA_ENTRYPOINT}: no se pudo leer el punto de entrada"]

    tiene_import = bool(re.search(
        r"from\s+core\.services\.boot_diagnostics_service\s+import\s+diagnostico_arranque_sistema",
        texto,
    ))
    tiene_llamada = bool(re.search(r"\bdiagnostico_arranque_sistema\s*\(", texto))
    tiene_fail_hard = bool(re.search(r'\["criticos"\]', texto)) and "sys.exit" in texto

    if not tiene_import:
        errores.append(
            f"  [BOOT-VALIDATION] {_RUTA_ENTRYPOINT}: no importa "
            f"diagnostico_arranque_sistema desde boot_diagnostics_service "
            f"-> el Fail-Hard de ADR-0016 no esta conectado al arranque real"
        )
    if not tiene_llamada:
        errores.append(
            f"  [BOOT-VALIDATION] {_RUTA_ENTRYPOINT}: diagnostico_arranque_sistema() "
            f"nunca se invoca -> declarado pero no ejecutado"
        )
    if tiene_import and tiene_llamada and not tiene_fail_hard:
        errores.append(
            f"  [BOOT-VALIDATION] {_RUTA_ENTRYPOINT}: se invoca el diagnostico pero "
            f"no se ve un sys.exit gobernado por sus 'criticos' -> el resultado "
            f"se calcula y se ignora, no es Fail-Hard de verdad"
        )
    return errores


# LLM sin resiliencia (Fase 19, ADR-0017): generate() es una llamada CRUDA
# a un unico proveedor, sin circuit breaker ni fallback. \bgenerate\b NO
# matchea "generate_stream"/"generate_con_uso" (serian "generate_" con un
# caracter de palabra pegado, sin limite de palabra ahi) -- streaming queda
# fuera a proposito (limitacion documentada en el ADR: no se puede
# "des-enviar" texto ya emitido al cliente, mismo patron que la exclusion
# de streaming del CritiqueHarness en ADR-0010).
RE_LLM_SIN_RESILIENCIA = re.compile(
    r"from\s+core\.providers\s+import\s+[\w\s,]*\bgenerate\b(?!_)"
    r"|\bproviders\.generate\("
)
# Archivos donde una llamada cruda a generate() es legitima: providers.py
# la define y generate() internamente llama a generate_con_uso(); el
# propio llm_service.py es el envoltorio de resiliencia (usa
# generate_con_uso, nunca generate a secas, pero se excluye por claridad).
_LLM_RESILIENCIA_EXCLUIDOS = {"core/providers.py", "core/services/llm_service.py"}


def check_llm_resilience(archivos: list[str]) -> list[str]:
    """
    ADR-0017 [LLM-RESILIENCE]: ninguna llamada al LLM fuera de
    core/services/llm_service.py (el envoltorio de circuit breaker +
    cadena de fallback) — un import o llamada directa a
    core.providers.generate() se salta el circuit breaker por completo,
    exactamente el hallazgo real que motivo esta fase (core/orchestrator.py
    llamaba generate() directo, dejando la cadena de resiliencia de la
    Fase 8 desconectada del chat real de los agentes).
    """
    errores = []
    for rel in archivos:
        if not (rel.startswith("core/") and rel.endswith(".py")):
            continue
        if rel in _LLM_RESILIENCIA_EXCLUIDOS:
            continue
        for n, linea in enumerate(leer(rel), 1):
            sin_comentario = linea.split("#", 1)[0]
            if RE_LLM_SIN_RESILIENCIA.search(sin_comentario):
                errores.append(
                    f"  [LLM-RESILIENCE] {rel}:{n}: {linea.strip()[:80]}  "
                    f"<- llamada al LLM sin circuit breaker: usar "
                    f"llm_service.generar() (core/services/llm_service.py)"
                )
    return errores


# Higiene de datos (Fase 20, ADR-0018): la politica de retencion/purga solo
# protege la privacidad de sectores regulados si CORRE de verdad en el
# arranque real -- mismo patron de riesgo que [BOOT-VALIDATION]: declarar
# purgar_registros_antiguos()/iniciar_monitor_purga() sin registrarlas como
# tarea de fondo del servidor real las deja "instaladas" pero inertes.
_RUTA_STARTUP_API = "core/api/__init__.py"


def check_data_hygiene() -> list[str]:
    """
    ADR-0018 [DATA-HYGIENE]: core/api/__init__.py debe importar y arrancar
    el monitor de purga de retencion (audit_service.iniciar_monitor_purga)
    como tarea de fondo real del servidor -- no solo debe existir la
    funcion en audit_service.py.
    """
    errores = []
    texto = "\n".join(leer(_RUTA_STARTUP_API))
    if not texto.strip():
        return [f"  [DATA-HYGIENE] {_RUTA_STARTUP_API}: no se pudo leer el arranque del servidor"]

    tiene_import = bool(re.search(
        r"from\s+core\.services\.audit_service\s+import\s+iniciar_monitor_purga",
        texto,
    ))
    tiene_tarea = bool(re.search(
        r"asyncio\.create_task\s*\(\s*_?iniciar_monitor_purga\s*\(",
        texto,
    ))

    if not tiene_import:
        errores.append(
            f"  [DATA-HYGIENE] {_RUTA_STARTUP_API}: no importa "
            f"iniciar_monitor_purga desde audit_service -> la politica de "
            f"retencion de ADR-0018 no esta conectada al arranque real"
        )
    if not tiene_tarea:
        errores.append(
            f"  [DATA-HYGIENE] {_RUTA_STARTUP_API}: iniciar_monitor_purga() "
            f"nunca se arranca como asyncio.create_task -> declarado pero "
            f"no ejecutado en background"
        )
    return errores


# Escalabilidad Enterprise (Fase 21, ADR-0019): toda funcion que ya se
# despacha via queue_service.ejecutar_pesado()/encolar() (la misma lista de
# nombres que RE_PESADO/check_pesado_sincrono vigila desde el lado del
# llamador, mas la funcion Reduce del Map-Reduce nuevo) debe declarar su
# costo de recursos estimado -- sin esa metadata, dimensionar cuantos
# workers reales hacen falta antes de activar Queue Mode distribuido en
# produccion es puro tanteo.
FUNCIONES_PESADAS_CON_COSTO = {
    "generar_pdf_gantt", "embeddings_3d", "crear_backup", "generar_pdf",
    "_reducir_resultados",
}


def check_scale_limits(archivos: list[str]) -> list[str]:
    """
    ADR-0019 [SCALE-LIMITS]: cada funcion pesada despachada via QueuePort
    debe llevar el decorador @costo_recursos(cpu=..., memoria=...)
    (core/services/resource_guard.py) inmediatamente antes de su def.
    """
    errores = []
    for rel in archivos:
        if not (rel.startswith("core/") and rel.endswith(".py")):
            continue
        # core/api/* son endpoints (adaptador HTTP) -- pueden coincidir de
        # nombre por casualidad con la funcion pesada real que despachan via
        # queue_service (p.ej. el endpoint async def generar_pdf(payload)
        # vs. la funcion sincrona core.report_generator.generar_pdf que
        # realmente hace el trabajo). El costo se declara donde vive el
        # trabajo, no en el adaptador que lo despacha.
        if rel.startswith("core/api/"):
            continue
        lineas = leer(rel)
        for n, linea in enumerate(lineas, 1):
            m = re.match(r"\s*(?:async\s+)?def\s+(\w+)\s*\(", linea)
            if not m or m.group(1) not in FUNCIONES_PESADAS_CON_COSTO:
                continue
            # @costo_recursos( puede estar hasta 3 lineas antes (permite
            # decoradores intercalados, p.ej. @staticmethod).
            precedentes = lineas[max(0, n - 4):n - 1]
            if not any("@costo_recursos(" in l for l in precedentes):
                errores.append(
                    f"  [SCALE-LIMITS] {rel}:{n}: def {m.group(1)}(...)  "
                    f"<- funcion pesada sin @costo_recursos(cpu=..., memoria=...) "
                    f"(core/services/resource_guard.py)"
                )
    return errores


# Integridad industrial (Fase 23, ADR-0021): el Gemelo Digital razona sobre
# la telemetria de planta — un sensor mapeado SIN rango de validez fisica
# deja pasar lecturas imposibles (payload malicioso o sensor roto) como si
# fueran datos legitimos: data poisoning directo a la Curva S ajustada y a
# las alertas financieras. Los catalogos SENSORES son listas de literales,
# asi que se validan por AST (preciso), no por regex.
def check_industrial_integrity(archivos: list[str]) -> list[str]:
    """
    ADR-0021 [INDUSTRIAL-INTEGRITY]: todo sensor de un catalogo SENSORES
    (core/adapters/*.py) debe declarar min_fisico y max_fisico validos
    (min < max, numericos) — y base.py debe seguir aplicandolos.
    """
    import ast as _ast
    errores = []
    for rel in archivos:
        if not (rel.startswith("core/adapters/") and rel.endswith(".py")):
            continue
        try:
            arbol = _ast.parse("\n".join(leer(rel)))
        except SyntaxError:
            continue
        for nodo in _ast.walk(arbol):
            if not (isinstance(nodo, (_ast.Assign, _ast.AnnAssign))):
                continue
            objetivos = nodo.targets if isinstance(nodo, _ast.Assign) else [nodo.target]
            if not any(isinstance(t, _ast.Name) and t.id == "SENSORES" for t in objetivos):
                continue
            if nodo.value is None or not isinstance(nodo.value, _ast.List):
                continue
            try:
                sensores = _ast.literal_eval(nodo.value)
            except ValueError:
                continue
            for s in sensores:
                sid = s.get("id", "?")
                minf, maxf = s.get("min_fisico"), s.get("max_fisico")
                if not isinstance(minf, (int, float)) or not isinstance(maxf, (int, float)):
                    errores.append(
                        f"  [INDUSTRIAL-INTEGRITY] {rel}: sensor '{sid}' sin "
                        f"min_fisico/max_fisico numericos -> data poisoning "
                        f"posible en el Gemelo Digital (ADR-0021)"
                    )
                elif minf >= maxf:
                    errores.append(
                        f"  [INDUSTRIAL-INTEGRITY] {rel}: sensor '{sid}' con rango "
                        f"fisico invalido (min {minf} >= max {maxf})"
                    )
    texto_base = "\n".join(leer("core/adapters/base.py"))
    if "min_fisico" not in texto_base or "fuera_de_rango_fisico" not in texto_base:
        errores.append(
            "  [INDUSTRIAL-INTEGRITY] core/adapters/base.py: la validacion de "
            "rango fisico (min_fisico -> fuera_de_rango_fisico) fue removida "
            "-> los rangos declarados no se aplican a ninguna lectura real"
        )
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


# Servicios/puertos existentes al momento de esta regla (2026-07-15, ADR-0014)
# — grandfathered: no se les exige instrumentar retroactivamente. Todo
# archivo NUEVO en core/services/ o core/ports/ que no este aqui debe
# referenciar telemetry_otel o metrics_prometheus.
SERVICIOS_PORTS_GRANDFATHERED = {
    "core/ports/agent_port.py", "core/ports/auth_port.py", "core/ports/cognitive_port.py",
    "core/ports/harness_port.py", "core/ports/orchestrator_port.py", "core/ports/pipeline_port.py",
    "core/ports/queue_port.py", "core/ports/telemetry_port.py",
    "core/services/agent_service.py", "core/services/analytics_service.py",
    "core/services/audit_service.py", "core/services/auth_service.py",
    "core/services/delegation_service.py", "core/services/gantt_report_service.py",
    "core/services/harness_service.py", "core/services/insights_service.py",
    "core/services/llm_service.py", "core/services/orchestrator_service.py",
    "core/services/pipeline_service.py", "core/services/queue_service.py",
    "core/services/report_service.py", "core/services/sandbox_service.py",
    "core/services/upload_service.py",
}


def check_observabilidad(archivos: list[str]) -> list[str]:
    """
    ADR-0014 [OBSERVABILITY]: todo servicio o puerto NUEVO (core/services/,
    core/ports/) debe incluir trazas de telemetria basicas — referenciar
    core.telemetry_otel o core.metrics_prometheus. Los archivos existentes
    a la fecha de esta regla quedan grandfathered (no se instrumentan
    retroactivamente en este pase).
    """
    errores = []
    for rel in archivos:
        es_servicio_o_puerto = (
            (rel.startswith("core/services/") or rel.startswith("core/ports/"))
            and rel.endswith(".py") and not rel.endswith("__init__.py")
        )
        if not es_servicio_o_puerto or rel in SERVICIOS_PORTS_GRANDFATHERED:
            continue
        texto = "\n".join(leer(rel))
        if "telemetry_otel" not in texto and "metrics_prometheus" not in texto:
            errores.append(
                f"  [OBSERVABILITY] {rel}: servicio/puerto nuevo sin trazas de "
                f"telemetria -> referenciar core.telemetry_otel o core.metrics_prometheus"
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


def check_escalabilidad() -> list[str]:
    """Fase 21: Queue Mode (deteccion de broker), Circuit Breaker de
    Concurrencia y orquestacion paralela Map-Reduce."""
    return (_correr_suite("tests.scale.test_queue_broker_detection", "ESCALABILIDAD")
            + _correr_suite("tests.scale.test_resource_guard", "ESCALABILIDAD")
            + _correr_suite("tests.scale.test_map_reduce", "ESCALABILIDAD"))


def check_enterprise() -> list[str]:
    """Fase 10: refresh tokens rotativos y chequeo de arranque seguro."""
    return _correr_suite("tests.enterprise.test_refresh_tokens", "ENTERPRISE")


def check_persistencia_dual() -> list[str]:
    """Fase 15: SQLite/PostgreSQL dual + esquema gobernado por Alembic."""
    return _correr_suite("tests.persistence.test_dual_mode", "DB-DUAL")


def check_observabilidad_forense() -> list[str]:
    """Fase 16: tracing OTEL, /metrics Prometheus y auditoria forense completa."""
    return _correr_suite("tests.observability.test_otel_and_forensics", "OBSERVABILITY")


def check_hats() -> list[str]:
    """Fases 11/12: HATs (ContextHarness + CritiqueHarness) — best-effort."""
    return (_correr_suite("tests.harnesses.test_memoria_harness", "HAT")
            + _correr_suite("tests.harnesses.test_autocritica_harness", "HAT")
            + _correr_suite("tests.harnesses.test_habilidades_harness", "HAT"))


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


# Integridad de distribucion (Fase 24, ADR-0022): la v1.0 Gold no puede
# depender de recursos externos criticos. El kill switch por Gist era una
# URL de control externa (punto unico de falla); la licencia RSA local la
# reemplaza. Esta regla impide que el patron reaparezca — en el fuente o
# ya compilado dentro del binario distribuido — y exige que la cadena
# criptografica de licencias funcione de verdad (self-check real, no lint).
_PATRONES_CONTROL_EXTERNO = ("KILL_SWITCH_GIST_URL", "gist.githubusercontent")


def check_distribution_integrity(archivos: list[str]) -> list[str]:
    """
    ADR-0022 [DISTRIBUTION-INTEGRITY]:
      1. Cero URLs de control externas: ningun archivo fuente puede
         contener los patrones del mecanismo remoto retirado, y
         core/kill_switch.py no puede volver a hacer red (urllib/httpx/
         requests/socket prohibidos en ese modulo).
      2. Self-check RSA real: par efimero -> firmar -> validar OK;
         payload adulterado -> firma_invalida. Si la cadena de licencias
         se rompe, el build no sale.
      3. Si dist/AgentDesk/AgentDesk.exe existe, escanea el binario (cubre
         recursos/config en claro; los .py viajan comprimidos en el PYZ —
         la garantia dura es el escaneo de fuente + el self-check).
    """
    errores = []

    # 1) Fuente sin patrones de control externo (este archivo se excluye:
    #    define los patrones que busca)
    for ruta in archivos:
        if ruta.replace("\\", "/").endswith("scripts/gate.py"):
            continue
        for n, linea in enumerate(leer(ruta), 1):
            if any(p in linea for p in _PATRONES_CONTROL_EXTERNO):
                errores.append(
                    f"  [DIST-INTEGRITY] {ruta}:{n}: patron de control "
                    f"remoto externo prohibido (ADR-0022)"
                )
    for n, linea in enumerate(leer("core/kill_switch.py"), 1):
        limpia = linea.split("#")[0]
        if any(f"import {mod}" in limpia for mod in
               ("urllib", "httpx", "requests", "socket")):
            errores.append(
                f"  [DIST-INTEGRITY] core/kill_switch.py:{n}: el kill "
                f"switch debe ser 100% local — red prohibida (ADR-0022)"
            )

    # 2) Self-check criptografico de la cadena de licencias
    import json as _json
    import tempfile as _tempfile
    sys.path.insert(0, str(RAIZ))
    from core.services import license_service as _lic
    pub_original = os.environ.get("AGENTDESK_LICENSE_PUB")
    try:
        priv, pub = _lic.generar_par_claves(bits=2048)
        with _tempfile.NamedTemporaryFile("w", suffix=".pem", delete=False) as f:
            f.write(pub)
        os.environ["AGENTDESK_LICENSE_PUB"] = f.name
        payload = {"machine_id": _lic.machine_id(), "emitida": "2026-07-17",
                   "expira": None, "edicion": "gate-selfcheck"}
        contenido = _json.dumps({"payload": payload,
                                 "firma": _lic.firmar_payload(payload, priv)})
        if not _lic.validar_licencia(contenido)["valida"]:
            errores.append("  [DIST-INTEGRITY] self-check RSA: una licencia "
                           "bien firmada NO valida — cadena rota")
        adulterado = dict(payload, edicion="hacked")
        contenido_mal = _json.dumps({"payload": adulterado,
                                     "firma": _json.loads(contenido)["firma"]})
        if _lic.validar_licencia(contenido_mal)["motivo"] != "firma_invalida":
            errores.append("  [DIST-INTEGRITY] self-check RSA: un payload "
                           "ADULTERADO paso la verificacion de firma")
    finally:
        if pub_original is None:
            os.environ.pop("AGENTDESK_LICENSE_PUB", None)
        else:
            os.environ["AGENTDESK_LICENSE_PUB"] = pub_original
        os.unlink(f.name)

    # 3) Binario distribuido (si existe en esta maquina)
    exe = RAIZ / "dist" / "AgentDesk" / "AgentDesk.exe"
    if exe.exists():
        contenido_exe = exe.read_bytes()
        for patron in _PATRONES_CONTROL_EXTERNO:
            if patron.encode("ascii") in contenido_exe:
                errores.append(
                    f"  [DIST-INTEGRITY] dist/AgentDesk/AgentDesk.exe "
                    f"contiene '{patron}' — binario con control externo"
                )
    return errores


# Privacidad semantica (Fase 25, ADR-0023): la Memoria Hermes es memoria
# PERSISTENTE entre sesiones — una consulta sin scope completo seria una
# fuga directa de conversaciones/know-how entre usuarios o proyectos.
def check_semantic_privacy(archivos: list[str]) -> list[str]:
    """
    ADR-0023 [SEMANTIC-PRIVACY]:
      1. Toda llamada a hermes().buscar()/guardar() en el codigo fuente
         debe pasar user_id= y proyecto_id= explicitos en la MISMA llamada
         (defensa en profundidad: la firma keyword-only ya lo exige en
         runtime; esta regla impide que alguien agregue defaults).
      2. core/vector_store.py debe conservar el fail-closed _exigir_scope
         en guardar() y buscar().
    """
    errores = []
    patron = re.compile(r"hermes\(\)\s*\.\s*(buscar|guardar)\s*\(")
    for ruta in archivos:
        if not ruta.endswith(".py") or ruta.replace("\\", "/").endswith("scripts/gate.py"):
            continue
        texto = "\n".join(leer(ruta))
        for m in patron.finditer(texto):
            # Ventana hasta el cierre de la llamada (balance de parentesis)
            nivel, fin = 0, m.end()
            for i in range(m.end() - 1, min(len(texto), m.end() + 1500)):
                if texto[i] == "(":
                    nivel += 1
                elif texto[i] == ")":
                    nivel -= 1
                    if nivel == 0:
                        fin = i
                        break
            llamada = texto[m.start():fin]
            linea = texto[:m.start()].count("\n") + 1
            for kw in ("user_id=", "proyecto_id="):
                if kw not in llamada:
                    errores.append(
                        f"  [SEMANTIC-PRIVACY] {ruta}:{linea}: llamada a "
                        f"Hermes .{m.group(1)}() sin {kw} explicito"
                    )
    guardas = sum(1 for l in leer("core/vector_store.py")
                  if "_exigir_scope(user_id, proyecto_id)" in l)
    if guardas < 2:
        errores.append(
            "  [SEMANTIC-PRIVACY] core/vector_store.py: el fail-closed "
            "_exigir_scope debe aplicarse en guardar() Y buscar()"
        )
    return errores


# Seguridad de intencion (Fase 27, ADR-0025): el Copiloto traduce lenguaje
# natural en planes — un plan que ofrezca al usuario una accion OT sin
# filtrar seria un LLM decidiendo sobre fierros. Estructuralmente prohibido.
def check_intent_safety(archivos: list[str]) -> list[str]:
    """
    ADR-0025 [INTENT-SAFETY]:
      1. core/services/intent_service.py NO puede invocar escribir_tag ni
         aprobar() — el Copiloto propone, jamas ejecuta.
      2. Toda accion OT del plan debe salir de _filtrar_acciones_ot()
         (que usa ot_service.validar, el filtro determinista de ADR-0024)
         y planificar() debe invocarlo.
      3. La suite tests/intent corre en cada gate.
    """
    errores = []
    texto = "\n".join(leer("core/services/intent_service.py"))
    if not texto:
        return ["  [INTENT-SAFETY] core/services/intent_service.py ausente"]
    for prohibido in ("escribir_tag", ".aprobar("):
        if prohibido in texto:
            errores.append(
                f"  [INTENT-SAFETY] intent_service.py contiene '{prohibido}' "
                f"— el Copiloto propone, jamas ejecuta (ADR-0025)"
            )
    if "ot_service.validar(" not in texto:
        errores.append("  [INTENT-SAFETY] intent_service.py no usa "
                       "ot_service.validar() — filtro de limites ausente")
    if "_filtrar_acciones_ot(" not in texto.split("async def planificar")[-1]:
        errores.append("  [INTENT-SAFETY] planificar() no pasa las acciones "
                       "por _filtrar_acciones_ot()")
    proc = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests/intent",
         "-t", ".", "-p", "test_*.py"],
        cwd=RAIZ, capture_output=True, text=True,
    )
    if proc.returncode != 0:
        detalle = (proc.stderr or proc.stdout or "").strip().splitlines()[-25:]
        errores += ["  [INTENT-SAFETY] tests/intent FALLO:"] + \
                   [f"    {linea}" for linea in detalle]
    return errores


# Actuacion industrial (Fase 26, ADR-0024): escribir hacia la planta puede
# mover fierros — cada tag escribible exige limite fisico de seguridad, y
# ningun endpoint de aprobacion puede quedar sin RBAC supervisor+.
def check_industrial_action(archivos: list[str]) -> list[str]:
    """
    ADR-0024 [INDUSTRIAL-ACTION]:
      1. Todo catalogo ACTUADORES (core/adapters/*.py) declara
         min_escritura/max_escritura numericos con min < max (por AST,
         igual que [INDUSTRIAL-INTEGRITY]).
      2. base.py aplica el filtro determinista (_validar_comando) dentro
         de escribir_tag() — la escritura sin filtro queda prohibida.
      3. Todo endpoint POST /ot/ exige tiene_permiso(...) con "supervisor"
         DENTRO del handler (Human-in-the-loop con RBAC real).
    """
    import ast as _ast
    errores = []

    for ruta in archivos:
        if not ruta.replace("\\", "/").startswith("core/adapters/") or not ruta.endswith(".py"):
            continue
        texto = "\n".join(leer(ruta))
        m = re.search(r"^ACTUADORES:\s*list\[dict\]\s*=\s*(\[.*?\n\])", texto,
                      re.M | re.S)
        if not m:
            continue
        try:
            catalogo = _ast.literal_eval(m.group(1))
        except (ValueError, SyntaxError) as exc:
            errores.append(f"  [OT-ACTION] {ruta}: catalogo ACTUADORES no es "
                           f"literal evaluable ({exc})")
            continue
        for tag in catalogo:
            mn, mx = tag.get("min_escritura"), tag.get("max_escritura")
            if not isinstance(mn, (int, float)) or not isinstance(mx, (int, float)) or mn >= mx:
                errores.append(
                    f"  [OT-ACTION] {ruta}: tag '{tag.get('id')}' sin limite "
                    f"fisico de seguridad valido (min_escritura < max_escritura)"
                )

    base = "\n".join(leer("core/adapters/base.py"))
    m = re.search(r"def escribir_tag\(.*?(?=\n    def )", base, re.S)
    if not m or "_validar_comando" not in m.group(0):
        errores.append("  [OT-ACTION] core/adapters/base.py: escribir_tag() debe "
                       "aplicar el filtro determinista _validar_comando()")

    for ruta in archivos:
        if not ruta.replace("\\", "/").startswith("core/api/") or not ruta.endswith(".py"):
            continue
        texto = "\n".join(leer(ruta))
        for m in re.finditer(r"@router\.post\(\"(/ot/[^\"]*)\"\)", texto):
            fin = texto.find("@router.", m.end())
            bloque = texto[m.start():fin if fin != -1 else len(texto)]
            if "tiene_permiso" not in bloque or '"supervisor"' not in bloque:
                errores.append(
                    f"  [OT-ACTION] {ruta}: endpoint POST {m.group(1)} sin "
                    f"RBAC supervisor+ dentro del handler"
                )
    return errores


def check_memoria_hermes() -> list[str]:
    """Fase 25: suite de Memoria Hermes (persistencia, aislamiento, skills)."""
    proc = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests/memory",
         "-t", ".", "-p", "test_*.py"],
        cwd=RAIZ, capture_output=True, text=True,
    )
    if proc.returncode == 0:
        return []
    detalle = (proc.stderr or proc.stdout or "").strip().splitlines()[-25:]
    return ["  [HERMES] tests/memory FALLO:"] + \
           [f"    {linea}" for linea in detalle]


def check_onboarding() -> list[str]:
    """Fase 24: suite E2E del flujo de bienvenida (primer arranque offline)."""
    proc = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests/e2e",
         "-t", ".", "-p", "test_*.py"],
        cwd=RAIZ, capture_output=True, text=True,
    )
    if proc.returncode == 0:
        return []
    detalle = (proc.stderr or proc.stdout or "").strip().splitlines()[-25:]
    return ["  [ONBOARDING] tests/e2e FALLO:"] + \
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
    errores += check_pesado_sincrono(archivos)
    errores += check_boot_validation()
    errores += check_llm_resilience(archivos)
    errores += check_data_hygiene()
    errores += check_scale_limits(archivos)
    errores += check_escalabilidad()
    errores += check_industrial_integrity(archivos)
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
    errores += check_observabilidad(archivos)
    errores += check_observabilidad_forense()
    errores += check_distribution_integrity(archivos)
    errores += check_onboarding()
    errores += check_semantic_privacy(archivos)
    errores += check_memoria_hermes()
    errores += check_industrial_action(archivos)
    errores += check_intent_safety(archivos)

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
