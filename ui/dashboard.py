"""
AgentDesk Professional — UI Dashboard

Layout 3 zonas:
  Header   — nombre del proyecto + timestamp
  Sidebar  — lista de agentes con estado coloreado
  WorkArea — Progress con BarColumn vinculado a telemetria del Orchestrator

El AgentDeskLive usa rich.live.Live para auto-actualizarse conforme
el FilterLogHandler recibe eventos de @measure_latency.
"""

import io
import json
import logging
import os
import sys
import threading
from dataclasses import dataclass, field
from datetime import datetime

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.markup import escape
from rich.panel import Panel
from rich.progress import Progress, TaskProgressColumn, TextColumn
from rich.table import Table
from rich import box


def _titulo_app() -> str:
    """
    Titulo del Header. Si AGENTDESK_MODBUS_HOST esta definida (planta real,
    p.ej. ModbusPal en 127.0.0.1:5021) anade la etiqueta [MODBUS]; sin la
    variable el adaptador opera en simulador y el titulo queda limpio.
    Se evalua en CADA render: refleja el entorno vigente, no el del arranque.
    """
    base = "[bold cyan]AgentDesk Professional[/bold cyan]"
    if os.environ.get("AGENTDESK_MODBUS_HOST", "").strip():
        return base + r"  [bold green]\[MODBUS][/bold green]"
    return base


def _crear_console() -> Console:
    """
    Console con salida UTF-8 explícita y sin renderer legacy de Windows.
    Evita UnicodeEncodeError cuando stdout está redirigido (pipes, tests, CI).
    """
    try:
        _file = io.TextIOWrapper(
            sys.stdout.buffer,
            encoding="utf-8",
            errors="replace",
            line_buffering=True,
        )
    except AttributeError:
        _file = sys.stdout
    return Console(
        file=_file,
        force_terminal=True,
        highlight=False,
        safe_box=True,
        legacy_windows=False,
    )


console = _crear_console()


# ── AgentDeskLive — estado por agente ─────────────────────────────────────────

@dataclass
class AgentStatusData:
    nombre:        str
    estado:        str   = "IDLE"    # IDLE | RUNNING | OK | ABORTED | ERROR
    progreso:      float = 0.0
    ultimo_filtro: str   = "-"
    task_id:       object = field(default=None, repr=False)


# ── AgentDeskLive — dashboard con Layout 3 zonas ─────────────────────────────

class AgentDeskLive:
    """
    Dashboard en vivo: Layout(Header / Sidebar / WorkArea) + Live + BarColumn.

    Uso como context manager en main.py:
        live = AgentDeskLive(agentes_cfg, ["Analista de Datos"])
        with live:
            data = await agente.realizar_tarea(...)
            live.marcar_completado("Analista de Datos", ok=data is not None)
            await asyncio.sleep(0.4)   # muestra el estado final antes de cerrar
    """

    # Mapa filtro -> % de avance en la barra (nombres normalizados por @measure_latency)
    _FILTRO_PESOS: dict[str, float] = {
        "Recursion Guard":        33.0,
        "Tone Guard":             67.0,
        "Logic Integrity Filter": 100.0,
    }

    # Colores e iconos ASCII por estado (sin Unicode extendido para compatibilidad)
    _ESTADO_ESTILO: dict[str, tuple[str, str]] = {
        "IDLE":    ("dim",    "[ ]"),
        "RUNNING": ("yellow", "[>]"),
        "OK":      ("green",  "[+]"),
        "ABORTED": ("red",    "[X]"),
        "ERROR":   ("red",    "[!]"),
    }

    def __init__(self, agentes_cfg: list[dict], nombres_activos: list[str]) -> None:
        self._agentes_cfg     = agentes_cfg
        self._nombres_activos = nombres_activos
        self._registry: dict[str, AgentStatusData] = {}
        self._progress        = self._build_progress()
        self._layout          = self._build_layout()
        self._live            = Live(
            self._layout,
            console=console,
            refresh_per_second=6,
            screen=False,
            vertical_overflow="visible",
        )

    # ── Construcción del Layout ────────────────────────────────────────────────

    @staticmethod
    def _barra(pct: float, width: int = 22) -> str:
        """Barra de progreso ASCII — 100% compatible con cp1252 y cualquier terminal."""
        filled = int(width * pct / 100)
        bar    = "[green]" + "#" * filled + "[/green]"
        bar   += "[dim]" + "." * (width - filled) + "[/dim]"
        return bar

    def _build_progress(self) -> Progress:
        return Progress(
            TextColumn("{task.fields[icono]}", justify="center"),
            TextColumn("[bold]{task.description:<24}[/bold]"),
            TextColumn("{task.fields[barra]}"),      # barra ASCII en lugar de BarColumn
            TaskProgressColumn(),
            TextColumn("  [dim]{task.fields[ultimo_filtro]}[/dim]"),
            console=console,
            expand=False,
            transient=False,
        )

    def _build_layout(self) -> Layout:
        layout = Layout(name="root")
        layout.split_column(
            Layout(name="header",  size=3),
            Layout(name="main"),
        )
        layout["main"].split_row(
            Layout(name="sidebar",  ratio=1, minimum_size=22),
            Layout(name="workarea", ratio=3),
        )
        self._render_layout(layout)
        return layout

    # ── Renderizado de zonas ───────────────────────────────────────────────────

    def _render_layout(self, layout: Layout | None = None) -> None:
        target = layout or self._layout
        ts = datetime.now().strftime("%Y-%m-%d  %H:%M:%S")

        # Header
        target["header"].update(Panel(
            f"{_titulo_app()}  "
            f"[dim]|[/dim]  [bold white]{ts}[/bold white]",
            border_style="cyan",
            padding=(0, 2),
        ))

        # Sidebar
        lines: list[str] = ["[bold cyan]Agentes[/bold cyan]\n"]
        for ag in self._agentes_cfg:
            nombre = ag.get("nombre", "")
            data   = self._registry.get(nombre)
            color, icono = self._ESTADO_ESTILO.get(
                data.estado if data else "IDLE", ("dim", "[ ]")
            )
            lines.append(f"[{color}]{icono} {nombre}[/{color}]")
        lines += [
            "\n[dim]─────────────────[/dim]",
            "[cyan]R[/cyan]  Recargar config",
            "[cyan]0[/cyan]  Salir",
        ]
        target["sidebar"].update(Panel(
            "\n".join(lines),
            title="[bold]AGENTS[/bold]",
            border_style="cyan",
        ))

        # WorkArea
        target["workarea"].update(Panel(
            self._progress,
            title="[bold blue]WORKAREA — Estado de Tareas[/bold blue]",
            border_style="blue",
            padding=(1, 2),
        ))

    # ── API pública ────────────────────────────────────────────────────────────

    def _iniciar_tasks(self) -> None:
        """Crea una tarea en el Progress por cada agente activo."""
        for nombre in self._nombres_activos:
            tid = self._progress.add_task(
                description=nombre,
                total=100,
                completed=0,
                icono="[yellow][>][/yellow]",
                barra=self._barra(0),
                ultimo_filtro="Iniciando...",
            )
            self._registry[nombre] = AgentStatusData(
                nombre=nombre,
                estado="RUNNING",
                task_id=tid,
            )
        self._render_layout()

    def actualizar_filtro(
        self, agente: str, filtro: str, status: str, duracion: float
    ) -> None:
        """
        Llamado por FilterLogHandler al completar un filtro.
        Avanza la barra del agente y actualiza su estado en el sidebar.
        """
        data = self._registry.get(agente)
        if data is None or data.task_id is None:
            return

        pct        = self._FILTRO_PESOS.get(filtro, data.progreso)
        filtro_txt = f"{filtro} ({duracion:.3f}s)"

        if status == "ok":
            data.progreso      = pct
            data.estado        = "OK" if pct >= 100.0 else "RUNNING"
            data.ultimo_filtro = filtro_txt
            icono = "[cyan][+][/cyan]" if pct >= 100.0 else "[yellow][>][/yellow]"
            self._progress.update(
                data.task_id,
                completed=pct,
                icono=icono,
                barra=self._barra(pct),
                ultimo_filtro=filtro_txt,
            )
        else:
            data.estado        = "ABORTED"
            data.ultimo_filtro = filtro_txt
            self._progress.update(
                data.task_id,
                icono="[red][X][/red]",
                barra=self._barra(data.progreso),
                ultimo_filtro=f"{filtro_txt} [red]FAIL[/red]",
            )

        self._render_layout()

    def marcar_completado(self, agente: str, ok: bool) -> None:
        """Marca el estado final del agente tras terminar realizar_tarea()."""
        data = self._registry.get(agente)
        if data is None or data.task_id is None:
            return

        if ok:
            data.estado   = "OK"
            data.progreso = 100.0
            self._progress.update(
                data.task_id,
                completed=100,
                icono="[green][+][/green]",
                barra=self._barra(100.0),
                ultimo_filtro="Completado",
            )
        else:
            data.estado = "ABORTED"
            self._progress.update(
                data.task_id,
                icono="[red][X][/red]",
                barra=self._barra(data.progreso),
                ultimo_filtro="Abortado",
            )

        self._render_layout()

    def __enter__(self) -> "AgentDeskLive":
        FilterLogHandler._live_dashboard = self
        self._iniciar_tasks()
        self._live.start()
        return self

    def __exit__(self, *_args) -> None:
        try:
            self._live.stop()
        except (UnicodeEncodeError, Exception):
            pass   # encoding edge-case en stdout redirigido; display ya visible
        FilterLogHandler._live_dashboard = None


# ── AgentDeskUI — dashboard persistente unificado ─────────────────────────────

class AgentDeskUI:
    """
    Dashboard unificado y persistente.

    Combina Layout 3 zonas + Live + hilo de monitoreo en un único objeto
    que dura toda la sesión. Coordina la entrada de datos pausando el
    motor de render sin corromper el estado del display.

    Zonas
    -----
    Header   — título + timestamp actualizado por el monitoring thread
    Sidebar  — lista de agentes con estado + comandos disponibles
    WorkArea — tabla de progreso con barras ASCII por agente

    Uso en main.py
    --------------
        ui = AgentDeskUI(agentes_cfg, bridge, loop)
        with ui:
            while True:
                ui.pausar()
                opcion = input(...)
                ui.reanudar()
                if opcion == "N":
                    await loop.run_in_executor(None, ui.mostrar_formulario_creacion)
    """

    _FILTRO_PESOS: dict[str, float] = {
        "Recursion Guard":        33.0,
        "Tone Guard":             67.0,
        "Logic Integrity Filter": 100.0,
    }
    _ESTADO_ESTILO: dict[str, tuple[str, str]] = {
        "IDLE":    ("dim",    "[ ]"),
        "RUNNING": ("yellow", "[>]"),
        "OK":      ("green",  "[+]"),
        "ABORTED": ("red",    "[X]"),
        "ERROR":   ("red",    "[!]"),
    }

    def __init__(
        self,
        agentes_cfg: list[dict],
        bridge: object,
        loop: object,
    ) -> None:
        self._agentes_cfg = list(agentes_cfg)
        self._bridge      = bridge
        self._loop        = loop
        self._registry: dict[str, AgentStatusData] = {}
        self._lock        = threading.RLock()           # protege actualizaciones de layout
        self._stop_event  = threading.Event()
        self._monitor: threading.Thread | None = None

        self._progress = self._build_progress()
        self._layout   = self._build_layout()
        self._live     = Live(
            self._layout,
            console=console,
            refresh_per_second=4,
            screen=False,
            vertical_overflow="visible",
        )

    # ── Context manager ────────────────────────────────────────────────────────

    def __enter__(self) -> "AgentDeskUI":
        FilterLogHandler._live_dashboard = self
        try:
            self._live.start()
        except Exception:
            pass
        self._stop_event.clear()
        self._monitor = threading.Thread(
            target=self._monitoring_loop, daemon=True, name="agentdesk-monitor"
        )
        self._monitor.start()
        return self

    def __exit__(self, *_) -> None:
        self._stop_event.set()
        FilterLogHandler._live_dashboard = None
        try:
            self._live.stop()
        except Exception:
            pass

    # ── Hilo de monitoreo ─────────────────────────────────────────────────────

    def _monitoring_loop(self) -> None:
        """
        Se ejecuta en un hilo daemon durante toda la sesion.
        Actualiza el Header con el timestamp actual cada segundo,
        manteniendo el display sincronizado incluso durante el idle.
        """
        while not self._stop_event.is_set():
            with self._lock:
                self._render_header()
            self._stop_event.wait(timeout=1.0)   # sleep interruptible

    # ── Pause / resume para entrada de datos ─────────────────────────────────

    def pausar(self) -> None:
        """
        Para el motor Live antes de mostrar un prompt o menú.
        El monitoring thread sigue actualizando el layout en memoria;
        cuando se reanude, el display mostrará el estado más reciente.
        """
        try:
            self._live.stop()
        except Exception:
            pass

    def reanudar(self) -> None:
        """Reinicia el motor Live tras la entrada de datos."""
        try:
            self._live.start()
        except Exception:
            pass

    # ── Formulario de creación desde el Sidebar ───────────────────────────────

    def mostrar_formulario_creacion(self) -> bool:
        """
        Pausa el Live, lanza PanelCreacion, actualiza el Sidebar con el
        nuevo agente si la creación tuvo éxito y reanuda el Live.

        Diseñado para ejecutarse desde loop.run_in_executor() (contexto síncrono).
        El display queda congelado en el último frame durante el formulario,
        evitando parpadeos o scroll inesperado.
        """
        self.pausar()
        try:
            panel = PanelCreacion(bridge=self._bridge, loop=self._loop)
            exito = panel.mostrar()
            if exito:
                # Refrescar lista de agentes desde config.json
                try:
                    with open("config.json", encoding="utf-8") as f:
                        cfg = json.load(f)
                    with self._lock:
                        self._agentes_cfg = cfg["agents"]
                        self._render_sidebar()
                except Exception:
                    pass
            return exito
        finally:
            self.reanudar()

    # ── Progress: gestión de tareas ───────────────────────────────────────────

    def iniciar_agentes(self, nombres: list[str]) -> None:
        """Registra los agentes activos y crea sus barras en el Progress."""
        with self._lock:
            for nombre in nombres:
                tid = self._progress.add_task(
                    description=nombre,
                    total=100,
                    completed=0,
                    icono="[yellow][>][/yellow]",
                    barra=self._barra(0),
                    ultimo_filtro="Iniciando...",
                )
                self._registry[nombre] = AgentStatusData(
                    nombre=nombre, estado="RUNNING", task_id=tid
                )
            self._render_layout()

    def actualizar_filtro(
        self, agente: str, filtro: str, status: str, duracion: float
    ) -> None:
        """Llamado por FilterLogHandler: avanza la barra del agente."""
        data = self._registry.get(agente)
        if data is None or data.task_id is None:
            return
        pct        = self._FILTRO_PESOS.get(filtro, data.progreso)
        filtro_txt = f"{filtro} ({duracion:.3f}s)"
        with self._lock:
            if status == "ok":
                data.progreso      = pct
                data.estado        = "OK" if pct >= 100.0 else "RUNNING"
                data.ultimo_filtro = filtro_txt
                icono = "[cyan][+][/cyan]" if pct >= 100.0 else "[yellow][>][/yellow]"
                self._progress.update(
                    data.task_id, completed=pct,
                    icono=icono, barra=self._barra(pct), ultimo_filtro=filtro_txt,
                )
            else:
                data.estado        = "ABORTED"
                data.ultimo_filtro = filtro_txt
                self._progress.update(
                    data.task_id, icono="[red][X][/red]",
                    barra=self._barra(data.progreso),
                    ultimo_filtro=f"{filtro_txt} [red]FAIL[/red]",
                )
            self._render_layout()

    def marcar_completado(self, agente: str, ok: bool) -> None:
        """Marca el estado final del agente tras terminar realizar_tarea()."""
        data = self._registry.get(agente)
        if data is None or data.task_id is None:
            return
        with self._lock:
            if ok:
                data.estado = "OK"
                data.progreso = 100.0
                self._progress.update(
                    data.task_id, completed=100,
                    icono="[green][+][/green]",
                    barra=self._barra(100.0), ultimo_filtro="Completado",
                )
            else:
                data.estado = "ABORTED"
                self._progress.update(
                    data.task_id, icono="[red][X][/red]",
                    barra=self._barra(data.progreso), ultimo_filtro="Abortado",
                )
            self._render_layout()

    # ── Construcción del layout ───────────────────────────────────────────────

    @staticmethod
    def _barra(pct: float, width: int = 22) -> str:
        filled = int(width * pct / 100)
        return (
            "[green]" + "#" * filled + "[/green]"
            + "[dim]" + "." * (width - filled) + "[/dim]"
        )

    def _build_progress(self) -> Progress:
        return Progress(
            TextColumn("{task.fields[icono]}", justify="center"),
            TextColumn("[bold]{task.description:<24}[/bold]"),
            TextColumn("{task.fields[barra]}"),
            TaskProgressColumn(),
            TextColumn("  [dim]{task.fields[ultimo_filtro]}[/dim]"),
            console=console,
            expand=False,
            transient=False,
        )

    def _build_layout(self) -> Layout:
        layout = Layout(name="root")
        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="main"),
        )
        layout["main"].split_row(
            Layout(name="sidebar",  ratio=1, minimum_size=22),
            Layout(name="workarea", ratio=3),
        )
        self._render_layout(layout)
        return layout

    # ── Renderizado de zonas (thread-safe via self._lock) ─────────────────────

    def _render_layout(self, target: Layout | None = None) -> None:
        """Actualiza las tres zonas. Llamar siempre dentro de self._lock."""
        t = target or self._layout
        self._render_header(t)
        self._render_sidebar(t)
        self._render_workarea(t)

    def _render_header(self, target: Layout | None = None) -> None:
        ts = datetime.now().strftime("%Y-%m-%d  %H:%M:%S")
        (target or self._layout)["header"].update(Panel(
            f"{_titulo_app()}  "
            f"[dim]|[/dim]  [bold white]{ts}[/bold white]",
            border_style="cyan",
            padding=(0, 2),
        ))

    def _render_sidebar(self, target: Layout | None = None) -> None:
        lines: list[str] = ["[bold cyan]Agentes[/bold cyan]\n"]
        for ag in self._agentes_cfg:
            nombre = ag.get("nombre", "")
            data   = self._registry.get(nombre)
            color, icono = self._ESTADO_ESTILO.get(
                data.estado if data else "IDLE", ("dim", "[ ]")
            )
            lines.append(f"[{color}]{icono} {nombre}[/{color}]")
        lines += [
            "\n[dim]─────────────[/dim]",
            "[cyan]N[/cyan]  Nuevo agente",
            "[cyan]R[/cyan]  Recargar cfg",
            "[cyan]0[/cyan]  Salir",
        ]
        (target or self._layout)["sidebar"].update(Panel(
            "\n".join(lines),
            title="[bold]AGENTS[/bold]",
            border_style="cyan",
        ))

    def _render_workarea(self, target: Layout | None = None) -> None:
        (target or self._layout)["workarea"].update(Panel(
            self._progress,
            title="[bold blue]WORKAREA — Estado de Tareas[/bold blue]",
            border_style="blue",
            padding=(1, 2),
        ))


# ── FilterLogHandler — telemetria en tiempo real ──────────────────────────────

class FilterLogHandler(logging.Handler):
    """
    Intercepta entradas de @measure_latency (campos 'filtro' + 'duracion_s').

    Modo Live  : notifica a AgentDeskLive para actualizar las barras de progreso.
    Modo texto : imprime cada filtro como linea en la consola (fallback).
    """

    _ESTILOS: dict[str, tuple[str, str]] = {
        "ok":      ("[ OK ]", "green"),
        "error":   ("[FAIL]", "red"),
        "timeout": ("[TIME]", "yellow"),
    }

    # Referencia al dashboard live activo; None cuando no hay Live en curso.
    _live_dashboard: "AgentDeskLive | None" = None

    def emit(self, record: logging.LogRecord) -> None:
        filtro   = getattr(record, "filtro",     None)
        duracion = getattr(record, "duracion_s", None)
        if not filtro or duracion is None:
            return

        status  = getattr(record, "status",  "ok")
        agente  = getattr(record, "agente",  "")

        # ── Modo Live: delegar al dashboard, no imprimir en consola ───────────
        if self.__class__._live_dashboard is not None:
            self.__class__._live_dashboard.actualizar_filtro(
                agente, filtro, status, duracion
            )
            return

        # ── Modo texto (fallback): imprimir linea en consola ──────────────────
        etiqueta, color = self._ESTILOS.get(status, ("[????]", "white"))
        agente_col = f"[dim]{agente:<22}[/dim]  " if agente else ""
        console.print(
            f"  {agente_col}"
            f"[bold]{filtro:<28}[/bold] "
            f"[{color}]{etiqueta}[/{color}]"
            f"[dim]  {duracion:.4f}s[/dim]"
        )


def instalar_consola_filtros() -> None:
    """Registra FilterLogHandler en core.pipeline (idempotente)."""
    pl = logging.getLogger("core.pipeline")
    if any(isinstance(h, FilterLogHandler) for h in pl.handlers):
        return

    pl.propagate = False
    pl.addHandler(FilterLogHandler(level=logging.DEBUG))

    for h in logging.getLogger().handlers:
        if isinstance(h, logging.FileHandler):
            pl.addHandler(h)


# ── Helpers de sección (modo texto) ───────────────────────────────────────────

def mostrar_cabecera_orquestador(titulo: str) -> None:
    console.print()
    console.rule(
        f"[bold cyan]ORCHESTRATOR CONSOLE[/bold cyan]"
        f"  |  [bold yellow]{titulo}[/bold yellow]"
    )


def _mostrar_separador_resultado(titulo: str = "RESULTADO") -> None:
    console.rule(f"[bold blue]{titulo}[/bold blue]")


# ── Correction Agent — panel destacado ────────────────────────────────────────

def mostrar_correccion(sugerencia: "Sugerencia") -> None:  # type: ignore[name-defined]
    from core.correction_agent import Sugerencia  # import local

    _COLORES: dict[str, tuple[str, str]] = {
        "INFO":     ("cyan",   "[ INFO ]"),
        "WARNING":  ("yellow", "[ WARN ]"),
        "CRITICAL": ("red",    "[ CRIT ]"),
    }
    color, etiqueta = _COLORES.get(sugerencia.severidad, ("white", "[????]"))

    secciones: list[str] = [
        f"[bold]Causa raiz[/bold]\n  {escape(sugerencia.causa_raiz)}",
        "",
        f"[bold]Accion recomendada[/bold]\n  {escape(sugerencia.accion)}",
    ]
    if sugerencia.ejemplo:
        secciones += ["", f"[bold]Ejemplo[/bold]\n[dim]  {escape(sugerencia.ejemplo)}[/dim]"]
    if sugerencia.log_excerpt:
        fragmento  = json.dumps(sugerencia.log_excerpt, ensure_ascii=False, indent=2)
        lineas_log = "\n  ".join(escape(fragmento).splitlines())
        secciones += ["", f"[bold]Extracto del log JSON[/bold]\n[dim]  {lineas_log}[/dim]"]

    console.print()
    console.print(Panel(
        "\n".join(secciones),
        title=f"[bold {color}]  CORRECTION AGENT  |  {sugerencia.filtro}  |  {etiqueta}  [/bold {color}]",
        border_style=color,
        expand=True,
        padding=(1, 2),
    ))
    console.print()


# ── Configuracion dinamica ─────────────────────────────────────────────────────

def mostrar_dashboard_config(config_path: str = "config.json") -> None:
    from core.config_loader import load_config

    config  = load_config(config_path)
    agentes = config.get("agents", [])

    table = Table(
        title="[bold cyan]Configuracion Dinamica de Agentes[/bold cyan]",
        box=box.SIMPLE_HEAVY,
        show_lines=True,
        title_justify="left",
        expand=False,
    )
    table.add_column("Nombre",   style="bold",   no_wrap=True)
    table.add_column("Modelo",   style="cyan",   no_wrap=True)
    table.add_column("Temp.",    style="yellow", justify="center", no_wrap=True)
    table.add_column("Idioma",   style="green",  justify="center", no_wrap=True)
    table.add_column("tipo_ia",  style="dim",    justify="center", no_wrap=True)

    for ag in agentes:
        table.add_row(
            ag.get("nombre",      "-"),
            ag.get("modelo",      "-"),
            str(ag.get("temperatura", "-")),
            ag.get("idioma",      "espanol"),
            ag.get("tipo_ia",     "-"),
        )

    console.print()
    console.rule("[bold cyan]AGENT DESK — Configuracion de Agentes[/bold cyan]")
    console.print(table)

    for ag in agentes:
        console.print(Panel(
            ag.get("prompt_base", "Sin prompt_base definido."),
            title=f"[bold]{ag.get('nombre')}[/bold]  —  prompt_base",
            border_style="dim",
            expand=False,
        ))
    console.print()


# ── CommandBridge — confirmacion visual ───────────────────────────────────────

def mostrar_reload_ok(nombre_agente: str, cambios: dict) -> None:
    lineas = [f"[bold]Agente:[/bold]  {nombre_agente}", ""]
    for campo, (antes, despues) in cambios.items():
        if antes != despues:
            lineas.append(
                f"  [dim]{campo}[/dim]  {escape(str(antes))} [dim]->[/dim] "
                f"[cyan]{escape(str(despues))}[/cyan]"
            )
        else:
            lineas.append(
                f"  [dim]{campo}[/dim]  {escape(str(despues))}  [dim](sin cambio)[/dim]"
            )
    console.print(Panel(
        "\n".join(lineas),
        title="[bold green]  RELOAD_CONFIG aplicado  [/bold green]",
        border_style="green",
        expand=False,
    ))


# ── Dashboard de resultado ─────────────────────────────────────────────────────

def mostrar_dashboard(data: dict, titulo_resultado: str = "RESULTADO") -> None:
    _mostrar_separador_resultado(titulo_resultado)

    console.print(Panel(
        data.get("resumen", "Sin datos"),
        title="[bold blue]Resumen Ejecutivo[/bold blue]",
        border_style="blue",
    ))

    if integridad := data.get("_integridad"):
        console.print(Panel(
            f"[yellow]{integridad}[/yellow]",
            title="[bold yellow][!] Aviso de Integridad[/bold yellow]",
            border_style="yellow",
        ))

    table = Table(
        title="[bold green]Reporte Financiero[/bold green]",
        box=box.SIMPLE_HEAVY,
        show_lines=False,
        title_justify="left",
    )
    tabla_data = data.get("tabla", [])
    if tabla_data:
        for h in tabla_data[0]:
            table.add_column(str(h), style="cyan")
        for row in tabla_data[1:]:
            table.add_row(*[str(c) for c in row])
    console.print(table)


# ── Crear nuevo agente desde la UI ────────────────────────────────────────────

def interactuar_nuevo_agente() -> dict | None:
    """
    Interfaz interactiva para registrar un nuevo agente.
    Usa rich.prompt para capturar los datos, valida con AgentConfig
    y devuelve el dict listo para enviarse via CommandBridge.

    Retorna el dict validado, o None si el usuario cancela o la validación falla.
    """
    from rich.prompt import Confirm, Prompt
    from pydantic import ValidationError
    from core.schemas import AgentConfig

    console.print()
    console.rule("[bold cyan]CREAR NUEVO AGENTE[/bold cyan]")

    try:
        nombre = Prompt.ask("[bold]Nombre del agente[/bold]", console=console)
        if not nombre.strip():
            console.print("[red]El nombre es obligatorio. Operacion cancelada.[/red]")
            return None

        tipo_ia = Prompt.ask(
            "[bold]Tipo de IA[/bold]",
            choices=["general", "finanzas", "custom"],
            default="general",
            console=console,
        )

        modelo = Prompt.ask(
            "[bold]Modelo[/bold]",
            default="models/gemini-2.5-flash",
            console=console,
        )

        temp_raw = Prompt.ask(
            "[bold]Temperatura[/bold] (0.0 = preciso / 1.0 = creativo)",
            default="0.4",
            console=console,
        )
        try:
            temperatura = float(temp_raw)
        except ValueError:
            console.print("[red]Temperatura debe ser un numero. Operacion cancelada.[/red]")
            return None

        idioma = Prompt.ask(
            "[bold]Idioma de respuesta[/bold]",
            default="español",
            console=console,
        )

        prompt_base = Prompt.ask(
            "[bold]Prompt base[/bold] (rol del agente, opcional)",
            default="",
            console=console,
        )

        data = {
            "nombre":      nombre.strip(),
            "tipo_ia":     tipo_ia,
            "modelo":      modelo.strip(),
            "temperatura": temperatura,
            "idioma":      idioma.strip(),
            "prompt_base": prompt_base.strip(),
        }

        # ── Validacion con AgentConfig (Pydantic) ─────────────────────────────
        try:
            AgentConfig.model_validate(data)
        except ValidationError as e:
            console.print(Panel(
                "\n".join(
                    f"  [red]• {err['loc'][0] if err['loc'] else 'campo'}: "
                    f"{err['msg']}[/red]"
                    for err in e.errors()
                ),
                title="[bold red]Errores de validacion[/bold red]",
                border_style="red",
            ))
            return None

        # ── Resumen antes de confirmar ────────────────────────────────────────
        console.print()
        console.print(Panel(
            f"[bold]Nombre:[/bold]      {data['nombre']}\n"
            f"[bold]tipo_ia:[/bold]     {data['tipo_ia']}\n"
            f"[bold]Modelo:[/bold]      {data['modelo']}\n"
            f"[bold]Temperatura:[/bold] {data['temperatura']}\n"
            f"[bold]Idioma:[/bold]      {data['idioma']}\n"
            f"[bold]Prompt base:[/bold] {data['prompt_base'] or '[dim](vacio)[/dim]'}",
            title="[bold cyan]Resumen del nuevo agente[/bold cyan]",
            border_style="cyan",
        ))

        if not Confirm.ask("[bold]Confirmar creacion?[/bold]", default=True, console=console):
            console.print("[dim]Operacion cancelada.[/dim]")
            return None

        return data

    except (KeyboardInterrupt, EOFError):
        console.print("\n[dim]Operacion cancelada.[/dim]")
        return None


# ── PanelCreacion — componente de alta fidelidad ─────────────────────────────

class PanelCreacion:
    """
    Componente UI para la creacion de nuevos agentes.

    Presenta un formulario en 3 secciones (Identidad / Modelo / Personalidad)
    dentro de Panels Rich que sustituyen temporalmente el area principal.

    Flujo:
      1. Secciones visuales capturan datos con rich.prompt.
      2. Valida con AgentConfig (Pydantic) — muestra errores en panel rojo.
      3. Muestra resumen y pide confirmacion.
      4. Envia Command(CREAR_AGENTE) al Orchestrator via CommandBridge
         usando asyncio.run_coroutine_threadsafe (seguro desde hilo sync).
      5. KeyboardInterrupt/EOFError devuelve control al menu sin romper la UI.

    Uso desde main.py:
        panel = PanelCreacion(bridge=bridge, loop=loop)
        exito = await loop.run_in_executor(None, panel.mostrar)
    """

    def __init__(self, bridge: object, loop: object) -> None:
        self._bridge = bridge
        self._loop   = loop

    # ── Punto de entrada ──────────────────────────────────────────────────────

    def mostrar(self) -> bool:
        """
        Muestra el panel interactivo y devuelve True si el agente fue creado.
        Diseñado para ejecutarse en un hilo (run_in_executor).
        """
        from rich.prompt import Confirm, Prompt
        from pydantic import ValidationError
        from core.schemas import AgentConfig
        from core.command_bridge import Command, CREAR_AGENTE

        console.print()
        console.rule(
            "[bold cyan]PANEL DE CREACION[/bold cyan]  |  Nuevo Agente",
            style="cyan",
        )

        try:
            data: dict = {}

            # ── Seccion 1 — Identidad ─────────────────────────────────────────
            console.print(Panel(
                "[dim]Define el nombre e identidad funcional del agente.[/dim]",
                title="[bold cyan]1 / 3  —  IDENTIDAD[/bold cyan]",
                border_style="cyan",
                expand=False,
            ))
            nombre = Prompt.ask("  [bold]Nombre[/bold]", console=console)
            if not nombre.strip():
                console.print("[red]El nombre es obligatorio. Creacion cancelada.[/red]")
                return False
            tipo_ia = Prompt.ask(
                "  [bold]Tipo de IA[/bold]",
                choices=["general", "finanzas", "custom"],
                default="general",
                console=console,
            )
            data["nombre"]  = nombre.strip()
            data["tipo_ia"] = tipo_ia

            # ── Seccion 2 — Configuracion del modelo ─────────────────────────
            console.print()
            console.print(Panel(
                "[dim]Selecciona el modelo Gemini, creatividad e idioma de respuesta.[/dim]",
                title="[bold cyan]2 / 3  —  CONFIGURACION DEL MODELO[/bold cyan]",
                border_style="cyan",
                expand=False,
            ))
            modelo = Prompt.ask(
                "  [bold]Modelo[/bold]",
                default="models/gemini-2.5-flash",
                console=console,
            )
            temp_raw = Prompt.ask(
                "  [bold]Temperatura[/bold]  (0.0 = preciso  /  1.0 = creativo)",
                default="0.4",
                console=console,
            )
            try:
                temperatura = float(temp_raw)
            except ValueError:
                console.print("[red]Temperatura debe ser un numero decimal. Cancelado.[/red]")
                return False
            idioma = Prompt.ask(
                "  [bold]Idioma de respuesta[/bold]",
                default="español",
                console=console,
            )
            data["modelo"]      = modelo.strip()
            data["temperatura"] = temperatura
            data["idioma"]      = idioma.strip()

            # ── Seccion 3 — Personalidad ─────────────────────────────────────
            console.print()
            console.print(Panel(
                "[dim]Instruccion de rol que se antepone a cada tarea. Puede dejarse vacio.[/dim]",
                title="[bold cyan]3 / 3  —  PERSONALIDAD[/bold cyan]",
                border_style="cyan",
                expand=False,
            ))
            prompt_base = Prompt.ask(
                "  [bold]Prompt base[/bold]  (opcional)",
                default="",
                console=console,
            )
            data["prompt_base"] = prompt_base.strip()

            # ── Validacion Pydantic ───────────────────────────────────────────
            try:
                AgentConfig.model_validate(data)
            except ValidationError as e:
                console.print()
                console.print(Panel(
                    "\n".join(
                        f"  [red]• {err['loc'][0] if err['loc'] else 'campo'}: "
                        f"{err['msg']}[/red]"
                        for err in e.errors()
                    ),
                    title="[bold red]Errores de validacion — Creacion cancelada[/bold red]",
                    border_style="red",
                    expand=False,
                ))
                return False

            # ── Resumen + confirmacion ────────────────────────────────────────
            console.print()
            console.print(Panel(
                f"  [bold]Nombre:[/bold]      {data['nombre']}\n"
                f"  [bold]Tipo IA:[/bold]     {data['tipo_ia']}\n"
                f"  [bold]Modelo:[/bold]      {data['modelo']}\n"
                f"  [bold]Temperatura:[/bold] {data['temperatura']}\n"
                f"  [bold]Idioma:[/bold]      {data['idioma']}\n"
                f"  [bold]Prompt:[/bold]      {data['prompt_base'] or '[dim](vacio)[/dim]'}",
                title="[bold green]Resumen — Revisa los datos antes de confirmar[/bold green]",
                border_style="green",
                expand=False,
            ))

            if not Confirm.ask(
                "\n  [bold]Confirmar creacion del agente?[/bold]",
                default=True,
                console=console,
            ):
                console.print("[dim]Creacion cancelada por el usuario.[/dim]")
                return False

            # ── Enviar al Orchestrator via CommandBridge ──────────────────────
            return self._enviar(Command(tipo=CREAR_AGENTE, payload=data))

        except (KeyboardInterrupt, EOFError):
            # Atrapa Ctrl+C o EOF sin propagar la excepcion al event loop
            console.print("\n[dim]Creacion interrumpida. Regresando al menu principal.[/dim]")
            return False

    # ── Envio thread-safe al Orchestrator ─────────────────────────────────────

    def _enviar(self, cmd: object) -> bool:
        """
        Envia el comando al event loop principal desde este hilo sincrono.
        asyncio.run_coroutine_threadsafe garantiza que la cola no se corrompa.
        """
        import asyncio as _asyncio
        try:
            future = _asyncio.run_coroutine_threadsafe(
                self._bridge.send(cmd),
                self._loop,
            )
            future.result(timeout=5.0)
            console.print()
            console.print(Panel(
                f"[bold green]'{cmd.payload.get('nombre')}' registrado exitosamente.[/bold green]\n"
                "[dim]El agente aparecera en el menu principal en la siguiente pantalla.[/dim]",
                title="[bold green]Creacion completada[/bold green]",
                border_style="green",
                expand=False,
            ))
            return True
        except Exception as exc:
            console.print(Panel(
                f"[red]Error al comunicarse con el Orchestrator:\n{escape(str(exc))}[/red]",
                title="[bold red]Error de comunicacion[/bold red]",
                border_style="red",
                expand=False,
            ))
            return False


# ── Métricas históricas ───────────────────────────────────────────────────────

def mostrar_metricas_historicas(
    con: "Console | None" = None,
    max_entradas: int = 1000,
) -> None:
    """
    Lee logs/sistema.log, calcula métricas por agente y las muestra
    en tablas Rich con latencias por filtro y tendencia de rendimiento.

    Parámetros
    ----------
    con          : consola Rich a usar (usa la global si no se pasa)
    max_entradas : número máximo de entradas del log a procesar
    """
    from core.metrics import cargar_entradas_log, calcular_metricas, resumen_sistema

    _c = con or console     # permite pasar ui.console desde main.py

    _c.print()
    _c.rule("[bold cyan]METRICAS HISTORICAS[/bold cyan]")

    try:
        entradas = cargar_entradas_log(max_entradas=max_entradas)
    except FileNotFoundError:
        _c.print(Panel(
            "[yellow]El archivo logs/sistema.log no existe todavia.\n"
            "Ejecuta al menos un agente para generar métricas.[/yellow]",
            border_style="yellow",
        ))
        return

    if not entradas:
        _c.print(Panel(
            "[yellow]Sin datos. Ejecuta al menos un agente para generar métricas.[/yellow]",
            border_style="yellow",
        ))
        return

    metricas = calcular_metricas(entradas)
    if not metricas:
        _c.print(Panel(
            "[yellow]No se encontraron eventos de agentes en el log.[/yellow]",
            border_style="yellow",
        ))
        return

    resumen = resumen_sistema(metricas)

    # ── Panel de resumen del sistema ──────────────────────────────────────────
    _c.print(Panel(
        f"  [bold]Agentes activos:[/bold]   {resumen['agentes']}\n"
        f"  [bold]Total tareas:[/bold]      {resumen['total_tareas']}\n"
        f"  [bold]Tasa de exito:[/bold]     {resumen['tasa_exito_pct']}%\n"
        f"  [bold]Latencia promedio:[/bold] {resumen['lat_promedio_s']}s\n"
        f"  [bold]Latencia maxima:[/bold]   {resumen['lat_max_s']}s\n"
        f"  [bold]Desv. estandar:[/bold]    {resumen['lat_desv_std']}s",
        title="[bold cyan]Resumen del Sistema[/bold cyan]",
        border_style="cyan",
        expand=False,
    ))

    # ── Tabla de métricas por agente ─────────────────────────────────────────
    tabla = Table(
        title="[bold]Metricas por Agente[/bold]",
        box=box.SIMPLE_HEAVY,
        show_lines=True,
        title_justify="left",
    )
    tabla.add_column("Agente",      style="bold",   no_wrap=True)
    tabla.add_column("Total",       justify="center")
    tabla.add_column("Exitos",      style="green",  justify="center")
    tabla.add_column("Abortados",   style="red",    justify="center")
    tabla.add_column("Tasa exito",  justify="center")
    tabla.add_column("Lat. prom.",  style="yellow", justify="center")
    tabla.add_column("Lat. max.",   style="dim",    justify="center")
    tabla.add_column("Tendencia",   justify="center")
    tabla.add_column("Ultimo run",  style="dim",    no_wrap=True)

    _TENDENCIA_ESTILO = {
        "mejora":  "[green][+] Mejora[/green]",
        "empeora": "[red][-] Empeora[/red]",
        "estable": "[dim][=] Estable[/dim]",
    }

    # Solo agentes que completaron al menos 1 tarea (exito o abortada)
    activos = {n: m for n, m in metricas.items() if m.total_tareas > 0}
    if not activos:
        _c.print("[dim]Sin actividad registrada aun.[/dim]")
        return

    for nombre in sorted(activos):
        m = activos[nombre]
        tasa = (
            f"[green]{m.tasa_exito_pct:.1f}%[/green]"
            if m.tasa_exito_pct >= 80
            else f"[red]{m.tasa_exito_pct:.1f}%[/red]"
        )
        tabla.add_row(
            nombre,
            str(m.total_tareas),
            str(m.exitosas),
            str(m.abortadas),
            tasa,
            f"{m.lat_promedio_s:.4f}s",
            f"{m.lat_max_s:.4f}s",
            _TENDENCIA_ESTILO.get(m.tendencia, "[=] Estable"),
            m.ultimo_run[:19] if m.ultimo_run != "-" else "-",
        )

    _c.print(tabla)

    # ── Latencias por filtro (desglose) ──────────────────────────────────────
    _c.print()
    _c.rule("[bold]Latencia por Filtro del Pipeline[/bold]", style="dim")

    filtros_global: dict[str, list[float]] = {}
    for m in metricas.values():
        for fname, mf in m.filtros.items():
            if fname not in filtros_global:
                filtros_global[fname] = []
            filtros_global[fname].extend(mf.latencias)

    if filtros_global:
        tf = Table(box=box.SIMPLE_HEAVY, show_lines=False)
        tf.add_column("Filtro",       style="bold",   no_wrap=True)
        tf.add_column("Ejecuciones",  justify="center")
        tf.add_column("Lat. prom.",   style="yellow", justify="center")
        tf.add_column("Lat. max.",    style="dim",    justify="center")
        tf.add_column("Barra",        no_wrap=True)

        max_lat = max(
            (max(lats) for lats in filtros_global.values() if lats), default=1.0
        ) or 1.0

        for fname in sorted(filtros_global):
            lats = filtros_global[fname]
            if not lats:
                continue
            from statistics import mean as _mean
            prom = round(_mean(lats), 4)
            mxm  = round(max(lats), 4)
            w      = 20
            filled = int(w * prom / max_lat)
            barra  = "[yellow]" + "#" * filled + "[/yellow][dim]" + "." * (w - filled) + "[/dim]"
            tf.add_row(fname, str(len(lats)), f"{prom:.4f}s", f"{mxm:.4f}s", barra)

        _c.print(tf)

    _c.print()


# ── Ejecucion directa ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    mostrar_dashboard_config()
