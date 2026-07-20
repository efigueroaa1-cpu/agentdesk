# AgentDesk v1.1 — Resiliencia Operativa y Soberanía de Datos en Runtime

Fecha: 2026-07-20 · Scorecard: **GOLD** · Gate: APROBADO 4/4 · Suite completa:
**290 tests** (3 skip por Docker) · Bundle inicial: **452.6 KB / 500 KB** ·
Base: v1.0.0-industrial (33fd64d).

## Contexto de la sesión

Tras validar telemetría Modbus real (v1.0.0-industrial), la Opción Paralelo
de 22 agentes exponía tres problemas reales de infraestructura: conexiones
Modbus huérfanas atascando el simulador, `config.json` empaquetado dentro
del binario (sin soberanía de datos del usuario), y saturación de Groq/Gemini
sin ninguna estrategia más allá del circuit breaker genérico. Esta sesión
cierra los tres.

## Cambios (commits 76447eb..c317be1)

| Commit | Cambio |
|---|---|
| `76447eb` | Higiene de conexión Modbus (cierre de socket siempre); `core/api/telemetry_router.py` — dominio propio para WS telemetría + Gemelo Digital/Comando OT; `max_agentes_paralelo` 4→2 |
| `8c6e93a` | Jitter táctico: 2+ degradaciones seguidas fuera de Groq espacian la siguiente llamada 1.5s+jitter |
| `4142ebb` | **Soberanía de Datos**: `config.json` deja de vivir dentro del binario — `config_path()` bootstrapea una copia escribible en `%APPDATA%\AgentDesk\` (mismo patrón que `.env`/`env.example`); cierra además una escritura muerta preexistente de `restaurar_backup()` |
| `b5325a3` | Reset de circuit breakers LLM desde la UI (`DiagnosticsPanel.jsx`) + `scripts/verificar_cuotas_llm.py` (verificación manual de cuota real, fuera del binario) |
| `c317be1` | Reintento inteligente TPM/TPD-aware (un 429 por minuto reintenta corto; uno diario no, sería desperdicio) + `agentes_prioritarios` — con cuota diaria escasa, los agentes críticos se despachan primero |

## Verdad técnica del diagnóstico central

El 429 persistente de Groq **no era un límite de ráfaga** (por lo que
espaciar llamadas en segundos no lo resolvía) — es un tope **diario** de
tokens (TPD, 100 000/día en el tier actual), confirmado línea por línea en
los mensajes reales del proveedor. La solución efectiva no fue reintentar
más rápido sino **decidir quién compite primero** por la cuota que queda:
`agentes_prioritarios` despacha primero a los agentes de negocio críticos
(Contador, SCM, Analista Finanzas, Estratega, Evaluador de Proyectos), antes
que el resto del lote.

## Prueba de Aceptación Final (FAT) — verificada con evidencia, no solo reportada

Corrida real 2026-07-20 18:29–18:30 sobre el binario `AgentDesk_0.1.0_x64-setup_20260720_1808.exe`:

- **Telemetría**: 5/5 unidades Modbus con datos reales (U1 50.0 °C / 80.0 bar).
- **Priorización**: Contador ICI y SCM respondidos por **Groq real** (verificado:
  contenido de reporte con promedios calculados, no la plantilla determinista
  del mock); Analista Finanzas Corporativas respondido por **Gemini real**
  tras encontrar el circuito de Groq abierto — y rechazó correctamente el
  análisis financiero por falta de contexto, señal inequívoca de razonamiento
  real, no una plantilla.
- **Resiliencia**: agotada la cuota real de ambos proveedores, Estratega y
  Evaluador de Proyectos degradaron a Mock (reporte honesto, sin inventar
  cifras) — **22/22 agentes completaron sin caída ni `None`**.

## Estado de deudas conocidas

- Certificado EV/OV para firma de código: pendiente externo (compra), pipeline
  listo (`sign_release.ps1`).
- `auditoria_ia` en el binario instalado tiene columnas desactualizadas
  (`contexto_hats`/`guardrails_json` de una migración Alembic posterior al
  esquema ya creado) — la Opción Paralelo (CLI) tampoco pasa por
  `audit_service.registrar_interaccion()` (solo el camino API/chat lo hace).
  No bloqueante para esta release; documentado para una fase futura.
- Cuota diaria de Groq/Gemini es una restricción real de cuenta, no de
  código — `scripts/verificar_cuotas_llm.py` permite confirmar el reset
  antes de una corrida completa.

## Comandos de release

```powershell
git tag -a v1.1.0-resiliencia -m "AgentDesk v1.1 - Operational resilience and runtime data sovereignty"
.\build_all.ps1                      # instalador NSIS definitivo
python scripts/qa_scorecard.py       # certificacion del build
```
