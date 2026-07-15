# ADR-0008 — Seguridad Enterprise y Persistencia Masiva

- **Estado:** Aceptado
- **Fecha:** 2026-07-14
- **Relacionado:** ADR-0005 (persistencia dual), ADR-0007 (auditoría)

## Contexto

Con la telemetría industrial y la auditoría forense operativas, los dos
puntos débiles restantes eran: (a) access tokens de 8 horas — una ventana de
ataque enorme si un token se filtra — y (b) un arranque que aceptaba
silenciosamente configuraciones inseguras o incompletas.

## Decisión

### 1. Refresh Tokens rotativos (access corto)

- **Access token: 30 minutos** (antes 8 h). La sesión se mantiene canjeando
  un **refresh token rotativo** (`POST /auth/refresh`): cada canje revoca el
  usado y emite un par nuevo — un refresh sirve UNA sola vez.
- En la base solo vive el **SHA-256 del refresh** (tabla `refresh_tokens`,
  portable SQLite/PostgreSQL); el valor real existe solo en el cliente.
  Vigencia del refresh: 7 días.
- **Detección de robo:** reusar un refresh ya revocado revoca TODA la
  familia del usuario y deja traza `AUDITORIA_SEGURIDAD` — el atacante y la
  víctima pierden la sesión, y el evento queda auditado.
- Frontend: guarda el par en sessionStorage; `initAuth` renueva vía refresh
  cuando el access expiró, sin cerrar la sesión del usuario.

### 2. Arranque Fail-Hard / modo configuración

`diagnostico_arranque()` corre antes de levantar uvicorn (main.py, modo --api):

| Hallazgo | Acción |
|---|---|
| `jwt_secret.key` débil o por defecto (<32 chars o valor conocido) | **Se niega a arrancar** (exit 78) — un secreto débil delata manipulación |
| Sin usuarios en DB y sin `MASTER_PASSWORD_HASH` | **Modo configuración**: arranca degradado con aviso claro (nadie puede loguearse hasta configurar) |

El Guardián refuerza esto en cada gate: la regla `[CRED]` bloquea cualquier
credencial por defecto hardcodeada (`changeme`, `admin123`, `secret`, …) en
código o configuración versionada.

### 3. Robustez de ejecución

Timeout por paso del orquestador: 45 s → **90 s** (proveedores pesados en
tareas industriales), y el chat no-streaming reintenta con **backoff
exponencial** (2 s, 4 s) ante timeouts transitorios antes de rendirse.

## Consecuencias

- Ventana de exposición de un access robado: 8 h → ≤30 min; el refresh
  robado se auto-neutraliza al primer reuso.
- Las sesiones activas emitidas antes de este cambio siguen válidas hasta su
  expiración original (transición suave).
- El wizard de escritorio no cambia: una instalación nueva arranca en modo
  configuración, no en pantalla negra.
- Persistencia de alta concurrencia: ya cubierta por ADR-0005 (PostgreSQL
  con pool industrial); `refresh_tokens` y `auditoria_ia` viajan en el mismo
  esquema portable.
