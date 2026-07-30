# Certificación AgentDesk v1.3-GOLD — Soberanía Operativa

**Fecha de certificación:** 2026-07-30
**Versión:** 1.3.0 (GOLD)
**Estándar de binario:** `AgentDesk_v1.3-GOLD_x64-setup_{timestamp}.exe`

---

## 1. Hitos alcanzados

### Inteligencia autónoma
- **22/22 agentes** ejecutados con éxito en **modo 100% offline** (Modo Faena, CPU-only,
  Llama 3.2 vía Ollama). Barra de progreso al 100% en todos los agentes.
- **Cero alucinaciones por falta de datos:** los 17 agentes expertos declaran
  `"Dato No Disponible en Telemetría Actual"` (en `kpis` y `evidencia`) cuando la
  telemetría (registros 40001/40002) no cubre un KPI — resultado de auditoría válido
  que satisface el esquema Pydantic `ReporteAgente` y pasa el **GroundingGuard [CRIT]**
  sin abortar.
- **Resiliencia de watchdog:** el `ExecutionTimeout` de **650 s** (`timeout_tarea_s`,
  `engine.py`) es el **único** watchdog activo. Ollama hace **una sola pasada**
  (`MAX_INTENTOS_OLLAMA = 1`) — ningún reintento local puede desbordar el límite. Los
  proveedores cloud conservan la auto-corrección de 3 pasadas.

### Conectividad industrial (OT)
- **Modbus TCP** validado en vivo (host `127.0.0.1:5021`, registros holding
  40001/40002 = temperatura/presión).
- **OPC-UA** validado en vivo contra servidor Prosys (`:53530`) — lectura real de
  nodos (`asyncua`), sin degradar a simulador.
- Puerto de Telemetría agnóstico (ADR-0001/0004): cada protocolo entra como adaptador
  del `TelemetryPort`; cola resiliente por suscriptor con reintentos y backoff.

### Arquitectura hexagonal intacta
- Capas puras: `core/domain`, `core/ports`, `core/services`, `core/adapters`,
  `core/repositories`. Orquestador desacoplado (paquete `core/orchestrator/`, 7
  módulos <500 líneas). API desacoplada (paquete `core/api/`, 9 módulos <500 líneas).
- **Guardián de Arquitectura (`scripts/gate.py`): APROBADO 4/4** — 0 etiquetas
  TODO/PATCH, 0 archivos nuevos >500 líneas, 0 violaciones de imports por capa,
  sin `eval()`/`shell=True`, Bandit limpio (media/alta), contrato de auth 100%,
  telemetría industrial 100%, sandbox 100%.
- Trazabilidad de decisiones: ADR-0001 … ADR-0022.

---

## 2. Pipeline de build certificado

`build_all.ps1` ejecuta el flujo:

```
npm run build (Vite)  →  copia a react_dist/  →  PyInstaller (onedir, agentdesk.spec)
      →  tauri build  →  Instalador NSIS  →  AgentDesk_v1.3-GOLD_x64-setup_{TS}.exe
```

- `agentdesk.spec`: modo **onedir**; `hiddenimports` completos, incluidos los que
  PyInstaller no ve por análisis estático: **`psycopg2`**, `asyncpg`,
  `sqlalchemy.dialects.postgresql` (modo PostgreSQL), `pythonjsonlogger`, transportes
  de Celery/Kombu/Redis, `paho.mqtt`, `alembic`, `fpdf`, `uvicorn.*`.
- Firma Authenticode opcional (ADR-0022): configura `AGENTDESK_SIGN_CERT` /
  `AGENTDESK_SIGN_PASS` para evitar la advertencia de SmartScreen.

---

## 3. Checklist de Saneamiento de Seguridad — "Security-Clean" (Deuda Cero)

### 3.1 Garbage Collection del repositorio (ejecutado)
```bash
git reflog expire --expire=now --all && git gc --prune=now --aggressive
```
Estado local verificado: **0 objetos sueltos**, historia alcanzable limpia del valor
real de la clave (las únicas ocurrencias de `tvly-` son el patrón de detección del
gate y un fixture de test).

> ⚠️ El GC local **no** purga el almacenamiento server-side de GitHub. Ver ticket:
> `Desktop/ticket_github_gc_tavily.md` (acción del usuario).

### 3.2 Rotación de secretos del `.env` (antes de distribuir)
El `.env` vive en `%APPDATA%\AgentDesk\.env` (nunca se empaqueta en el instalador).

- [ ] **`AGENTDESK_TAVILY_KEY`** — **ROTAR obligatorio** (fue expuesta en repo público).
      Genera una nueva key en el panel de Tavily, revoca la anterior, actualiza el `.env`.
- [ ] **`GROQ_API_KEY`** — rotar por higiene (revocar la anterior en console.groq.com).
- [ ] **`GEMINI_API_KEY`** — rotar por higiene (Google AI Studio / Cloud console).
- [ ] **`MASTER_PASSWORD_HASH`** — regenerar si la contraseña maestra pudo filtrarse:
      `python -c "import bcrypt; print(bcrypt.hashpw(b'NUEVA_PASS', bcrypt.gensalt()).decode())"`
- [ ] **URLs heredadas del `.env`** — el kill-switch remoto fue **retirado**
      (ADR-0022, ahora 100% local): elimina cualquier variable de URL de control
      remoto obsoleta. En `AGENTDESK_UPDATE_URL`, verifica que no incruste tokens.
- [ ] **`AGENTDESK_MODBUS_HOST`** / **`AGENTDESK_OPCUA_ENDPOINT`** — no son secretos
      (endpoints de planta); solo confirmar que apuntan al entorno correcto.
- [ ] Confirmar que **ningún** secreto quedó hardcodeado: `python scripts/gate.py`
      corre la regla `[CRED]` + detección de secreto literal por prefijo
      (`tvly-`/`sk-`/`AIza`/`gsk_`/`ghp_`/…).
- [ ] Enviar el ticket de GitHub Support para el GC server-side (`Desktop/ticket_github_gc_tavily.md`).

---

## 4. Verificación de entrega

- [ ] Instalador generado (~40 MB) con el nombre estándar GOLD.
- [ ] Estructura `_internal/` completa dentro del NSIS (fix ADR-0022 / mapeo de
      recursos de Tauri en forma directorio).
- [ ] Post-instalación: `GET /health` → 200 y `/ui/` sirve el bundle del día.
- [ ] Login con la contraseña maestra real entra sin problema.
