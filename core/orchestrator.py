import asyncio
import json
import logging
import os
from google import genai

from pydantic import ValidationError
from data.middleware import consultar_datos_seguros
from core.schemas import ReporteAgente, extraer_json_objeto
from core.pipeline import PipelineProcessor
from core.command_bridge import CommandBridge
import core.reporter as reporter
from core.orchestrator_chat_tools import AgentChatToolsMixin
from core.orchestrator_chat_tools_stream import AgentChatToolsStreamMixin
from core.orchestrator_engine import OrquestadorEngineMixin
from core.orchestrator_registry import OrquestadorRegistryMixin
from core.orchestrator_bridge import OrquestadorBridgeMixin

logger = logging.getLogger(__name__)

_MODELO_FALLBACK      = "models/gemini-2.5-flash"
_TEMPERATURA_FALLBACK = 0.4


class AgentBase(AgentChatToolsMixin, AgentChatToolsStreamMixin):
    """
    Agente individual configurable por parámetros en config.json.

    Parámetros dinámicos (todos opcionales, con fallback):
      modelo      — modelo de Gemini
      temperatura — creatividad (0.0 preciso / 1.0 creativo)
      idioma      — directriz de idioma inyectada en el prompt
      prompt_base — instrucción de rol del agente
    """

    def __init__(self, config: dict, client: genai.Client, model_name_global: str):
        self.nombre      = config["nombre"]
        self.tipo_ia     = config["tipo_ia"]
        self.client      = client
        self._aplicar_config(config, model_name_global)
        self.pipeline    = PipelineProcessor(nombre_agente=self.nombre)

        logger.info(
            "Agente inicializado",
            extra={
                "agente":      self.nombre,
                "modelo":      self.modelo,
                "temperatura": self.temperatura,
                "idioma":      self.idioma,
            },
        )

    def _aplicar_config(self, config: dict, fallback_modelo: str = "") -> None:
        """Aplica (o re-aplica) parámetros dinámicos desde un dict de config."""
        self.modelo             = config.get("modelo",             fallback_modelo or _MODELO_FALLBACK)
        self.temperatura        = float(config.get("temperatura",  _TEMPERATURA_FALLBACK))
        self.prompt_base        = config.get("prompt_base",        "").strip()
        self.idioma             = config.get("idioma",             "español").strip()
        self.area               = config.get("area",               "General").strip().title()
        # Encadenamiento: ID del siguiente agente al que pasar el resultado
        self.siguiente_agente_id = config.get("siguiente_agente_id", None)
        # HATs (ADR-0009): capacidades componibles atachadas por config.
        self.harnesses = list(config.get("harnesses", []))
        # Ultimo contexto de HATs inyectado (ADR-0014): canal lateral de
        # solo lectura para que orchestrator_service audite el contexto
        # RECUPERADO, no solo el mensaje del usuario, sin cambiar la firma
        # de retorno de los metodos de chat.
        self.ultimo_contexto_hats = ""
        # Fase 19 (ADR-0017): mismo patron de canal lateral -- que proveedor
        # respondio REALMENTE (puede diferir de self.modelo si hubo
        # fallback) y cuantos tokens exactos/estimados consumio la ultima
        # llamada, para que orchestrator_service audite la cadena de
        # resiliencia sin cambiar la firma de retorno de los metodos de chat.
        self.ultimo_proveedor_llm = ""
        self.ultimo_tokens_llm: dict = {}

    def reload_config(self, config: dict) -> bool:
        """
        Actualiza los parámetros del agente en caliente con validación Pydantic.

        Flujo:
          1. Snapshot del estado actual (garantía de rollback).
          2. Construir el dict completo rellenando ausentes con valores actuales.
          3. Validar contra AgentConfig.
          4a. Fallo  → log de error + return False (rollback implícito: no se toca nada).
          4b. Éxito  → aplicar parámetros validados + log de diff + return True.

        Retorna True si el reload fue aplicado, False si fue rechazado.
        """
        from pydantic import ValidationError
        from core.schemas import AgentConfig

        # ── 1. Snapshot ────────────────────────────────────────────────────────
        snapshot = {
            "modelo":      self.modelo,
            "temperatura": self.temperatura,
            "prompt_base": self.prompt_base,
            "idioma":      self.idioma,
        }

        # ── 2. Construir config completa (fallos parciales usan el valor actual) ─
        config_candidato = {
            "id":          config.get("id",          ""),
            "nombre":      self.nombre,
            "tipo_ia":     self.tipo_ia,
            "area":        config.get("area",        self.area),
            "modelo":      config.get("modelo",      self.modelo),
            "temperatura": config.get("temperatura", self.temperatura),
            "idioma":      config.get("idioma",      self.idioma),
            "prompt_base": config.get("prompt_base", self.prompt_base),
        }

        # ── 3. Validación Pydantic ─────────────────────────────────────────────
        try:
            validado = AgentConfig.model_validate(config_candidato)
        except ValidationError as e:
            logger.error(
                "RELOAD_CONFIG rechazado para '%s' — validacion fallida. "
                "Configuracion anterior mantenida (rollback).",
                self.nombre,
                extra={
                    "agente":            self.nombre,
                    "config_rechazada":  config_candidato,
                    "errores_pydantic":  [err["msg"] for err in e.errors()],
                    "rollback_aplicado": True,
                },
            )
            return False

        # ── 4b. Aplicar parámetros validados ──────────────────────────────────
        self.modelo      = validado.modelo
        self.temperatura = validado.temperatura
        self.prompt_base = validado.prompt_base
        self.idioma      = validado.idioma

        logger.info(
            "RELOAD_CONFIG aplicado para '%s'.",
            self.nombre,
            extra={
                "agente":           self.nombre,
                "modelo_antes":     snapshot["modelo"],
                "modelo_despues":   self.modelo,
                "temp_antes":       snapshot["temperatura"],
                "temp_despues":     self.temperatura,
                "idioma_antes":     snapshot["idioma"],
                "idioma_despues":   self.idioma,
                "rollback_aplicado": False,
            },
        )
        return True

    async def _contexto_harnesses(self, mensaje: str, agente_id_clave: str,
                                   user_id: str = "anonimo") -> str:
        """Contexto extra best-effort de los HATs configurados (ADR-0009/0010)."""
        if not self.harnesses:
            self.ultimo_contexto_hats = ""
            return ""
        try:
            from core.services.harness_service import harness_service
            extra = await harness_service.aplicar_pre(
                self.harnesses, agente_id_clave or self.nombre, mensaje, user_id=user_id,
            )
            self.ultimo_contexto_hats = extra or ""
            return f"\n\n{extra}\n" if extra else ""
        except Exception as exc:
            self.ultimo_contexto_hats = ""
            logger.warning("HATs: contexto no aplicado para '%s' (%s)",
                           self.nombre, exc, extra={"agente": self.nombre})
            return ""

    async def _criticar_respuesta(self, mensaje: str, respuesta: str,
                                   agente_id_clave: str, user_id: str = "anonimo") -> str:
        """Post-hook best-effort de autocrítica (CritiqueHarness, ADR-0010)."""
        if not self.harnesses:
            return respuesta
        try:
            from core.services.harness_service import harness_service
            return await harness_service.aplicar_post(
                self.harnesses, agente_id_clave or self.nombre, respuesta,
                mensaje=mensaje, user_id=user_id, modelo=self.modelo,
            )
        except Exception as exc:
            logger.warning("HATs: autocritica no aplicada para '%s' (%s)",
                           self.nombre, exc, extra={"agente": self.nombre})
            return respuesta

    async def chat_libre(
        self,
        mensaje: str,
        contexto_archivo: str = "",
        sesion_id: str = "default",
        agente_id_clave: str = "",
        user_id: str = "anonimo",
    ) -> str:
        """
        Responde en modo conversacional libre con memoria persistente.
        La memoria guarda los últimos N mensajes en SQLite y los inyecta
        al prompt para que el agente mantenga el hilo de la conversación.
        """
        from core import memory as _mem

        aid = agente_id_clave or self.nombre

        # 1. Guardar el mensaje del usuario en memoria
        _mem.guardar_mensaje(aid, sesion_id, "usuario", mensaje)

        # 2. Recuperar contexto de la conversación anterior
        historial_ctx = _mem.get_contexto(aid, sesion_id, n_mensajes=8)

        # 3. Construir el prompt con memoria + contexto de archivo
        rol         = f"{self.prompt_base}\n\n" if self.prompt_base else ""
        archivo_ctx = (f"\n\nContenido del archivo adjunto:\n{contexto_archivo[:6000]}\n"
                       if contexto_archivo else "")
        memoria_ctx = f"\n\n{historial_ctx}\n" if historial_ctx else ""
        harness_ctx = await self._contexto_harnesses(mensaje, aid, user_id)

        prompt = (
            f"{rol}"
            f"Responde siempre en {self.idioma}. "
            f"Eres {self.nombre}, agente de área {self.area}. "
            f"Responde de forma clara, directa y coherente con el historial."
            f"{memoria_ctx}{harness_ctx}{archivo_ctx}\n\n"
            f"Usuario: {mensaje}"
        )

        # 4. Generar respuesta -- via la cadena de resiliencia (Fase 19,
        # ADR-0017): self.modelo se intenta primero (eleccion del agente
        # respetada), y si falla (429/503/timeout/red) la cadena salta
        # automaticamente al siguiente proveedor sano en vez de devolver un
        # mensaje pidiendole al usuario que reconfigure algo a mano. Solo
        # lanza si TODA la cadena, incluido el mock final, falla -- un bug
        # real, no un fallo de proveedor.
        from core.services.llm_service import llm_service
        from core.telemetry_otel import medir_paso
        try:
            with medir_paso("llm.generar", agente=self.nombre, modelo=self.modelo):
                resultado_llm = await llm_service.generar(
                    prompt, temperatura=self.temperatura, modelo_preferido=self.modelo,
                )
        except Exception as exc:
            logger.error("chat_libre '%s': cadena de resiliencia agotada (%s)",
                         self.nombre, exc, extra={"agente": self.nombre, "error_type": "chat_api"})
            return f"Error al procesar la solicitud: {exc}"

        respuesta = resultado_llm["texto"]
        self.ultimo_proveedor_llm = resultado_llm["proveedor"]
        self.ultimo_tokens_llm    = {
            "tokens_entrada": resultado_llm.get("tokens_entrada"),
            "tokens_salida":  resultado_llm.get("tokens_salida"),
            "tokens_total":   resultado_llm.get("tokens_total"),
            "tokens_exactos": resultado_llm.get("tokens_exactos", False),
        }

        # 5. Autocritica (CritiqueHarness, ADR-0010) + guardar en memoria
        respuesta = await self._criticar_respuesta(mensaje, respuesta, aid, user_id)
        _mem.guardar_mensaje(aid, sesion_id, "agente", respuesta)
        return respuesta

    async def chat_libre_stream(
        self,
        mensaje: str,
        contexto_archivo: str = "",
        sesion_id: str = "default",
        agente_id_clave: str = "",
        user_id: str = "anonimo",
    ):
        """
        Versión streaming de chat_libre.
        Devuelve chunks de texto conforme Groq los genera.
        Cada chunk es un string parcial de la respuesta.
        """
        from core.providers import generate_stream
        from core import memory as _mem

        aid = agente_id_clave or self.nombre
        _mem.guardar_mensaje(aid, sesion_id, "usuario", mensaje)

        historial_ctx = _mem.get_contexto(aid, sesion_id, n_mensajes=8)
        rol           = f"{self.prompt_base}\n\n" if self.prompt_base else ""
        archivo_ctx   = (f"\n\nContenido del archivo adjunto:\n{contexto_archivo[:6000]}\n"
                         if contexto_archivo else "")
        memoria_ctx   = f"\n\n{historial_ctx}\n" if historial_ctx else ""
        harness_ctx   = await self._contexto_harnesses(mensaje, aid, user_id)

        prompt = (
            f"{rol}"
            f"Responde siempre en {self.idioma}. "
            f"Eres {self.nombre}, agente de área {self.area}. "
            f"Responde de forma clara, directa y coherente con el historial."
            f"{memoria_ctx}{harness_ctx}{archivo_ctx}\n\n"
            f"Usuario: {mensaje}"
        )

        texto_completo = ""
        try:
            async for chunk in generate_stream(self.modelo, prompt, self.temperatura):
                texto_completo += chunk
                yield chunk
        except Exception as exc:
            msg = str(exc)
            if "429" in msg or "quota" in msg.lower():
                yield "⚠️ Cuota agotada. Configura Groq en Sistema → Proveedores IA."
            elif "503" in msg:
                yield "⚠️ Servicio saturado. Intenta de nuevo en unos segundos."
            else:
                yield f"⚠️ Error: {exc}"
            return

        # Guardar respuesta completa en memoria
        if texto_completo:
            _mem.guardar_mensaje(aid, sesion_id, "agente", texto_completo)

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

        # ── Bucle de auto-corrección: hasta 3 intentos ────────────────────────
        # Ollama (2026-07-20, hallazgo real en vivo): hasta 300s POR LLAMADA
        # (LATENCIA_MAX_POR_PROVEEDOR, llm_service.py) -- 3 intentos completos
        # pueden exceder timeout_tarea_s externo antes de que el 2do/3er
        # intento termine ("Gestor Logistico" quedo descartado por timeout a
        # mitad del intento 2). Con Ollama respondiendo, el bucle se rinde en
        # MAX_INTENTOS_OLLAMA intentos para dejarle margen real al timeout
        # externo, en vez de agotar 3 intentos completos casi seguro.
        instruccion_actual = instruccion
        MAX_INTENTOS        = 3
        MAX_INTENTOS_OLLAMA = 2
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


class Orquestador(OrquestadorEngineMixin, OrquestadorRegistryMixin, OrquestadorBridgeMixin):
    """
    Gestiona los agentes y escucha comandos del CommandBridge.

    El CommandBridge es opcional: si no se pasa, el sistema funciona
    igual que antes sin soporte para recarga dinámica.
    """

    def __init__(
        self,
        config_path: str,
        client: genai.Client,
        model_name_global: str,
        bridge: CommandBridge | None = None,
    ):
        self._config_path       = config_path
        self._model_name_global = model_name_global
        self._bridge            = bridge
        self._client            = client

        with open(config_path, "r", encoding="utf-8") as f:
            self.config = json.load(f)

        self.agentes = {
            a["id"]: AgentBase(a, client, model_name_global)
            for a in self.config["agents"]
        }

        # Sandbox Zero-Trust (Fase 7): cualquier subproceso disparado por un agente
        # pasa por este runner (shell prohibida, entorno minimo sin API keys,
        # limites de tiempo/memoria). Ver core/services/sandbox_service.py.
        from core.services.sandbox_service import SubprocessRunner
        self.sandbox = SubprocessRunner()

        os.makedirs("reportes", exist_ok=True)
