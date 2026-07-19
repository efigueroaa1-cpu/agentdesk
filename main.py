import argparse
import asyncio
import sys
import json
import logging
import datetime
from core.setup_wizard import env_configurado, ejecutar_wizard, migrar_env


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="AgentDesk", add_help=False)
    p.add_argument("--api",  action="store_true")
    p.add_argument("--port", type=int, default=8000)
    args, _ = p.parse_known_args()
    return args

# Detect API mode BEFORE the wizard so Tauri's sidecar launch (no terminal)
# never calls input() and never blocks on a missing .env file.
# sys.argv check is intentionally simple — argparse runs later.
_IS_API_MODE: bool = "--api" in sys.argv

# Env wizard only runs in interactive CLI mode.
# In --api mode the FastAPI startup event handles missing credentials gracefully.
if not _IS_API_MODE:
    if not env_configurado():
        if not migrar_env():
            ejecutar_wizard()

from google import genai
from security import verificar_acceso
from config_api import API_KEY
from core.log_config import configurar_logging
from core.orchestrator import Orquestador
from core.pipeline import PipelineProcessor
from core.correction_agent import CorrectionAgent
from core.command_bridge import CommandBridge, Command, RELOAD_CONFIG
import core.reporter as reporter
from ui.dashboard import (
    console,
    instalar_consola_filtros,
    mostrar_dashboard,
    mostrar_correccion,
    mostrar_reload_ok,
    mostrar_metricas_historicas,
    AgentDeskUI,
)


async def obtener_modelo_disponible(client: genai.Client) -> str | None:
    pager = await client.aio.models.list()
    async for m in pager:
        if 'generateContent' in (m.supported_actions or []):
            return m.name
    return None


async def guardar_reporte(agente_id: str, data: dict, log: logging.Logger) -> None:
    ts   = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    path = f"reportes/data_{agente_id}_{ts}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
    log.info("Reporte guardado", extra={"path": path, "agente": agente_id})


async def main() -> None:
    configurar_logging()
    instalar_consola_filtros()

    def _on_abort(agente, filtro, exc, reporte, raw_data):
        sug = CorrectionAgent().analizar(filtro, str(exc), reporte, raw_data)
        mostrar_correccion(sug)
        reporter.guardar_correccion(agente, sug)

    PipelineProcessor._abort_hook = _on_abort
    log  = logging.getLogger(__name__)
    loop = asyncio.get_running_loop()

    client     = genai.Client(api_key=API_KEY)
    model_name = await obtener_modelo_disponible(client)

    if not model_name:
        log.error("No se encontro ningun modelo disponible en la API.")
        console.print("[bold red][ERROR][/bold red] No hay modelos disponibles.")
        sys.exit(1)

    log.info("Sistema iniciado", extra={"model": model_name})

    bridge       = CommandBridge()
    app          = Orquestador("config.json", client, model_name, bridge=bridge)
    from core.tools import set_orquestador
    set_orquestador(app)   # ADR-0011: delegacion cognitiva Speak/Listen
    tarea_bridge = asyncio.create_task(app.procesar_comandos())
    agentes_cfg  = app.config['agents']

    # AgentDeskUI: dashboard persistente para toda la sesion
    ui = AgentDeskUI(agentes_cfg, bridge, loop)

    try:
        with ui:
            while True:

                # ── Menú ─────────────────────────────────────────────────────
                # Pausar Live para imprimir el menú sin conflicto con el render
                ui.pausar()
                console.print()
                console.rule("[bold]DASHBOARD DE CONTROL[/bold]")
                for i, a in enumerate(agentes_cfg):
                    console.print(f"  [cyan]{i + 1}.[/cyan] {a['nombre']}")
                console.print(
                    f"  [cyan]{len(agentes_cfg) + 1}.[/cyan] "
                    "[bold]Ejecutar todos en paralelo[/bold]"
                )
                console.print("  [cyan]M.[/cyan]  Metricas historicas")
                console.print("  [dim]0. Salir[/dim]")

                opcion = await loop.run_in_executor(None, input, "\nElige agente: ")
                opcion = opcion.strip()
                ui.reanudar()   # Live vuelve a actualizarse

                if opcion == "0":
                    break

                # ── M — Métricas históricas ─────────────────────────────────
                if opcion.upper() == "M":
                    ui.pausar()
                    mostrar_metricas_historicas(con=ui._live.console)
                    await loop.run_in_executor(None, input, "\nPresiona Enter para volver al Dashboard...")
                    ui.reanudar()
                    continue

                # ── N — Nuevo agente ────────────────────────────────────────
                # mostrar_formulario_creacion() pausa/reanuda el Live internamente
                if opcion.upper() == "N":
                    exito = await loop.run_in_executor(
                        None, ui.mostrar_formulario_creacion
                    )
                    if exito:
                        await asyncio.sleep(0.1)
                        agentes_cfg     = app.config["agents"]
                        ui._agentes_cfg = agentes_cfg   # sincroniza sidebar
                    continue

                # ── R — Reload config ───────────────────────────────────────
                if opcion.upper() == "R":
                    ui.pausar()
                    console.print()
                    for i, a in enumerate(agentes_cfg):
                        console.print(f"  [cyan]{i + 1}.[/cyan] {a['nombre']}")
                    console.print(
                        f"  [cyan]{len(agentes_cfg) + 1}.[/cyan] Todos los agentes"
                    )
                    sel = await loop.run_in_executor(
                        None, input, "\nElige agente a recargar: "
                    )
                    ui.reanudar()

                    try:
                        sel_idx = int(sel.strip()) - 1
                        if sel_idx == len(agentes_cfg):
                            agente_id = None
                        elif 0 <= sel_idx < len(agentes_cfg):
                            agente_id = agentes_cfg[sel_idx]["id"]
                        else:
                            console.print("[bold red][ERROR][/bold red] Opcion fuera de rango.")
                            continue
                    except ValueError:
                        console.print("[bold red][ERROR][/bold red] Ingresa un numero valido.")
                        continue

                    snapshot_antes = {
                        aid: {
                            "modelo":      ag.modelo,
                            "temperatura": ag.temperatura,
                            "idioma":      ag.idioma,
                        }
                        for aid, ag in app.agentes.items()
                        if agente_id is None or aid == agente_id
                    }

                    await bridge.send(
                        Command(tipo=RELOAD_CONFIG, payload={"agente_id": agente_id})
                    )
                    await asyncio.sleep(0.05)
                    agentes_cfg     = app.config["agents"]
                    ui._agentes_cfg = agentes_cfg

                    ui.pausar()
                    for aid, antes in snapshot_antes.items():
                        ag = app.agentes[aid]
                        mostrar_reload_ok(ag.nombre, {
                            "modelo":      (antes["modelo"],      ag.modelo),
                            "temperatura": (antes["temperatura"], ag.temperatura),
                            "idioma":      (antes["idioma"],      ag.idioma),
                        })
                    ui.reanudar()
                    continue

                # ── Tareas numéricas ────────────────────────────────────────
                try:
                    idx = int(opcion) - 1

                    # ── Todos en paralelo ──────────────────────────────────
                    if idx == len(agentes_cfg):
                        nombres = [a['nombre'] for a in agentes_cfg]
                        log.info(
                            "Ejecucion paralela iniciada",
                            extra={"num_agentes": len(agentes_cfg)},
                        )
                        inicio = loop.time()
                        ui.iniciar_agentes(nombres)

                        # Sincronizacion de telemetria (2026-07-19): snapshot
                        # consolidado de las unidades Modbus (bloques
                        # `telemetria` de config.json) entregado como raw_data
                        # a TODOS los agentes ANTES de generar — sin esto los
                        # expertos analizaban datos_trabajo.json vacio y el
                        # GroundingGuard abortaba las cifras inventadas.
                        # Composicion aqui, no en core (ADR-0004).
                        datos_paralelo = None
                        bloques_tel = [
                            {"unidad": a["nombre"],
                             "unit_id": a["telemetria"].get("unit_id", 1),
                             "registros": a["telemetria"].get("registros", [])}
                            for a in agentes_cfg
                            if a.get("telemetria", {}).get("protocolo") == "modbus_tcp"
                        ]
                        if bloques_tel:
                            from core.adapters.modbus_adapter import ModbusTelemetryAdapter
                            snapshot = ModbusTelemetryAdapter().leer_snapshot(bloques_tel)
                            datos_paralelo = {"telemetria_industrial": snapshot}
                            log.info(
                                "Telemetria consolidada para el lote paralelo",
                                extra={"unidades": len(snapshot)},
                            )

                        resultados = await app.ejecutar_todos_paralelo(
                            "reporte_ventas", datos_override=datos_paralelo,
                        )
                        for cfg_ag, res in zip(agentes_cfg, resultados):
                            ui.marcar_completado(cfg_ag['nombre'], ok=(res is not None))
                        await asyncio.sleep(0.5)

                        duracion = round(loop.time() - inicio, 2)
                        log.info(
                            "Ejecucion paralela completada",
                            extra={"duracion_s": duracion, "num_agentes": len(agentes_cfg)},
                        )
                        ui.pausar()
                        for cfg_ag, data in zip(agentes_cfg, resultados):
                            if data is None:
                                console.print(
                                    f"[bold red][ERROR][/bold red] {cfg_ag['nombre']}: "
                                    "reporte invalido — ver logs/sistema.log"
                                )
                                continue
                            mostrar_dashboard(data, titulo_resultado=cfg_ag['nombre'])
                            await guardar_reporte(cfg_ag['id'], data, log)
                        ui.reanudar()
                        continue

                    # ── Agente individual ──────────────────────────────────
                    if not (0 <= idx < len(agentes_cfg)):
                        console.print("[bold red][ERROR][/bold red] Opcion fuera de rango.")
                        continue

                    agente = agentes_cfg[idx]
                    ui.iniciar_agentes([agente['nombre']])
                    data = await app.agentes[agente['id']].realizar_tarea("reporte_ventas")
                    ui.marcar_completado(agente['nombre'], ok=(data is not None))
                    await asyncio.sleep(0.4)

                    ui.pausar()
                    if data is None:
                        console.print(
                            "[bold red][ERROR][/bold red] Reporte invalido — "
                            "consulta logs/sistema.log para el detalle."
                        )
                    else:
                        mostrar_dashboard(data)
                        await guardar_reporte(agente['id'], data, log)
                    ui.reanudar()

                except ValueError:
                    console.print("[bold red][ERROR][/bold red] Ingresa un numero valido.")
                except Exception as e:
                    log.exception("Error inesperado en el bucle principal.")
                    console.print(f"[bold red][ERROR][/bold red] {e}")

    finally:
        tarea_bridge.cancel()
        await asyncio.gather(tarea_bridge, return_exceptions=True)
        log.info("CommandBridge cerrado.")


if __name__ == "__main__":
    _args = _parse_args()

    if _args.api:
        # ── Modo servidor (lanzado por Tauri) ─────────────────────────────────
        # Sin autenticación de terminal — el acceso lo gestiona el kill switch
        # y la autenticación de usuarios en el propio frontend React.
        configurar_logging()

        # ── Kill Switch: licencia RSA local ANTES de arrancar uvicorn ─────────
        # ADR-0022: cero red — license.key se valida con criptografia local
        # (firma RSA + machine_id). Sin licencia = modo desktop libre (pass);
        # licencia presente pero invalida = instalacion manipulada → no
        # arrancar (misma politica Zero-Default que el diagnostico de abajo).
        from core import kill_switch as _ks
        if not _ks.validar_ahora():
            print(
                "[KILL SWITCH] Licencia local invalida "
                f"(motivo: {_ks.estado_dict()['motivo']}). Abortando.",
                file=sys.stderr,
            )
            sys.exit(78)   # EX_CONFIG — desactivado por configuración

        # ── Chequeo de salud inicial (Fail-Hard, ADR-0008/ADR-0016) ───────────
        # Secreto JWT débil/por defecto, o AGENTDESK_DB_URL con credenciales
        # por defecto = instalación manipulada → NO arrancar (Fail-Hard,
        # politica Zero-Default). Sin credenciales posibles (ni usuarios ni
        # MASTER_PASSWORD_HASH) → arrancar degradado a modo configuración.
        # BOOT-VALIDATION (Fase 18): este es el ÚNICO punto de invocación del
        # Diagnóstico de Arranque Enterprise — scripts/gate.py lo exige.
        from core.services.boot_diagnostics_service import diagnostico_arranque_sistema
        _salud = diagnostico_arranque_sistema()
        if _salud["criticos"]:
            print("=" * 72, file=sys.stderr)
            print("[SEGURIDAD] AgentDesk se niega a arrancar:", file=sys.stderr)
            for _err in _salud["criticos"]:
                print(f"  - {_err}", file=sys.stderr)
            print("Corrige la configuracion y vuelve a iniciar.", file=sys.stderr)
            print("=" * 72, file=sys.stderr)
            sys.exit(78)   # EX_CONFIG
        if _salud["modo_configuracion"]:
            print("[SEGURIDAD] Arranque en MODO CONFIGURACION:", file=sys.stderr)
            for _av in _salud["avisos"]:
                print(f"  - {_av}", file=sys.stderr)

        import uvicorn
        from core.api import app as _api_app

        # ── Telemetría industrial (ADR-0004) ──────────────────────────────────
        # AGENTDESK_INDUSTRIAL=sim|mqtt activa el adaptador de planta. La
        # composición ocurre AQUÍ (composition root): api.py no se toca; el
        # broadcast del WS y el disparo reactivo de tareas llegan inyectados.
        import os as _os
        if _os.environ.get("AGENTDESK_INDUSTRIAL", "").lower() in ("sim", "mqtt", "1"):
            from core.api import manager as _ws_manager
            from core.adapters.mqtt_adapter import instalar_en_app as _instalar_ot
            _instalar_ot(_api_app, broadcast=_ws_manager.broadcast)

        uvicorn.run(
            _api_app,
            host="127.0.0.1",
            port=_args.port,
            log_level="warning",
        )
    else:
        # ── Modo CLI interactivo ───────────────────────────────────────────────
        # Guard: stdin must be a real terminal. When launched by Tauri's
        # run_agent command (--config, no terminal) exit cleanly instead of
        # crashing on input(). Handles frozen exe without a console too.
        _stdin_ok = sys.stdin is not None
        try:
            if _stdin_ok:
                _stdin_ok = sys.stdin.isatty()
        except Exception:
            _stdin_ok = False
        if not _stdin_ok:
            sys.exit(0)
        if not verificar_acceso():
            sys.exit(1)
        asyncio.run(main())
