# Manual Operativo — Control Remoto AgentDesk vía WhatsApp

## 1. Introducción

AgentDesk expone un endpoint HTTP `POST /webhook/whatsapp` que permite controlar
el sistema de forma remota desde cualquier cliente HTTP, incluyendo integraciones
con la **WhatsApp Business API** o herramientas como Twilio, Meta Cloud API o cURL.

El canal es unidireccional desde el punto de vista del protocolo: el cliente envía
una petición JSON y recibe una respuesta JSON con el resultado del comando.

---

## 2. Autenticación

Cada mensaje debe incluir el campo `clave` con la contraseña del sistema en texto
plano. El servidor la valida contra `MASTER_PASSWORD_HASH` (bcrypt en `.env`).

**No existe sesión ni token JWT** — cada webhook es autónomo y autocontenido.
Esto es intencional: el canal está diseñado para conexiones desde redes externas
sin estado persistente.

### Ejemplo de payload JSON

```json
{
  "from_number": "+56912345678",
  "mensaje": "Status",
  "clave": "mi-contraseña-segura"
}
```

### Respuesta exitosa

```json
{
  "respuesta": "AgentDesk activo.\nAgentes cargados: 17\nKill switch: activo ✅"
}
```

### Errores de autenticación

| Código HTTP | Causa |
|---|---|
| `401` | Clave incorrecta |
| `503` | `MASTER_PASSWORD_HASH` no configurado en `.env` |

---

## 3. Comandos Disponibles

### `Status`

Devuelve el estado general del sistema.

```json
{ "mensaje": "Status", "clave": "..." }
```

**Respuesta:**
```
AgentDesk activo.
Agentes cargados: 17
Kill switch: activo ✅
```

---

### `Reiniciar Agente <id>`

Recarga la configuración de un agente en caliente sin interrumpir el resto del sistema.
El cambio se valida con Pydantic v2 — si la configuración en `config.json` tiene errores,
el agente mantiene su estado anterior (rollback automático).

```json
{ "mensaje": "Reiniciar Agente agente_finanzas_01", "clave": "..." }
```

**Respuesta:**
```
Recarga de 'agente_finanzas_01' encolada correctamente.
```

> **Nota:** El ID del agente se encuentra en `config.json` → campo `"id"`. Ejemplos:
> `agente_bd_01`, `agente_finanzas_01`, `agente_mecanica_03`

---

### `Ayuda`

Lista todos los comandos disponibles.

```json
{ "mensaje": "Ayuda", "clave": "..." }
```

**Respuesta:**
```
Comandos disponibles:
  Status                 — estado del sistema y agentes cargados
  Reiniciar Agente <id>  — recarga la configuración de un agente
  Ayuda                  — lista de comandos
```

---

## 4. Integración con WhatsApp Business API

### Opción A — Twilio for WhatsApp

```python
# webhook_handler.py (servidor Flask/FastAPI del operador)
import httpx

async def on_whatsapp_message(from_number: str, body: str):
    async with httpx.AsyncClient() as client:
        r = await client.post(
            "http://TU-IP:8000/webhook/whatsapp",
            json={
                "from_number": from_number,
                "mensaje":     body,
                "clave":       os.environ["AGENTDESK_WEBHOOK_KEY"],
            },
            timeout=10,
        )
    respuesta = r.json().get("respuesta", "Sin respuesta")
    # Reenviar `respuesta` al usuario de WhatsApp via Twilio API
```

### Opción B — Meta Cloud API (webhook de entrada)

Configura un webhook en Meta Business Suite que reenvíe mensajes entrantes
a `POST /webhook/whatsapp`. El campo `entry[0].changes[0].value.messages[0].text.body`
contiene el texto del usuario.

### Opción C — cURL directo (testing o cron jobs)

```bash
curl -X POST http://localhost:8000/webhook/whatsapp \
  -H "Content-Type: application/json" \
  -d '{"mensaje":"Status","clave":"mi-password","from_number":"+56900000000"}'
```

---

## 5. Alertas Proactivas de Guardrails

Los **Guardrails** de AgentDesk son filtros del pipeline que validan la salida
de los agentes antes de generar reportes. Cuando un guardrail aborta una tarea,
el sistema genera dos notificaciones automáticas:

### 5.1 Notificación nativa de escritorio (Tauri)

Si el dashboard AgentDesk está abierto (incluso minimizado), aparece una
**notificación nativa de Windows** con:

- **Título:** `AgentDesk — Guardrail activado`
- **Cuerpo:** `Agente: <id> | <razón del rechazo>`

Esta notificación se dispara desde React cuando el WebSocket `/ws/telemetria`
recibe un evento `{ tipo: "pipeline_abortado", agente: "...", motivo: "..." }`.

### 5.2 Flujo técnico de la alerta

```
[Pipeline Python]
  AgentBase.realizar_tarea()
    → Guardrail rechaza → MAX_INTENTOS agotados
    → logger.error(..., extra={"status": "abortado", "motivo": razon})
          ↓
[WebSocketLogHandler] (core/api.py)
  Detecta status="abortado" → broadcast WS:
  { tipo: "pipeline_abortado", agente: "...", motivo: "...", nivel: "ERROR" }
          ↓
[React AgentHub.jsx]
  onWsMessage detecta tipo === "pipeline_abortado"
  → Agrega entrada roja en la consola del agente
  → AgentService.sendNotification("AgentDesk — Guardrail activado", ...)
          ↓
[Tauri lib.rs]
  tauri-plugin-notification → Notificación nativa Windows
```

### 5.3 Guardrails que generan alertas

| Guardrail | Descripción | Cuándo aborta |
|---|---|---|
| `GroundingGuard` | Verifica que los KPIs estén respaldados por datos reales | Cuando `evidencia` está vacía o los valores no coinciden |
| `RecursionGuard` | Detecta loops de razonamiento circular | Cuando el agente repite la misma respuesta > N veces |
| `SchemaGuard` | Valida que la respuesta tenga la estructura JSON correcta | Cuando `ReporteAgente` (Pydantic) rechaza la salida |
| `LatencyGuard` | Fuerza timeout si la tarea excede el límite configurado | `duracion_s > max_latencia_s` en config del agente |

### 5.4 Envío proactivo a WhatsApp (integración custom)

Para recibir alertas de guardrail en WhatsApp, implementa un handler adicional
en el WebSocket de monitoreo de Python:

```python
# En tu integración:
async def monitor_guardrails():
    async with websockets.connect("ws://localhost:8000/ws/telemetria") as ws:
        async for mensaje in ws:
            data = json.loads(mensaje)
            if data.get("tipo") == "pipeline_abortado":
                agente = data.get("agente", "desconocido")
                motivo = data.get("motivo", "sin motivo")
                await enviar_whatsapp(
                    numero=SUPERVISOR_PHONE,
                    texto=f"⚠️ AgentDesk Alert\nAgente: {agente}\nGuardrail: {motivo}"
                )
```

---

## 6. Seguridad

| Aspecto | Implementación |
|---|---|
| Contraseña | bcrypt con salt automático — nunca se almacena en texto plano |
| Hash de referencia | `MASTER_PASSWORD_HASH` en `.env` (nunca en código fuente) |
| Timeout de validación | 4 segundos máximo (ejecutado en `run_in_executor` para no bloquear el loop) |
| CORS | Solo orígenes `127.0.0.1:8000` y `localhost:*` — el webhook requiere acceso directo al servidor |
| Rate limiting | No incluido en este módulo — usar un proxy inverso (Nginx/Caddy) en producción |

### Generar MASTER_PASSWORD_HASH

```bash
python -c "import bcrypt; print(bcrypt.hashpw(b'tu-password', bcrypt.gensalt()).decode())"
```

Copia el resultado al archivo `.env`:
```
MASTER_PASSWORD_HASH=$2b$12$abc123...
```

---

## 7. Registro de Auditoría

Cada mensaje al webhook genera una entrada en `logs/sistema.log`:

```
INFO  core.api — Webhook WhatsApp recibido de +56912345678: Status
INFO  core.api — Webhook WhatsApp recibido de +56900000000: Reiniciar Agente agente_bd_01
```

Los intentos con clave incorrecta generan HTTP 401 sin registro de log
(para no exponer información de brute-force en los logs del sistema).
