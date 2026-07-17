"""
core/services/harness_service.py — Motor de Harness Attachments (ADR-0009/0010).

Resuelve la lista `harnesses: []` del config de cada agente a instancias de
HAT (memoria, autocrítica, ...) y aplica sus hooks alrededor de la llamada
al LLM. Best-effort estricto: un harness que falla se loguea y se ignora —
jamás rompe la conversación del usuario (mismo principio que audit_service,
ADR-0007).

Aislamiento de memoria (ADR-0010): ContextHarness filtra SIEMPRE por
user_id — sin user_id no hay memoria (fail-closed), nunca se degrada a
buscar solo por agente_id. Es la garantía real: un Operador A JAMÁS recibe
recuerdos sembrados por un Operador B, aunque compartan el mismo agente.
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

from core.vector_store import PROYECTO_GLOBAL

PRESUPUESTO_TOKENS_DEFAULT = 400   # ~1600 chars (tokens ~= chars/4, ADR-0007)
CANDIDATOS_MAX = 30                 # trazas de auditoria a considerar por consulta


class ContextHarness:
    """
    HAT de Memoria: RAG sobre la Memoria Hermes persistente (ADR-0023) con
    la auditoría como complemento de transición.

    En el hook 'pre' recupera recuerdos de sesiones PASADAS del mismo
    usuario (la memoria de la sesión en curso ya la cubre core/memory.py)
    por similitud vectorial contra el mensaje entrante, y los inyecta tras
    la poda de contexto dinámico (podar_fragmentos: relevancia + no
    redundancia + presupuesto de tokens, FinOps).

    ADR-0010/0023: user_id y proyecto_id son OBLIGATORIOS en Hermes
    (fail-closed). Sin user_id no hay memoria de ninguna fuente — nunca se
    cae de vuelta a "todos los usuarios de este agente".
    """

    nombre = "memoria"

    def __init__(self) -> None:
        self._agente_id: str | None = None
        self._presupuesto = PRESUPUESTO_TOKENS_DEFAULT

    def attach(self, agente_id: str, config: dict) -> None:
        self._agente_id = agente_id
        self._presupuesto = int(config.get("presupuesto_tokens_contexto", PRESUPUESTO_TOKENS_DEFAULT))

    def detach(self) -> None:
        self._agente_id = None

    def _recuerdos_hermes(self, mensaje: str, agente_id: str,
                          user_id: str, proyecto_id: str) -> list[tuple[str, float]]:
        """Memoria vectorial persistente (sobrevive reinicios y sesiones)."""
        from core.vector_store import hermes
        import time as _time
        resultados = hermes().buscar(
            mensaje, user_id=user_id, proyecto_id=proyecto_id,
            agente_id=agente_id or None, top_k=8,
        )
        fragmentos = []
        for r in resultados:
            dias = max(0, int((_time.time() - r["ts"]) / 86400))
            cuando = f"hace {dias} dia(s)" if dias else "hoy"
            fragmentos.append(
                (f"- Recuerdo ({cuando}): {r['texto'][:400]}", r["similitud"]))
        return fragmentos

    def _recuerdos_auditoria(self, mensaje: str, agente_id: str,
                             user_id: str) -> list[tuple[str, float]]:
        """Complemento de transición: TF-IDF efímero sobre auditoria_ia."""
        from core.services.audit_service import consultar
        from core.embeddings import recuperar_contexto_similar

        trazas = consultar(agente_id=agente_id, user_id=user_id, limit=CANDIDATOS_MAX)
        trazas = [t for t in trazas if t.get("prompt") and t.get("respuesta")]
        if not trazas:
            return []
        candidatos = [f"{t['prompt']} {t['respuesta']}" for t in trazas]
        ranking = recuperar_contexto_similar(mensaje, candidatos, top_k=5)
        return [
            (f"- Antes preguntaste: \"{trazas[i]['prompt'][:200]}\" "
             f"-> respondí: \"{trazas[i]['respuesta'][:200]}\"", sim)
            for i, sim in ranking
        ]

    async def apply_hooks(self, fase: str, contexto: dict) -> dict:
        if fase != "pre":
            return contexto   # ContextHarness no hace post-procesamiento

        mensaje   = contexto.get("mensaje", "")
        agente_id = self._agente_id or contexto.get("agente_id", "")
        user_id   = contexto.get("user_id")
        proyecto_id = contexto.get("proyecto_id") or PROYECTO_GLOBAL
        if not mensaje or not agente_id:
            return contexto
        if not user_id:
            logger.warning("ContextHarness: sin user_id en el contexto — "
                            "memoria denegada (fail-closed, ADR-0010)")
            return contexto

        from core.embeddings import podar_fragmentos

        # Hermes primero (persistente); auditoría como complemento. Se
        # concatenan en ese orden — podar_fragmentos elimina redundancias
        # (una interacción reciente suele estar en ambas fuentes).
        candidatos = self._recuerdos_hermes(mensaje, agente_id, user_id, proyecto_id)
        candidatos += self._recuerdos_auditoria(mensaje, agente_id, user_id)
        fragmentos = podar_fragmentos(candidatos, self._presupuesto)

        if fragmentos:
            contexto["memoria_semantica"] = (
                "Recuerdos relevantes de conversaciones anteriores:\n"
                + "\n".join(fragmentos)
            )
        return contexto


class SkillHarness:
    """
    HAT de Habilidades (ADR-0023): recupera de la Memoria Hermes las
    recetas (tipo="habilidad") relevantes al mensaje entrante y las
    inyecta como procedimiento sugerido. Scope estricto user_id +
    proyecto_id — las habilidades son know-how del usuario que las
    aprendió, jamás se comparten entre usuarios (SEMANTIC-PRIVACY).
    """

    nombre = "habilidades"

    def __init__(self) -> None:
        self._agente_id: str | None = None

    def attach(self, agente_id: str, config: dict) -> None:
        self._agente_id = agente_id

    def detach(self) -> None:
        self._agente_id = None

    async def apply_hooks(self, fase: str, contexto: dict) -> dict:
        if fase != "pre":
            return contexto

        mensaje = contexto.get("mensaje", "")
        user_id = contexto.get("user_id")
        proyecto_id = contexto.get("proyecto_id") or PROYECTO_GLOBAL
        if not mensaje or not user_id:
            return contexto   # fail-closed: sin user_id no hay habilidades

        from core.services import skill_service
        from core.vector_store import hermes

        coincidencias = hermes().buscar(
            mensaje, user_id=user_id, proyecto_id=proyecto_id,
            tipo="habilidad", top_k=2, umbral=0.15,
        )
        piezas: list[str] = []
        for c in coincidencias:
            # El texto indexado empieza "Habilidad: <nombre>. ..." — se
            # recupera la receta completa desde disco por su nombre.
            for receta in skill_service.listar_habilidades(user_id):
                if receta.get("nombre") and receta["nombre"] in c["texto"]:
                    piezas.append(skill_service.como_prompt(receta))
                    break
        if piezas:
            contexto["habilidades"] = (
                "Habilidades aprendidas aplicables a esta tarea:\n"
                + "\n".join(dict.fromkeys(piezas))   # dedupe conservando orden
            )
        return contexto


# Patrones de violación de seguridad industrial (denylist, ADR-0010). No
# pretende ser exhaustivo — es una primera línea determinista para bloquear
# los casos más obvios antes de intentar una regeneración corregida.
_PATRONES_INSEGUROS = [
    re.compile(r"desactiv\w*\s+(el\s+)?(limitador|interlock|parada\s+de\s+emergencia|"
               r"sistema\s+de\s+seguridad)", re.I),
    re.compile(r"ignora\w*\s+(las?\s+)?(normas?|protocolos?)\s+de\s+seguridad", re.I),
    re.compile(r"sin\s+(supervisi[oó]n|autorizaci[oó]n)\s+(puedes|puede|procede)", re.I),
    re.compile(r"puentea\w*\s+(el\s+)?(sensor|interlock|paro)", re.I),
]

_RESPUESTA_BLOQUEADA = (
    "No puedo entregar esa respuesta tal como fue generada: la autocrítica "
    "detectó una posible violación de seguridad industrial o una respuesta "
    "vacía/inconsistente, y el intento de regeneración no la corrigió. "
    "Contacta a un supervisor antes de proceder."
)


def _evaluar_respuesta(respuesta: str) -> str:
    """'aprobado' o 'rechazado' — regla determinista, sin llamar al LLM."""
    if not respuesta or len(respuesta.strip()) < 3:
        return "rechazado"
    if any(p.search(respuesta) for p in _PATRONES_INSEGUROS):
        return "rechazado"
    return "aprobado"


class CritiqueHarness:
    """
    HAT de Autocrítica (post-hook): revisa la respuesta del LLM ANTES de
    entregarla al usuario, buscando inconsistencias lógicas o violaciones de
    seguridad industrial. Si el veredicto es negativo, solicita una
    regeneración corregida; si la regeneración también falla el chequeo, se
    bloquea con un mensaje seguro en vez de entregar la respuesta original.
    """

    nombre = "autocritica"

    def __init__(self) -> None:
        self._agente_id: str | None = None

    def attach(self, agente_id: str, config: dict) -> None:
        self._agente_id = agente_id

    def detach(self) -> None:
        self._agente_id = None

    async def apply_hooks(self, fase: str, contexto: dict) -> dict:
        if fase != "post":
            return contexto   # CritiqueHarness no hace pre-procesamiento

        respuesta = contexto.get("respuesta", "") or ""
        if _evaluar_respuesta(respuesta) == "aprobado":
            contexto["veredicto_critica"] = "aprobado"
            return contexto

        contexto["veredicto_critica"] = "rechazado"
        regenerada = await self._regenerar(contexto)
        if regenerada and _evaluar_respuesta(regenerada) == "aprobado":
            contexto["respuesta"]         = regenerada
            contexto["veredicto_critica"] = "regenerado"
        else:
            contexto["respuesta"]         = _RESPUESTA_BLOQUEADA
            contexto["veredicto_critica"] = "bloqueado"
        return contexto

    @staticmethod
    async def _regenerar(contexto: dict) -> str | None:
        """
        Segunda pasada al LLM pidiendo una respuesta corregida (best-effort).

        Fase 19 (ADR-0017) [LLM-RESILIENCE]: via llm_service.generar() en
        vez de core.providers.generate directo -- si el proveedor del
        agente esta caido justo cuando se necesita la regeneracion (el peor
        momento para no tener red de seguridad), la cadena de fallback
        igual intenta completarla en vez de rendirse de inmediato.
        """
        try:
            from core.services.llm_service import llm_service
            prompt_correctivo = (
                "La siguiente respuesta a un operador industrial fue rechazada "
                "por autocrítica (posible violación de seguridad o respuesta "
                "vacía/inconsistente). Reescríbela SIN instrucciones inseguras, "
                "priorizando el protocolo de seguridad industrial. Si no es "
                "posible responder con seguridad, indica que se requiere "
                "autorización de un supervisor.\n\n"
                f"Pregunta original: {contexto.get('mensaje', '')}\n"
                f"Respuesta rechazada: {contexto.get('respuesta', '')}\n\n"
                "Respuesta corregida:"
            )
            modelo = contexto.get("modelo") or "mock:agentdesk-demo"
            resultado = await llm_service.generar(
                prompt_correctivo, temperatura=0.2, modelo_preferido=modelo,
            )
            return resultado["texto"]
        except Exception as exc:
            logger.warning("CritiqueHarness: regeneracion fallo (%s)", exc)
            return None


class HarnessService:
    """Resuelve nombres de harness -> instancias y aplica sus hooks best-effort."""

    _REGISTRO: dict[str, type] = {
        "memoria":     ContextHarness,
        "autocritica": CritiqueHarness,
        "habilidades": SkillHarness,
    }

    def _instanciar(self, nombres: list[str]) -> list:
        instancias = []
        for nombre in nombres:
            cls = self._REGISTRO.get(nombre)
            if cls is None:
                logger.warning("HATs: harness desconocido '%s' — ignorado", nombre)
                continue
            instancias.append(cls())
        return instancias

    async def aplicar_pre(
        self, nombres: list[str], agente_id: str, mensaje: str,
        user_id: str = "anonimo", config: dict | None = None,
        proyecto_id: str = PROYECTO_GLOBAL,
    ) -> str:
        """Aplica el hook 'pre' de cada harness configurado; retorna el texto a inyectar."""
        if not nombres:
            return ""
        piezas: list[str] = []
        for harness in self._instanciar(nombres):
            try:
                harness.attach(agente_id, config or {})
                resultado = await harness.apply_hooks(
                    "pre", {"agente_id": agente_id, "mensaje": mensaje,
                            "user_id": user_id, "proyecto_id": proyecto_id},
                )
                for clave in ("memoria_semantica", "habilidades"):
                    extra = resultado.get(clave)
                    if extra:
                        piezas.append(extra)
            except Exception as exc:
                logger.warning("HATs: harness '%s' fallo en pre-hook (%s) — ignorado",
                               getattr(harness, "nombre", "?"), exc)
            finally:
                try:
                    harness.detach()
                except Exception:
                    pass
        return "\n\n".join(piezas)

    async def aplicar_post(
        self, nombres: list[str], agente_id: str, respuesta: str, mensaje: str = "",
        user_id: str = "anonimo", modelo: str = "", config: dict | None = None,
    ) -> str:
        """Aplica el hook 'post' de cada harness configurado (CritiqueHarness, ADR-0010)."""
        if not nombres:
            return respuesta
        actual = respuesta
        for harness in self._instanciar(nombres):
            try:
                harness.attach(agente_id, config or {})
                resultado = await harness.apply_hooks("post", {
                    "agente_id": agente_id, "respuesta": actual, "mensaje": mensaje,
                    "user_id": user_id, "modelo": modelo,
                })
                actual = resultado.get("respuesta", actual)
            except Exception as exc:
                logger.warning("HATs: harness '%s' fallo en post-hook (%s) — ignorado",
                               getattr(harness, "nombre", "?"), exc)
            finally:
                try:
                    harness.detach()
                except Exception:
                    pass
        return actual


harness_service = HarnessService()
