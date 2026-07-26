# -*- coding: utf-8 -*-
"""
core/orchestrator_registry.py — Ciclo de vida de agentes (CRUD + recarga).

Extraido de core/orchestrator.py (2026-07-26, Strangler Fig v1.3, orchestrator
incremento 2/N): reload_agente / crear_nuevo_agente / eliminar_agente /
actualizar_agente -- registro en memoria + persistencia en config.json.
Mixin: Orquestador hereda estos metodos; esperan self._config_path, self.config,
self.agentes, self._client, self._model_name_global. AgentBase y
_TEMPERATURA_FALLBACK se importan LAZY dentro de crear_nuevo_agente (viven en
core/orchestrator.py -> import a nivel modulo seria circular).
Cubierto por tests/persistence/test_registry_agentes.py.
"""
import json
import logging

logger = logging.getLogger(__name__)


class OrquestadorRegistryMixin:
    """CRUD y recarga de agentes (ver core/orchestrator.py)."""

    # ── Recarga dinámica ───────────────────────────────────────────────────────

    def reload_agente(self, agente_id: str | None) -> list[str]:
        """
        Re-lee config.json y actualiza en caliente los parámetros del agente.

        agente_id=None → recarga todos los agentes.
        Retorna la lista de IDs que fueron actualizados.
        """
        from core.config_loader import load_config

        nuevo_cfg = load_config(self._config_path)
        self.config = nuevo_cfg                             # actualiza config en memoria

        actualizados: list[str] = []

        for ag_cfg in nuevo_cfg["agents"]:
            aid = ag_cfg["id"]
            if agente_id is not None and aid != agente_id:
                continue
            if aid in self.agentes:
                if self.agentes[aid].reload_config(ag_cfg):   # True = validado y aplicado
                    actualizados.append(aid)
                # False = validación fallida → rollback implícito, ya logueado
            else:
                logger.warning("RELOAD_CONFIG: agente_id '%s' no existe en el orquestador.", aid)

        return actualizados

    # ── Registro de nuevos agentes ────────────────────────────────────────────

    async def crear_nuevo_agente(self, data: dict) -> bool:
        """
        Registra un nuevo agente en el sistema.

        Flujo:
          1. Genera un agente_id único a partir del nombre.
          2. Valida el dict completo con AgentConfig (Pydantic).
          3. Crea el AgentBase y lo añade al registry en memoria.
          4. Persiste el nuevo agente en config.json.
          5. Emite un evento de auditoría en el log JSON.

        Retorna True si el agente fue creado, False si la validación falló.
        """
        import re
        from pydantic import ValidationError
        from core.schemas import AgentConfig
        from core.orchestrator import AgentBase, _TEMPERATURA_FALLBACK  # lazy: evita ciclo

        nombre = data.get("nombre", "").strip()
        if not nombre:
            logger.error("CREAR_AGENTE rechazado: 'nombre' es obligatorio.")
            return False

        # Generar ID único: agente_<slug>_<n>
        slug       = re.sub(r"[^a-z0-9]+", "_", nombre.lower()).strip("_")
        agente_id  = f"agente_{slug}_{len(self.agentes) + 1:02d}"

        if agente_id in self.agentes:
            logger.error(
                "CREAR_AGENTE rechazado: agente_id '%s' ya existe.", agente_id,
                extra={"agente_id": agente_id},
            )
            return False

        config_candidato = {
            "id":          agente_id,
            "nombre":      nombre,
            "tipo_ia":     data.get("tipo_ia",     "general"),
            "area":        data.get("area",        "General"),   # campo obligatorio
            "modelo":      data.get("modelo",      self._model_name_global),
            "temperatura": data.get("temperatura", _TEMPERATURA_FALLBACK),
            "idioma":      data.get("idioma",      "español"),
            "prompt_base": data.get("prompt_base", ""),
        }

        # Validación Pydantic
        try:
            AgentConfig.model_validate(config_candidato)
        except ValidationError as e:
            logger.error(
                "CREAR_AGENTE rechazado: validación fallida para '%s'.",
                nombre,
                extra={
                    "nombre":          nombre,
                    "errores_pydantic": [err["msg"] for err in e.errors()],
                },
            )
            return False

        # Crear AgentBase y registrar
        nuevo = AgentBase(config_candidato, self._client, self._model_name_global)
        self.agentes[agente_id]       = nuevo
        self.config["agents"].append(config_candidato)

        # Persistencia en config.json
        with open(self._config_path, "w", encoding="utf-8") as f:
            json.dump(self.config, f, indent=2, ensure_ascii=False)

        # Evento de auditoría
        logger.info(
            "Nuevo agente registrado en el sistema.",
            extra={
                "evento":      "AGENTE_CREADO",
                "agente_id":   agente_id,
                "nombre":      nombre,
                "tipo_ia":     config_candidato["tipo_ia"],
                "modelo":      config_candidato["modelo"],
                "temperatura": config_candidato["temperatura"],
                "idioma":      config_candidato["idioma"],
                "fuente":      "UI",
            },
        )
        return True

    # ── Eliminación de agentes ────────────────────────────────────────────────

    async def eliminar_agente(self, agente_id: str) -> bool:
        """
        Elimina un agente del sistema en caliente.
        Flujo: valida existencia → elimina del registry → persiste config.json.
        Retorna True si fue eliminado, False si no existía.
        """
        if agente_id not in self.agentes:
            logger.error(
                "ELIMINAR_AGENTE: agente '%s' no existe.", agente_id,
                extra={"agente_id": agente_id},
            )
            return False

        del self.agentes[agente_id]
        self.config["agents"] = [
            a for a in self.config["agents"] if a.get("id") != agente_id
        ]

        with open(self._config_path, "w", encoding="utf-8") as f:
            json.dump(self.config, f, indent=2, ensure_ascii=False)

        logger.info(
            "Agente eliminado del sistema.",
            extra={"evento": "AGENTE_ELIMINADO", "agente_id": agente_id},
        )
        return True

    # ── Actualización de agentes en caliente ──────────────────────────────────

    async def actualizar_agente(self, agente_id: str, data: dict) -> bool:
        """
        Actualiza los parámetros de un agente existente con validación Pydantic.
        Persiste los cambios en config.json si la validación pasa.
        Retorna True si fue actualizado, False si la validación falló o no existe.
        """
        if agente_id not in self.agentes:
            logger.error("ACTUALIZAR_AGENTE: agente '%s' no existe.", agente_id)
            return False

        ag = self.agentes[agente_id]
        resultado = ag.reload_config(data)   # snapshot + Pydantic + rollback

        if resultado:
            # Sincronizar config en memoria
            for ag_cfg in self.config["agents"]:
                if ag_cfg.get("id") == agente_id:
                    campos = ("nombre", "tipo_ia", "area", "modelo",
                              "temperatura", "idioma", "prompt_base",
                              "ubicacion", "siguiente_agente_id")
                    for campo in campos:
                        if campo in data:
                            ag_cfg[campo] = data[campo]
                    break

            with open(self._config_path, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)

            logger.info(
                "ACTUALIZAR_AGENTE aplicado para '%s'.",
                agente_id,
                extra={"agente_id": agente_id},
            )

        return resultado
