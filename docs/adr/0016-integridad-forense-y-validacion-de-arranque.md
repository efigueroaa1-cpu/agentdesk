# ADR-0016 — Integridad Forense y Validación de Arranque (Zero-Default)

- **Estado:** Aceptado
- **Fecha:** 2026-07-16
- **Relacionado:** ADR-0007/ADR-0014 (auditoría IA), ADR-0008 (seguridad
  enterprise, diagnóstico de arranque original), ADR-0011 (delegación
  Speak/Listen), ADR-0013 (persistencia dual, pool de conexiones), ADR-0015
  (hallazgo de la brecha de `contexto_hats` en delegación)

## Contexto

La Fase 17 cerró la brecha de testing entre memoria HAT, delegación y
auditoría forense, y en el camino documentó (sin corregir, fuera de
alcance de esa fase) un hallazgo real: `DelegationService._auditar()` no
propagaba `contexto_hats` a la traza forense, a diferencia de
`OrchestratorService._auditar()` (ADR-0014). Esta fase cierra esa brecha.

Además, el pedido de esta fase describía "implementar un servicio de
Diagnóstico de Arranque Enterprise" como si no existiera. Verificando el
código real antes de escribir nada: **ya existe desde la Fase 10**
(`AuthService.diagnostico_arranque()`, ADR-0008) — valida `AGENTDESK_JWT_SECRET`
(fuerza y prioridad sobre `jwt_secret.key`) y `MASTER_PASSWORD_HASH`
(bootstrap del primer admin), y ya está conectado a un `sys.exit(78)`
real en `main.py` si hay críticos. Lo que genuinamente faltaba —
explícitamente nombrado en el pedido — es la validación de
`AGENTDESK_DB_URL`, que hoy no se evalúa en absoluto.

## Decisión

### 1. Cierre de la brecha forense: `contexto_hats` en delegación

`DelegationService.listen()` ahora lee `agente.ultimo_contexto_hats`
(el mismo canal lateral de ADR-0014, poblado por `chat_libre` vía
`_contexto_harnesses()`) inmediatamente después de invocar `chat_libre`, y
lo pasa a `_auditar()` para el lado `"resuelto"` de la traza. El lado
`"delegado"` (origen) no tiene contexto_hats propio — quien delega no
ejecuta `chat_libre`, no hay memoria semántica que capturar de ese lado, y
no se inventa una.

`tests/integration/test_cross_systems.py::test_04` (Fase 17) pasó de
documentar la ausencia a **verificar positivamente** que el fragmento
recuperado por `ContextHarness` queda persistido en la columna
`contexto_hats` de `auditoria_ia` cuando la interacción llega vía
delegación.

### 2. Diagnóstico de Arranque Enterprise: composición, no reimplementación

`core/services/boot_diagnostics_service.py` (nuevo) compone:

- `auth_service.diagnostico_arranque()` (ADR-0008, sin cambios) — JWT y
  MASTER_PASSWORD_HASH.
- `_validar_db_url()` (nuevo) — política **Zero-Default** sobre
  `AGENTDESK_DB_URL`.

**Política Zero-Default:** un secreto **ausente** en un despliegue desktop
zero-config es una configuración **válida** (SQLite sin credenciales, JWT
autogenerado — ADR-0005/ADR-0008). Lo que nunca es válido es un secreto
**presente** con un valor por defecto o débil conocido: eso delata una
plantilla de despliegue copiada sin completar o una instalación
manipulada. Concretamente, `AGENTDESK_DB_URL` es crítico (Fail-Hard) si,
apuntando a PostgreSQL, su clave es vacía o pertenece a una lista de
credenciales por defecto conocidas (`postgres`, `admin`, `changeme`,
`123456`, ...), o si usuario y clave son idénticos. Sin la variable, o
apuntando a `sqlite:///`, no se evalúa — es el modo desktop por diseño.

`main.py` cambia su único punto de invocación de `core.auth.diagnostico_arranque`
a `boot_diagnostics_service.diagnostico_arranque_sistema()` — misma forma
de retorno (`{"criticos", "avisos", "modo_configuracion"}`), mismo
`sys.exit(78)` (EX_CONFIG) si hay críticos, mismo modo degradado si falta
`MASTER_PASSWORD_HASH`. No se relaja la excepción intencional de la Fase 10:
`MASTER_PASSWORD_HASH` ausente sigue siendo un **aviso** que degrada a modo
configuración, no un crítico — forzarlo a Fail-Hard rompería el flujo
legítimo de primera instalación (sin eso, nadie podría crear el primer
usuario admin).

Se expone `GET /diagnostico/arranque` (protegido, rol supervisor+, mismo
criterio que `/auditoria/*`) para que la UI pueda mostrar el estado sin
depender de leer el log del proceso — revela solo mensajes y booleanos,
nunca los valores de los secretos evaluados.

### 3. Guardián `[BOOT-VALIDATION]`

`scripts/gate.py` gana `check_boot_validation()`: verifica estáticamente
que `main.py` (a) importa `diagnostico_arranque_sistema`, (b) lo invoca, y
(c) el resultado sigue gobernando un `sys.exit` sobre `criticos`. Sin esta
regla, un refactor futuro de `main.py` podría desconectar el Fail-Hard sin
que ningún test lo note — nada del arranque real corre en la suite de
tests (que no invoca `main.py` como proceso).

### 4. Prueba de concurrencia de escritura — y un bug real encontrado en el camino

`tests/stress/test_db_concurrency.py` simula 10 agentes escribiendo
simultáneamente en `auditoria_ia` vía `audit_service.registrar_interaccion()`
(el mismo camino que usa cada interacción real), con `ThreadPoolExecutor`.

**Primera corrida: 4 de 50 escrituras se perdieron.** El motor por
defecto (SQLite) usaba `poolclass=StaticPool` — un único objeto
`sqlite3.Connection` de Python compartido por **todos** los hilos. Bajo
escritura concurrente real eso no es un problema de locking (agregar
`PRAGMA busy_timeout=5000` no lo resolvió) sino reuso inseguro del mismo
objeto de conexión desde varios hilos a la vez: la segunda corrida sin
`StaticPool` seguía fallando con `sqlite3.InterfaceError: bad parameter or
other API misuse`, la firma clásica de ese antipatrón.

Investigando el motivo de `StaticPool`: solo tiene sentido para bases
`:memory:` (donde cada conexión nueva sería una base vacía distinta). Esta
base **nunca** es `:memory:` en la práctica — ni el path por defecto
(`agentdesk.db` en el data dir) ni ninguna URL de despliegue real la usan,
y de hecho el propio código de `init_db()` ya redirigía silenciosamente
`sqlite:///:memory:` hacia el archivo por defecto en vez de soportarlo de
verdad. `StaticPool` no protegía nada — activamente rompía la concurrencia
real. Se retiró, dejando el pool por defecto de SQLAlchemy (una conexión
real por sesión, todas al mismo archivo), y se agregó `PRAGMA
busy_timeout=5000` para que SQLite espere hasta 5s por el lock de
escritura de otra conexión en vez de fallar de inmediato. Con ambos
cambios: 50/50 escrituras concurrentes, ~0.15-0.23s total, sin pérdidas.

**Limitación honesta (mismo patrón que Fase 13/15):** no hay un servidor
PostgreSQL real disponible en este entorno de desarrollo. El test ejercita
el camino real contra SQLite (el único motor de base de datos que existe
en esta máquina); el código bajo prueba es agnóstico al motor (misma
`get_session()`), así que el mismo test ejercitaría un PostgreSQL real sin
cambios si `AGENTDESK_DB_URL` apuntara a uno — pero no se fabrica esa
demostración.

## Consecuencias

- La auditoría forense de una interacción delegada ahora tiene la misma
  riqueza que una interacción directa — condición necesaria para que
  `GET /auditoria/interacciones` sea una fuente de verdad completa en
  sectores regulados, sin importar si la interacción pasó por delegación.
- `AGENTDESK_DB_URL` se suma a la superficie de Fail-Hard: un desplegador
  que copie una plantilla de `docker-compose.yml` con `postgres:postgres`
  sin cambiarla no puede arrancar el sistema en producción por accidente.
- El bug de `StaticPool` habría afectado a **cualquier** escritura
  concurrente real a la base de datos por defecto (no solo auditoría) —
  historial de ejecuciones, datos de monitor, alertas, Gantt. El fix es
  general, no acotado a la tabla de auditoría.
- `[BOOT-VALIDATION]` es la primera regla del Guardián que verifica que
  una pieza de seguridad esté **conectada** al arranque real, no solo que
  exista en el código — categoría distinta a las reglas anteriores
  (tamaño, imports, credenciales estáticas).
