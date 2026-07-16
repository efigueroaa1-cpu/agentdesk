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

PRESUPUESTO_TOKENS_DEFAULT = 400   # ~1600 chars (tokens ~= chars/4, ADR-0007)
CANDIDATOS_MAX = 30                 # trazas de auditoria a considerar por consulta


class ContextHarness:
    """
    HAT de Memoria de Corto Plazo: RAG ligero sobre `auditoria_ia`.

    En el hook 'pre' recupera fragmentos de conversaciones PASADAS del mismo
    agente Y DEL MISMO USUARIO (sesiones distintas a la actual — la memoria
    de sesión en curso ya la cubre core/memory.py) mediante similitud TF-IDF
    contra el mensaje entrante, e inyecta solo los fragmentos relevantes bajo
    un presupuesto de tokens.

    ADR-0010: el filtro por user_id es OBLIGATORIO. Sin un user_id explícito
    en el contexto, no se hace ninguna consulta — nunca se cae de vuelta a
    "todos los usuarios de este agente" como aproximación.
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

    async def apply_hooks(self, fase: str, contexto: dict) -> dict:
        if fase != "pre":
            return contexto   # ContextHarness no hace post-procesamiento

        mensaje   = contexto.get("mensaje", "")
        agente_id = self._agente_id or contexto.get("agente_id", "")
        user_id   = contexto.get("user_id")
        if not mensaje or not agente_id:
            return contexto
        if not user_id:
            logger.warning("ContextHarness: sin user_id en el contexto — "
                            "memoria denegada (fail-closed, ADR-0010)")
            return contexto

        from core.services.audit_service import consultar
        from core.embeddings import recuperar_contexto_similar

        trazas = consultar(agente_id=agente_id, user_id=user_id, limit=CANDIDATOS_MAX)
        trazas = [t for t in trazas if t.get("prompt") and t.get("respuesta")]
        if not trazas:
            return contexto

        candidatos = [f"{t['prompt']} {t['respuesta']}" for t in trazas]
        ranking = recuperar_contexto_similar(mensaje, candidatos, top_k=5)
        if not ranking:
            return contexto

        limite_chars = self._presupuesto * 4
        fragmentos: list[str] = []
        total = 0
        for idx, _sim in ranking:
            t    = trazas[idx]
            frag = (f"- Antes preguntaste: \"{t['prompt'][:200]}\" "
                    f"-> respondí: \"{t['respuesta'][:200]}\"")
            if total + len(frag) > limite_chars:
                break
            fragmentos.append(frag)
            total += len(frag)

        if fragmentos:
            contexto["memoria_semantica"] = (
                "Recuerdos relevantes de conversaciones anteriores:\n"
                + "\n".join(fragmentos)
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
        """Segunda pasada al LLM pidiendo una respuesta corregida (best-effort)."""
        try:
            from core.providers import generate
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
            return await generate(modelo, prompt_correctivo, 0.2)
        except Exception as exc:
            logger.warning("CritiqueHarness: regeneracion fallo (%s)", exc)
            return None


class HarnessService:
    """Resuelve nombres de harness -> instancias y aplica sus hooks best-effort."""

    _REGISTRO: dict[str, type] = {
        "memoria":     ContextHarness,
        "autocritica": CritiqueHarness,
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
    ) -> str:
        """Aplica el hook 'pre' de cada harness configurado; retorna el texto a inyectar."""
        if not nombres:
            return ""
        piezas: list[str] = []
        for harness in self._instanciar(nombres):
            try:
                harness.attach(agente_id, config or {})
                resultado = await harness.apply_hooks(
                    "pre", {"agente_id": agente_id, "mensaje": mensaje, "user_id": user_id},
                )
                extra = resultado.get("memoria_semantica")
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
