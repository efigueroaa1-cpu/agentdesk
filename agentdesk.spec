# -*- mode: python ; coding: utf-8 -*-
import os
from pathlib import Path

ROOT = Path(SPECPATH)

_icon_path    = str(ROOT / "assets" / "agentdesk.ico")
_version_path = str(ROOT / "version_info.txt")
if not os.path.exists(_icon_path):    _icon_path    = None
if not os.path.exists(_version_path): _version_path = None

block_cipher = None

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        (str(ROOT / "config.json"),                      "."),
        (str(ROOT / "datos_trabajo.json"),               "."),
        (str(ROOT / "env.example"),                      "."),
        (str(ROOT / "agentdesk-dashboard" / "dist"),     "react_dist"),
        (str(ROOT / "core"),                             "core"),
        (str(ROOT / "ui"),                               "ui"),
        (str(ROOT / "data"),                             "data"),
        # Migraciones Alembic (ADR-0013/0020): _aplicar_migraciones() busca
        # alembic.ini y migrations/ en la raiz del bundle. Sin estas dos
        # entradas, TODO instalador degradaba en silencio a create_all()
        # (best-effort) — el esquema inicial funcionaba, pero las migraciones
        # incrementales del piloto PostgreSQL quedaban inertes en el cliente.
        (str(ROOT / "alembic.ini"),                      "."),
        (str(ROOT / "migrations"),                       "migrations"),
    ],
    hiddenimports=[
        # Logging
        "pythonjsonlogger",
        "pythonjsonlogger.jsonlogger",
        # Gemini
        "google.genai",
        "google.genai.types",
        "google.genai.client",
        "google.auth",
        "google.auth.transport",
        "google.auth.transport.requests",
        # Pydantic
        "pydantic",
        "pydantic_core",
        "pydantic.v1",
        # FastAPI
        "fastapi",
        "fastapi.middleware",
        "fastapi.middleware.cors",
        "fastapi.responses",
        "fastapi.websockets",
        "fastapi.staticfiles",
        "fastapi.exception_handlers",
        # File upload
        "python_multipart",
        "multipart",
        "multipart.multipart",
        # AI providers
        "openai",
        "openai._models",
        "anthropic",
        "anthropic._models",
        "groq",
        "groq._models",
        "core.providers",
        "core.report_generator",
        "core.web_monitor",
        "core.database",
        "core.memory",
        "core.scheduler",
        "core.embeddings",
        "core.rate_limiter",
        "core.auth",
        "core.analytics",
        "core.docs_gen",
        # JWT para auth backend
        "jwt",
        # SQLite (stdlib urllib para HTTP — sin aiohttp)
        "sqlalchemy",
        "sqlalchemy.dialects.sqlite",
        "sqlalchemy.orm",
        "sqlalchemy.pool",
        # PostgreSQL (ADR-0005, modo servidor): SQLAlchemy carga el driver por
        # nombre de dialecto en tiempo de ejecucion (postgresql+psycopg2://),
        # invisible al analisis estatico de PyInstaller — hiddenimport obligatorio.
        "sqlalchemy.dialects.postgresql",
        "psycopg2",
        "asyncpg",   # chequeo async de conectividad PG en el arranque (ADR-0013)
        # Migraciones Alembic (ADR-0013/0020): alembic carga env.py y las
        # revisiones por RUTA en runtime (script_location), no por import —
        # el paquete alembic mismo debe ir completo como hiddenimport.
        "alembic",
        "alembic.command",
        "alembic.config",
        "alembic.runtime.migration",
        "alembic.script",
        # Queue Mode distribuido (ADR-0006/0019): Celery carga backends y
        # transportes por NOMBRE en runtime ("redis://" -> kombu.transport.redis,
        # backend -> celery.backends.redis) — invisible al analisis estatico,
        # exactamente el mismo patron que el dialecto de SQLAlchemy.
        "celery",
        "celery.app",
        "celery.backends",
        "celery.backends.redis",
        "celery.loaders.app",
        "celery.worker.strategy",
        "kombu",
        "kombu.transport.redis",
        "billiard",
        "vine",
        "redis",
        # Circuit Breaker de Concurrencia + metricas (ADR-0014/0019)
        "psutil",
        "prometheus_client",
        # Broker MQTT de planta (ADR-0004, opcional): paho se importa dentro
        # de una funcion con fallback a simulador — si no viaja en el bundle,
        # el modo AGENTDESK_MQTT_BROKER degradaria a simulador EN EL CLIENTE
        # sin error visible, el peor modo de fallo para un piloto.
        "paho",
        "paho.mqtt",
        "paho.mqtt.client",
        "beautifulsoup4",
        "bs4",
        # PDF (fpdf2 - no PIL dependency)
        "fpdf",
        "fpdf.fpdf",
        "fpdf.line_break",
        "fpdf.errors",
        "fpdf.enums",
        "fpdf.fonts",
        # Starlette
        "starlette",
        "starlette.applications",
        "starlette.routing",
        "starlette.requests",
        "starlette.responses",
        "starlette.websockets",
        "starlette.middleware",
        "starlette.middleware.cors",
        "starlette.concurrency",
        "starlette.background",
        "starlette.exceptions",
        "starlette.types",
        # Uvicorn
        "uvicorn",
        "uvicorn.main",
        "uvicorn.config",
        "uvicorn.logging",
        "uvicorn.lifespan.on",
        "uvicorn.lifespan.off",
        "uvicorn.middleware",
        "uvicorn.middleware.proxy_headers",
        "uvicorn.middleware.wsgi",
        "uvicorn.supervisors",
        "uvicorn.protocols",
        "uvicorn.protocols.http",
        "uvicorn.protocols.http.h11_impl",
        "uvicorn.protocols.http.httptools_impl",
        "uvicorn.protocols.websockets",
        "uvicorn.protocols.websockets.websockets_impl",
        "uvicorn.protocols.websockets.wsproto_impl",
        "uvicorn.loops",
        "uvicorn.loops.asyncio",
        "uvicorn.loops.uvloop",
        # HTTP transport
        "h11",
        "h11._connection",
        "h11._events",
        "httptools",
        "httptools.parser",
        "websockets",
        "websockets.connection",
        "websockets.extensions",
        "websockets.frames",
        "websockets.handshake",
        "websockets.legacy",
        "websockets.legacy.server",
        "websockets.legacy.client",
        "wsproto",
        "wsproto.connection",
        "wsproto.events",
        # AnyIO
        "anyio",
        "anyio.abc",
        "anyio.streams",
        "anyio.streams.memory",
        "anyio._backends._asyncio",
        "anyio._backends._trio",
        # CLI + UI
        "click",
        "rich",
        "rich.console",
        "rich.layout",
        "rich.live",
        "rich.markup",
        "rich.progress",
        "rich.panel",
        "rich.table",
        "rich.text",
        "rich.box",
        "rich.prompt",
        "rich._win32_console",
        "rich._windows_renderer",
        # Security
        "bcrypt",
        "dotenv",
        # Project modules
        "security",
        "config_api",
        "core.orchestrator",
        "core.pipeline",
        "core.schemas",
        "core.correction_agent",
        "core.reporter",
        "core.config_loader",
        "core.log_config",
        "core.command_bridge",
        "core.kill_switch",
        "core.metrics",
        "core.path_manager",
        "core.setup_wizard",
        "core.api",
        "core.tools",
        "data.middleware",
        "ui.dashboard",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=["hook_dotenv.py"],
    excludes=[
        "tkinter",
        "matplotlib",
        "numpy",
        "pandas",
        "pytest",
        "IPython",
        "jupyter",
        "notebook",
        "scipy",
        "cv2",
        "sklearn",
        "torch",
        "tensorflow",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AgentDesk",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=_icon_path,
    version=_version_path,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="AgentDesk",
)
