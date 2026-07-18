# AgentDesk v1.0 Gold — Resumen de Arquitectura y Certificacion

Fecha: 2026-07-17 · Scorecard: **GOLD** · Gate: APROBADO 4/4 (trinquete
del Guardian: **1171** lineas, 30+ reglas) · Suite completa: **227 tests**
(3 skip por Docker) · Bundle inicial: **452.5 KB / 500 KB** · Lockfile:
**100% soberano** (venv desde cero verificado).

## Arquitectura (hexagonal, ADR-0002/0003)

```
UI React (452 KB inicial, 24 paneles lazy)  ──►  /ui/ (StaticFiles)
        │ WS /ws/telemetria + REST
core/api/        adaptadores de entrada (routers por dominio, JWT middleware)
core/services/   servicios puros (orquestador, LLM chain, Hermes, skills,
                 OT command HITL, intent copilot, audit, licencias, colas)
core/ports/      contratos (Telemetry/Actuation/Auth/Queue/Orchestrator/…)
core/domain/     nucleo puro (User/RBAC, Agent, Task — sin frameworks)
core/adapters/   OT (Modbus/MQTT/OPC-UA, lectura + escritura con limites
                 fisicos, cola resiliente, reconexion con backoff)
core/repositories/ + SQLite/PostgreSQL dual (Alembic empaquetado)
```

## Capacidades certificadas por fase

| Capa | Capacidad | Verificacion |
|---|---|---|
| Seguridad | JWT access 30min + refresh rotativo con revocacion de familia; RBAC 3 roles; Fail-Hard Zero-Default; licencia RSA local + machine_id (kill switch sin URLs externas); firma Authenticode lista (sign_release.ps1) | test_security 9/9, enterprise 7/7, e2e onboarding 9/9, [DIST-INTEGRITY] |
| Cognitiva | Memoria Hermes (vector store SQLite persistente, scope user+proyecto fail-closed, purga GDPR); Libreria de Habilidades minada de auditoria; Copiloto de Intencion (objetivo → plan seguro) | tests memory 7/7, intent 6/6, [SEMANTIC-PRIVACY], [INTENT-SAFETY] |
| Industrial | Telemetria Modbus/MQTT/OPC-UA + Gemelo Digital (Curva S ajustada por señal fisica, anti data-poisoning); actuadores con filtro determinista de limites + Human-in-the-loop obligatorio + TTL | industrial 30+/30+, [INDUSTRIAL-INTEGRITY], [INDUSTRIAL-ACTION] |
| Resiliencia | Cadena LLM Groq→Gemini→OpenAI→Ollama→Mock con circuit breakers; Queue Mode local/Celery + breaker de concurrencia; Map-Reduce multi-hilo | resilience 13+, scale 23/23 |
| Observabilidad | Auditoria forense total (auditoria_ia + FinOps tokens/USD), OTel + Prometheus, dashboard Grafana piloto, retencion con purga (auditoria + Hermes) | audit 8+, observability, [DATA-HYGIENE] |
| Fiabilidad | CI/CD GitHub Actions (gate 4/4 + suite + scorecard artefacto + presupuesto bundle); lockfile pip-compile; blitz integracion 31 tests (cadena completa via HTTP con JWT reales) | Scorecard GOLD, check_integracion |

## Deudas criticas de auditorias previas — estado final

- Kill switch por Gist (punto unico de falla): **ERRADICADO** (F24, RSA local).
- UX hostil del 503 inicial: **ERRADICADA** (F24, onboarding E2E).
- Retencion de Hermes: **SALDADA** (F26, purga unificada).
- SmartScreen: **pipeline listo y probado**; desaparece al configurar el
  certificado EV/OV real (unico pendiente EXTERNO, requiere compra).
- Brecha de testing de integracion: **CERRADA** (F28, 31 tests; bug real
  de user_id en middleware cazado y corregido).
- Fragilidad de build: **CERRADA** (lockfile verificado desde cero).
- Gate manual como punto de falla humano: **CERRADO** (CI espejo del gate;
  bloqueo remoto se activa con `git remote add` + push — pendiente operativo).

## Comandos de release

```powershell
git tag -a v1.0.0 -m "AgentDesk v1.0 Gold"
.\build_all.ps1                      # instalador NSIS definitivo
.\scripts\sign_release.ps1           # firma (AGENTDESK_SIGN_CERT/PASS)
python scripts/qa_scorecard.py       # certificacion del build
```
