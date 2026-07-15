"""
core/services/harness_service.py — Motor de Harness Attachments (ADR-0009).

Resuelve la lista `harnesses: []` del config de cada agente a instancias de
HAT (memoria, autocrítica futura, ...) y aplica sus hooks alrededor de la
llamada al LLM. Best-effort estricto: un harness que falla se loguea y se
ignora — jamás rompe la conversación del usuario (mismo principio que
audit_service, ADR-0007).

Alcance actual de ContextHarness: memoria de CORTO PLAZO cross-sesión,
acotada al mismo agente (misma partición que usa core/memory.py, que ya
comparte contexto entre sesiones de un agente sin distinguir usuario). No
aísla por usuario todavía — es una limitación conocida, no un descuido; se
documenta aquí para no asumir una garantía de privacidad que no existe.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

PRESUPUESTO_TOKENS_DEFAULT = 400   # ~1600 chars (tokens ~= chars/4, ADR-0007)
CANDIDATOS_MAX = 30                 # trazas de auditoria a considerar por consulta


class ContextHarness:
    """
    HAT de Memoria de Corto Plazo: RAG ligero sobre `auditoria_ia`.

    En el hook 'pre' recupera fragmentos de conversaciones PASADAS del mismo
    agente (sesiones distintas a la actual — la memoria de sesión en curso
    ya la cubre core/memory.py) mediante similitud TF-IDF contra el mensaje
    entrante, e inyecta solo los fragmentos relevantes bajo un presupuesto
    de tokens para no disparar latencia ni costo.
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

    def apply_hooks(self, fase: str, contexto: dict) -> dict:
        if fase != "pre":
            return contexto   # ContextHarness no hace post-procesamiento

        mensaje   = contexto.get("mensaje", "")
        agente_id = self._agente_id or contexto.get("agente_id", "")
        if not mensaje or not agente_id:
            return contexto

        from core.services.audit_service import consultar
        from core.embeddings import recuperar_contexto_similar

        trazas = consultar(agente_id=agente_id, limit=CANDIDATOS_MAX)
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


class HarnessService:
    """Resuelve nombres de harness -> instancias y aplica sus hooks best-effort."""

    _REGISTRO: dict[str, type] = {
        "memoria": ContextHarness,
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
                resultado = harness.apply_hooks(
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
        self, nombres: list[str], agente_id: str, respuesta: str,
        user_id: str = "anonimo", config: dict | None = None,
    ) -> str:
        """Aplica el hook 'post' de cada harness (reservado para autocrítica, Fase 11)."""
        if not nombres:
            return respuesta
        actual = respuesta
        for harness in self._instanciar(nombres):
            try:
                harness.attach(agente_id, config or {})
                resultado = harness.apply_hooks(
                    "post", {"agente_id": agente_id, "respuesta": actual, "user_id": user_id},
                )
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
