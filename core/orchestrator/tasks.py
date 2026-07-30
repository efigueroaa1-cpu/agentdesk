# -*- coding: utf-8 -*-
"""
core/orchestrator_tasks.py — Ejecucion de tareas de reporte de los agentes.

Extraido de core/orchestrator.py (2026-07-27, Strangler Fig v1.3, orchestrator
incremento 5/N): realizar_tarea (+ _con_datos y _encadenada) -- genera el
reporte estructurado del agente via la cadena de resiliencia (llm_service),
parsea/valida contra ReporteAgente con extraer_json_objeto tolerante, y encadena
al siguiente_agente_id. Mixin de AgentBase: usa self.nombre/modelo/temperatura/
prompt_base/pipeline/siguiente_agente_id (de __init__), self.realizar_tarea
(auto-ref de _encadenada) y self._contexto_harnesses (queda en AgentBase).
Escribe los canales laterales self.ultimo_proveedor_llm/ultimo_tokens_llm.
Cubierto por tests/audit, harnesses/test_memoria_en_realizar_tarea,
resilience/test_llm_fallback, scale/test_paralelo_controlado.
"""
import json
import logging

from pydantic import ValidationError

from data.middleware import consultar_datos_seguros
from core.schemas import ReporteAgente, extraer_json_objeto
import core.reporter as reporter

# Logger bajo "core.orchestrator" (no __name__): el codigo extraido de
# core/orchestrator.py siempre logueo ahi; dashboards y auditoria forense
# filtran por ese nombre (2026-07-27, contrato operacional preservado).
logger = logging.getLogger("core.orchestrator")


class AgentTasksMixin:
    """Ejecucion de tareas de reporte (ver core/orchestrator.py)."""

    async def realizar_tarea_con_datos(self, datos_texto: str) -> dict | None:
        """Analiza texto externo (CSV, Excel exportado, etc.) con el agente."""
        import re as _re
        # Limpiar artefactos de Excel antes de enviar al LLM
        limpio = datos_texto
        limpio = _re.sub(r"#[¡!]?DIV/0[!]?", "N/D", limpio)
        limpio = _re.sub(r"#[A-Z/!¡]+", "N/D", limpio)
        limpio = limpio[:16_000]
        return await self.realizar_tarea("analisis_externo", _datos_override=limpio)

    async def realizar_tarea(self, tarea: str,
                             _datos_override: str | dict | None = None,
                             user_id: str = "operador_local") -> dict | None:
        datos    = _datos_override if _datos_override is not None else consultar_datos_seguros(f"LEER {tarea}")
        es_externo = isinstance(datos, str) and tarea in ("analisis_externo", "custom") or \
                     (isinstance(datos, dict) and datos.get("_es_texto_externo"))

        rol = f"{self.prompt_base}\n\n" if self.prompt_base else ""

        REGLA_IDIOMA = (
            "REGLA ABSOLUTA DE IDIOMA: Responde TODO en español. "
            "Los nombres de KPIs, columnas de tabla, títulos, resumen y evidencia "
            "deben estar en español. NUNCA uses inglés. "
            "Ejemplo correcto: 'Presupuesto Total', 'Monto Gastado', 'Porcentaje Ejecutado'. "
            "Ejemplo INCORRECTO: 'Total Budget', 'Amount Spent', 'Percentage'. "
        )

        if es_externo:
            datos_str = datos if isinstance(datos, str) else datos.get("_corpus", "")
            instruccion = (
                f"{rol}"
                f"{REGLA_IDIOMA}\n\n"
                "Eres un analista experto. Analiza el siguiente documento y extrae en ESPAÑOL:\n"
                "1) Un resumen ejecutivo claro y detallado en español.\n"
                "2) Los KPIs más importantes: totales, subtotales, porcentajes, variaciones (nombres en español).\n"
                "3) Una tabla con las partidas principales y sus valores (encabezados en español).\n"
                "4) Evidencia: para cada KPI, cita el valor exacto del documento.\n\n"
                f"DOCUMENTO:\n{datos_str}\n\n"
                "Responde ÚNICAMENTE en JSON válido. Todos los textos en español:\n"
                '{"resumen": "texto en español...", '
                '"kpis": {"Nombre KPI en Español": "valor"}, '
                '"tabla": [["Partida","Presupuesto","Gastado","Restante"], ["valor1","valor2","valor3","valor4"]], '
                '"evidencia": {"Nombre KPI en Español": "cita exacta del documento"}}'
            )
        else:
            instruccion = (
                f"{rol}"
                f"{REGLA_IDIOMA}\n\n"
                f"Analiza: {datos}. "
                "Responde ÚNICAMENTE en JSON válido. Todos los textos en español. "
                "RESTRICCION: en 'evidencia' cita el valor EXACTO de los datos originales. "
                'Estructura: {"resumen": "texto en español", '
                '"kpis": {"Nombre KPI en español": "valor"}, '
                '"tabla": [["Columna1","Columna2"], ["valor1","valor2"]], '
                '"evidencia": {"Nombre KPI en español": "fuente exacta del dato"}}'
            )

        raw_data = datos if isinstance(datos, dict) else {"_corpus": str(datos), "_es_texto_externo": True}

        # Tuberia de datos visible (2026-07-19): contenido EXACTO que recibe
        # este agente como entrada — permite verificar en sistema.log que la
        # distribucion de telemetria/datos no llega vacia (colapso Opcion 23).
        logger.info(
            "DATOS_ENTRADA agente='%s' tarea='%s' datos=%s",
            self.nombre, tarea,
            json.dumps(raw_data, ensure_ascii=False, default=str)[:4000],
            extra={"agente": self.nombre, "tarea": tarea},
        )

        # HATs (ADR-0009/0010, 2026-07-20): memoria semantica de auditorias
        # previas. Antes _contexto_harnesses() solo se invocaba desde
        # chat_libre/chat_con_herramientas — jamas desde este metodo batch,
        # que es el que usan los 22 agentes de la Opcion Paralelo. Un agente
        # con "harnesses": ["memoria"] en config.json ahora SI recupera
        # contexto relacionado de auditoria_ia para su analisis actual.
        harness_ctx = await self._contexto_harnesses(
            json.dumps(raw_data, ensure_ascii=False, default=str)[:2000],
            self.nombre, user_id,
        )
        instruccion = f"{instruccion}{harness_ctx}"

        # ── Bucle de auto-corrección: hasta 3 intentos (cloud) / 1 (Ollama) ───
        # Ollama (2026-07-30, Modo Faena CPU): hasta 600s POR LLAMADA
        # (LATENCIA_MAX_POR_PROVEEDOR={"ollama":600}, llm_service.py). Con 2
        # intentos, 2×600s (=1200s) DESBORDABAN el watchdog externo
        # timeout_tarea_s=650 (engine.py, asyncio.wait_for) -> el agente moria
        # a mitad del 2do intento ("Gestor Logistico descartado por timeout").
        # SOBERANIA OPERATIVA v1.3-GOLD: con Ollama se hace UNA sola pasada
        # (MAX_INTENTOS_OLLAMA=1) para que el ExecutionTimeout de 650s sea el
        # UNICO watchdog activo y ningun reintento local pueda desbordarlo. El
        # parche anti-alucinacion de los prompts ("Dato No Disponible") hace que
        # esa unica pasada ya valide schema+GroundingGuard. Los proveedores
        # cloud (rapidos) conservan las 3 pasadas de auto-correccion.
        instruccion_actual = instruccion
        MAX_INTENTOS        = 3
        MAX_INTENTOS_OLLAMA = 1
        limite_intentos      = MAX_INTENTOS   # se ajusta tras la 1ra respuesta real

        for intento in range(1, MAX_INTENTOS + 1):
            # Llamar al modelo de IA -- via la cadena de resiliencia (Fase
            # 19, ADR-0017). Antes: un 429/503 del proveedor configurado
            # devolvia un _api_error pidiendole al usuario que reconfigure
            # otro proveedor A MANO. Ahora la cadena salta automaticamente
            # al siguiente proveedor sano; solo queda _api_error si TODA la
            # cadena, incluido el mock final, falla -- un bug real.
            from core.services.llm_service import llm_service
            try:
                resultado_llm = await llm_service.generar(
                    instruccion_actual, temperatura=self.temperatura,
                    modelo_preferido=self.modelo,
                )
            except Exception as exc_rt:
                return {"_api_error": True, "_api_msg": f"Error de API: {str(exc_rt)[:120]}"}

            respuesta_raw = resultado_llm["texto"]
            self.ultimo_proveedor_llm = resultado_llm["proveedor"]
            if self.ultimo_proveedor_llm == "ollama":
                limite_intentos = min(limite_intentos, MAX_INTENTOS_OLLAMA)
            self.ultimo_tokens_llm    = {
                "tokens_entrada": resultado_llm.get("tokens_entrada"),
                "tokens_salida":  resultado_llm.get("tokens_salida"),
                "tokens_total":   resultado_llm.get("tokens_total"),
                "tokens_exactos": resultado_llm.get("tokens_exactos", False),
            }

            texto_limpio = extraer_json_objeto(respuesta_raw)   # tolera prosa/fences (Llama 3.2)

            # Parsear JSON
            try:
                raw = json.loads(texto_limpio)
            except json.JSONDecodeError as e:
                if intento < limite_intentos:
                    logger.warning("Agente '%s' intento %d: JSON inválido, reintentando", self.nombre, intento)
                    instruccion_actual = (
                        instruccion + f"\n\nCORRECCIÓN NECESARIA (intento {intento}/{limite_intentos}): "
                        f"Tu respuesta anterior no era JSON válido: {e}. "
                        "Responde ÚNICAMENTE con JSON válido, sin texto adicional."
                    )
                    continue
                logger.error("Agente '%s' — JSON inválido tras %d intentos", self.nombre, limite_intentos,
                             extra={"agente": self.nombre, "error_type": "json_decode"})
                return None

            # Validar schema
            try:
                reporte = ReporteAgente.model_validate(raw)
            except ValidationError as e:
                if intento < limite_intentos:
                    logger.warning("Agente '%s' intento %d: schema inválido, corrigiendo", self.nombre, intento)
                    campos_faltantes = [err["loc"][0] for err in e.errors() if err.get("loc")]
                    instruccion_actual = (
                        instruccion + f"\n\nCORRECCIÓN (intento {intento}/{limite_intentos}): "
                        f"El JSON no cumple el schema requerido. Campos con error: {campos_faltantes}. "
                        "Asegúrate de incluir: resumen (string), kpis (dict no vacío), "
                        "tabla (lista con encabezados), evidencia (dict con fuentes)."
                    )
                    continue
                campos_finales = [str(err.get("loc", "?")) for err in e.errors()]
                logger.error(
                    "Agente '%s' — schema inválido tras %d intentos. Campos: %s",
                    self.nombre, limite_intentos, campos_finales,
                    extra={"agente": self.nombre, "error_type": "schema_validation"},
                )
                return None

            # Ejecutar pipeline con auto-corrección
            resultado = await self.pipeline.procesar_con_razon(
                raw_data=raw_data,
                respuesta_texto=texto_limpio,
                reporte=reporte.model_dump(),
            )

            # Si el pipeline rechaza, construir prompt de corrección
            if isinstance(resultado, dict) and resultado.get("_abortado"):
                guardrail = resultado.get("_guardrail", "Pipeline")
                razon     = resultado.get("_razon", "Error de validación")

                if intento < limite_intentos:
                    logger.warning("Agente '%s' intento %d: %s rechazó — autocorrigiendo",
                                   self.nombre, intento, guardrail,
                                   extra={"agente": self.nombre, "guardrail": guardrail})
                    instruccion_actual = (
                        instruccion + f"\n\nCORRECCIÓN AUTOMÁTICA (intento {intento}/{limite_intentos}): "
                        f"El guardrail '{guardrail}' rechazó tu respuesta.\n"
                        f"Razón exacta: {razon}\n"
                        "Corrige estos problemas específicos y genera una nueva respuesta JSON."
                    )
                    continue
                else:
                    logger.error("Agente '%s' — pipeline abortó tras %d intentos de corrección",
                                 self.nombre, limite_intentos,
                                 extra={"agente": self.nombre, "error_type": "pipeline_abort",
                                        "status": "abortado", "motivo": razon})
                    return None

            # Pipeline pasó correctamente
            if resultado is not None:
                if intento > 1:
                    logger.info("Agente '%s' — tarea completada tras %d intentos de auto-corrección",
                                self.nombre, intento,
                                extra={"agente": self.nombre, "intentos": intento, "status": "ok_corregido"})
                else:
                    logger.info("Agente '%s' — tarea completada",
                                self.nombre,
                                extra={"agente": self.nombre, "modelo": self.modelo, "status": "ok"})
                reporter.guardar_reporte(self.nombre, resultado)
                try:
                    reporter.guardar_reporte_pdf(self.nombre, resultado)
                except Exception:
                    logger.exception(
                        "No se pudo generar el PDF del reporte (se conserva el .md)",
                        extra={"agente": self.nombre},
                    )
                return resultado

        return None

    async def realizar_tarea_encadenada(
        self,
        tarea: str,
        orquestador: "Orquestador",
        profundidad: int = 0,
        max_profundidad: int = 5,
    ) -> dict | None:
        """
        Ejecuta la tarea y, si el agente tiene `siguiente_agente_id` configurado,
        pasa el resultado como contexto enriquecido al siguiente agente.

        Protección anti-bucle: limita la cadena a `max_profundidad` saltos.
        El resumen del agente actual se inyecta al prompt del siguiente.
        """
        resultado = await self.realizar_tarea(tarea)

        if resultado is None or not self.siguiente_agente_id:
            return resultado

        if profundidad >= max_profundidad:
            logger.warning(
                "Cadena de agentes cortada: profundidad maxima (%d) alcanzada.",
                max_profundidad,
                extra={"agente": self.nombre, "siguiente": self.siguiente_agente_id},
            )
            return resultado

        siguiente = orquestador.agentes.get(self.siguiente_agente_id)
        if siguiente is None:
            logger.error(
                "Encadenamiento fallido: agente '%s' no encontrado.",
                self.siguiente_agente_id,
                extra={"agente_origen": self.nombre},
            )
            return resultado

        # Enriquecer el contexto: el resultado actual alimenta al siguiente
        resumen_previo = resultado.get("resumen", "")
        tarea_enriquecida = (
            f"{tarea}\n\n"
            f"CONTEXTO DEL AGENTE PREVIO ({self.nombre}):\n{resumen_previo}"
        )

        logger.info(
            "Encadenando '%s' -> '%s' (profundidad %d).",
            self.nombre, siguiente.nombre, profundidad + 1,
            extra={"cadena": f"{self.nombre}->{siguiente.nombre}"},
        )

        return await siguiente.realizar_tarea_encadenada(
            tarea_enriquecida, orquestador,
            profundidad=profundidad + 1,
            max_profundidad=max_profundidad,
        )
