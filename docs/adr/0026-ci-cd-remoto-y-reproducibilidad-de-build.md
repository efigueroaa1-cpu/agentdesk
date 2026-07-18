# ADR-0026 — Automatizacion de la Veracidad: CI/CD remoto y reproducibilidad de build

- Estado: Aceptado (2026-07-17, Fase 28)
- Relacionados: ADR-0016 (Zero-Default), ADR-0020 (despliegue), ADR-0022
  (integridad de distribucion), ADR-0025 (Copiloto)

## Contexto

El Quality Gate (gate.ps1 + gate.py, 30+ checks) corre MANUALMENTE en la
maquina de desarrollo. Para la v1.0 Gold la veracidad debe ser
estructural: nadie — ni el propio desarrollador — debe poder subir codigo
que no paso el gate, y un build de hoy debe ser reconstruible identico
dentro de un año.

Hallazgos de verdad tecnica:

1. **El repo NO tiene remoto GitHub configurado** (`git remote -v` vacio).
   El workflow queda escrito, validado en sintaxis y ESPEJADO localmente
   (el gate local corre exactamente los mismos checks); el criterio "el
   CI remoto bloquea el commit" se cumplira literalmente al ejecutar
   `git remote add` + push — sin cambios adicionales. No se simula un run
   de Actions que no ocurrio.
2. **El "QA Scorecard de la Fase 26" referenciado en el pedido nunca
   existio** (misma clase de discrepancia que las Fases 12/14/22). Se
   crea en esta fase: `scripts/qa_scorecard.py`.
3. **El presupuesto de bundle (<500 KB) ya se cumplia**: el
   code-splitting de la Fase 8 (manualChunks + React.lazy en 24 paneles)
   dejo el bundle inicial en ~448 KB (index 46.6 + vendor 371.9 + CSS
   29.5). Lo que NO existia era el ENFORCEMENT: nada impedia que una
   dependencia nueva lo reventara en silencio. Esta fase agrega el
   presupuesto como check bloqueante (CI + scorecard), no re-trabajo.
   Nota: separar react del vendor produce ciclo vendor<->vendor-react
   (hallazgo F9) — se respeta la estructura actual.
4. **requirements.txt usaba rangos `>=`**: dos instalaciones en fechas
   distintas producian arboles de dependencias distintos — regresiones
   por actualizaciones externas invisibles al gate.

## Decision

### 1. Lockfile de soberania (pip-tools)

- `requirements.in`: la FUENTE con dependencias directas (los rangos
  expresan compatibilidad minima — ahi si tienen sentido).
- `requirements.txt`: GENERADO por `pip-compile` — las ~90 dependencias
  del arbol completo pineadas `==`, con trazabilidad `via` por cada una.
  Regenerar: `python -m piptools compile requirements.in --output-file
  requirements.txt --strip-extras --no-header`.
- Verificado: instalacion desde CERO en un venv limpio usando SOLO el
  lockfile + imports del nucleo funcionando.
- El scorecard verifica que ninguna linea del lockfile quede sin pin.

### 2. CI remoto (.github/workflows/quality_gate.yml)

Dos jobs en cada push/PR a main, ambos bloqueantes:

- **backend** (windows-latest, Python 3.13): instala SOLO desde el
  lockfile, corre `gate.ps1` (los 4 checks: etiquetas, seguridad,
  residuos, Guardian de Arquitectura con sus 30+ reglas y suites), corre
  la suite completa `tests/` y publica el QA Scorecard como artefacto
  (json + md) INCLUSO si el build fallo (evidencia del porque).
- **frontend** (node 20): `npm ci` (lockfile npm), ESLint, build de
  produccion y el presupuesto de bundle inicial — suma de los assets
  referenciados por `dist/index.html`; >= 500 KB rompe el build.

### 3. QA Scorecard (`scripts/qa_scorecard.py`)

Artefacto unico por build: veredicto del Guardian, conteo de la suite
completa, soberania del lockfile y presupuesto de bundle. Veredicto
global `GOLD` / `BLOQUEADO` (exit code para CI). Ejecutable tambien en
local — el operador puede auditar un build sin leer logs.

### 4. Blitz de integracion (`tests/integration/test_full_cycle.py`)

31 tests con TestClient + JWT REALES (crear_token) contra la app real:
la cadena completa Recuerdo Hermes → plan del Copiloto → validacion OT →
tareas Gantt con CPM → Curva S → aprobacion → escritura simulada →
auditoria forense; matriz RBAC de 8 superficies; ciclo de habilidades
via API; licencia RSA end-to-end via endpoints; superficie operativa.
El unico doble es el proveedor LLM (AGENTDESK_MODE=mock — camino real
del codigo). La suite corre en cada gate local (check_integracion) y en
el CI.

**Bug real cazado por el blitz**: el JWTMiddleware publicaba
`request.state.usuario` pero los endpoints de las Fases 21/25/26/27
(mapreduce, skills, OT, copiloto) leian `request.state.user_id` — que
nunca existio. Consecuencia: TODOS auditaban como "anonimo" y el scope
de habilidades por usuario no funcionaba via HTTP (los tests unitarios
no lo veian porque invocan los servicios directo). Fix: alias
`state.user_id` en el middleware. Exactamente la brecha que esta fase
existia para cerrar.

## Consecuencias

- (+) Ninguna regla del gate es opcional: local y remoto corren lo mismo.
- (+) Builds reproducibles: mismo lockfile => mismo arbol de dependencias.
- (+) El presupuesto de bundle es un contrato, no una aspiracion.
- (−) `pip-compile` debe correrse al cambiar requirements.in (el
  scorecard delata lineas sin pin si se edita a mano).
- (−) El bloqueo remoto REAL queda pendiente de crear el repo GitHub y
  hacer push — un paso operativo del usuario, no de codigo.
