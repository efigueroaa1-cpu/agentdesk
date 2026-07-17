# ADR-0022 — Soberania de Licenciamiento: licencia RSA local y firma de codigo

- Estado: Aceptado (2026-07-17, Fase 24)
- Relacionados: ADR-0008 (Zero-Default), ADR-0016 (diagnostico de arranque),
  ADR-0020 (estrategia de despliegue), ADR-0021 (Gemelo Digital)

## Contexto

Hasta la Fase 23 la activacion del sistema dependia de un **Gist de GitHub**
(la env var de URL del kill switch): el backend consultaba una URL raw cada
5 minutos y un `{"active": false}` remoto bloqueaba todos los agentes.

Hallazgos de verdad tecnica antes de escribir codigo:

1. **El Gist era un punto unico de falla y una URL de control externa**:
   incompatible con el criterio "offline total" de la v1.0 Gold, dependiente
   de la disponibilidad de GitHub y del secreto de una URL publica sin
   autenticacion ni firma — cualquiera con la URL podia leer el estado, y
   quien controlara el Gist controlaba todas las instalaciones a la vez.
2. **Bug latente en `main.py`**: el camino de bloqueo referenciaba en el
   modulo un atributo con el nombre de la env var del Gist, que nunca
   existio en `core/kill_switch.py` (exponia `get_gist_url()`). Si el Gist
   hubiera respondido `active: false` alguna vez, el arranque habria muerto
   con `AttributeError` en lugar del mensaje limpio + exit 78. El mecanismo
   de bloqueo remoto **jamas se ejercito de punta a punta**.
3. **`cryptography` ya es dependencia del nucleo** (vault/JWT): la licencia
   RSA no agrega ninguna dependencia nueva.
4. **`KILL_SWITCH_URL` en `auth.config.js` era config muerta** (mismo patron
   que los USERS hardcodeados de la Fase 10): solo `IS_LOCKED`/`LOCK_MESSAGE`
   se usaban. Eliminada.

## Decision

### 1. Licencia RSA local vinculada al hardware

`core/services/license_service.py` + refactor de `core/kill_switch.py`:

- `license.key` (JSON: `payload` + `firma`) se valida **100% offline**:
  firma RSA-PSS-SHA256 sobre el payload canonico (json ordenado), verificada
  con la clave publica **embebida como constante del modulo** — no como data
  file, que seria la misma clase de fallo invisible-a-PyInstaller que
  alembic.ini en la Fase 22.
- `machine_id()` = sha256 del `MachineGuid` del registro de Windows
  (fallback: MAC), truncado a 32 hex. La licencia se emite PARA una maquina.
- Politica **Zero-Default** (coherente con ADR-0016):
  - sin `license.key` → sistema ACTIVO (modo desktop libre, zero-config);
  - licencia valida → ACTIVO (fuente `licencia`, edicion/vigencia visibles);
  - licencia presente pero invalida (firma rota, otra maquina, expirada)
    → BLOQUEADO + `AUDITORIA_SEGURIDAD` (una licencia invalida delata
    manipulacion, no un olvido).
- La clave PRIVADA vive fuera del repo
  (`%APPDATA%/AgentDesk/licensing/agentdesk_priv.pem` del emisor);
  `scripts/generar_licencia.py` emite licencias y regenera pares.
- API/UI: `GET /kill-switch` expone el estado + `machine_id`;
  `POST /kill-switch/licencia` (admin) instala una licencia validandola
  ANTES de persistir; el monitor re-valida cada 5 min (instalar una licencia
  no requiere reiniciar). `POST /kill-switch/url` eliminado.

### 2. Integridad del binario: firma de codigo, no auto-hash

Se descarto deliberadamente que la licencia "valide la integridad del
binario" mediante un hash de si mismo: **un auto-chequeo dentro del binario
es teatro de seguridad** (quien parchea el exe parchea tambien el chequeo).
Cada capa hace lo suyo:

- La **licencia RSA** decide si ESTA maquina esta autorizada (autenticidad
  del permiso, no del codigo).
- La **firma Authenticode** (SignTool en `build_all.ps1`) da la integridad
  del binario distribuido y elimina la advertencia SmartScreen: el sistema
  operativo verifica la firma ANTES de ejecutar — un chequeo que el binario
  no puede sabotear a si mismo. Sin `AGENTDESK_SIGN_CERT` configurada el
  build continua con aviso (placeholder listo para el certificado EV/OV).

### 3. Guardian [DIST-INTEGRITY] + suite E2E de onboarding

- `scripts/gate.py::check_distribution_integrity`: (a) cero patrones de
  control remoto externo en TODO el fuente y (b) en el binario
  `dist/AgentDesk/AgentDesk.exe` si existe; (c) red prohibida en
  `core/kill_switch.py`; (d) **self-check criptografico real**: par efimero
  → firmar → validar OK, payload adulterado → `firma_invalida`. Si la
  cadena de licencias se rompe, ningun build sale.
- `tests/e2e/test_onboarding_wizard.py` (9 tests, `check_onboarding` en el
  gate): primer arranque en maquina limpia y offline — diagnostico
  enterprise en modo configuracion sin criticos, login sin configurar
  responde 503 CON instrucciones accionables (que variable y donde),
  `/health` y `/ui/` sirven el dashboard, y el ciclo completo de licencia
  (valida activa / adulterada / otra maquina / expirada bloquean / el
  endpoint exige admin).

## Consecuencias

- (+) Offline total: ninguna funcion critica depende de un recurso externo.
- (+) El bloqueo por licencia se ejercita en tests (el del Gist nunca lo fue).
- (+) Revocacion y expiracion por maquina, criptograficamente verificables.
- (−) Ya no existe "apagado remoto de flota" desde un punto central; el
  control es por licencia emitida (expiracion corta si se necesita presion
  comercial). Decision consciente: era incompatible con la soberania offline.
- (−) Rotar el par de claves invalida todas las licencias emitidas (documentado
  en `scripts/generar_licencia.py`).
- El actualizador (`/update/url`, `UpdatePanel`) NO es control de activacion:
  es una consulta de version configurada por el usuario y queda fuera del
  alcance de esta regla.
