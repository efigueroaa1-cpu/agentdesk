# AGENTS.md — Libro de Guardia de AgentDesk

Mapa de contexto para cualquier ingeniero (humano o IA) que retome el proyecto.
Léelo completo antes de tocar código. Última revisión: 2026-07-14.

## Qué es AgentDesk

Aplicación de escritorio Windows para orquestar agentes de IA multi-proveedor
(Gemini/OpenAI/DeepSeek/Anthropic/Groq) con módulos de monitoreo web, Gantt,
finanzas, compliance y analytics.

- **Backend:** Python 3.13 + FastAPI en `127.0.0.1:8000`, empaquetado con
  PyInstaller (onedir). Entrada: `main.py` / `core/api.py`.
- **Frontend:** React + Vite + Tailwind en `agentdesk-dashboard/`, servido
  compilado en `/ui/` (StaticFiles). WebSocket de telemetría: `/ws/telemetria`.
- **Shell de escritorio:** Tauri 2.11 + instalador NSIS (`build_all.ps1`).
- **Persistencia:** SQLite vía SQLAlchemy; datos de usuario en `%APPDATA%\AgentDesk`.

## Arquitectura (hexagonal, migración Strangler Fig en curso)

Ver `docs/adr/0002-reglas-de-imports-hexagonal.md`. Resumen:

```
api.py / api_auth.py  ─→  services/  ─→  ports/  ─→  domain/
(adaptadores entrada)      │                            ▲
                           └─→  repositories/  ─────────┘
```

- `core/domain/` — entidades puras (`User`, `Agent`, `Task`) y reglas RBAC.
  Prohibido importar frameworks u otros módulos de core.
- `core/ports/` — Protocols: `TelemetryPort`+`MetricEvent` (ADR-0001, listo
  para Modbus/OPC-UA), `AuthPort`, `UserRepositoryPort`, `AgentServicePort`.
- `core/services/` — `AuthService` (JWT/bcrypt/reglas de usuarios),
  `AgentService` (ciclo de vida de agentes). NUNCA importan la capa api.
- `core/repositories/` — SQLAlchemy (`SqlAlchemyUserRepository`).
- `core/api.py` — "componente Dios" legado en adelgazamiento (2865→~2733
  líneas). Solo debe validar transporte y delegar. `core/auth.py` es una
  fachada de compatibilidad; código nuevo importa de `core.services`.
- **El Guardián (`scripts/gate.py`, invocado por `gate.ps1`) hace cumplir todo
  esto en cada gate:** etiquetas, tamaño (trinquete para legados >500 líneas),
  imports entre capas, Bandit (media/alta) y el test-contrato de auth.

## Seguridad (modelo real, no el ideal)

- JWT firmado (secreto en `jwt_secret.key`), roles `viewer(0) < supervisor(1)
  < admin(2)`, deny-by-default: sin token o token inválido ⇒ rol "viewer".
- El `JWTMiddleware` (core/api_auth.py) solo EXIGE token en: todo `DELETE` y
  las `_RUTAS_SIEMPRE_PROTEGIDAS`. El resto pasa como anónimo y cada endpoint
  sensible verifica `request.state.rol` él mismo (patrón `AUDITORIA_SEGURIDAD`
  con user_id/rol/ip — el logger `core.api` es contractual: los tests filtran
  por ese nombre).
- **Invariante blindada:** `tests/contract/test_auth_contract.py` recorre todas
  las rutas; cualquier endpoint de escritura nuevo debe quedar protegido o
  añadirse conscientemente a `RUTAS_PUBLICAS_AUTORIZADAS`, o el Gate falla.
- Suite base: `python -m unittest test_security` (9 tests RBAC de backup).

## Contrato de navegación (frontend)

- `MainLayout.jsx` con sidebar fijo `w-72` (288 px); los módulos se montan como
  componentes React nativos, **nunca iframes** (Proyectos ID 14 y Gantt ID 16
  ya se migraron de iframe a nativo).
- Módulo 8 "Monitor Web": orquestador `components/monitor/MonitorPanel.jsx`
  (<40 líneas); TODA la lógica entra por el Puerto de Telemetría
  `hooks/useMonitorData.js` → `{fuentes, cargando, eventos, historial,
  alertas, acciones}` (ADR-0001).
- Patrón obligatorio de paneles: orquestador delgado + hook de lógica +
  presentacionales puros ≤150 líneas (ver `components/agents/performance/`).
- Temas: variables CSS reales en `index.css` — `--t-accent`, `--t-bg-base`,
  `--t-bg-surface`, `--t-text`, `--t-text-muted`, `--t-border`. Usar con
  arbitrary values de Tailwind: `bg-[var(--t-bg-surface)]`.

## Por qué `core.timeutil.utcnow()`

`datetime.utcnow()` está deprecado en Python 3.12+. NO se reemplazó por
`datetime.now(timezone.utc)` a secas porque devolvería datetimes *aware* y
**toda la base SQLite almacena datetimes naive** — compararlos lanza
`TypeError`. `timeutil.utcnow()` = `datetime.now(timezone.utc).replace(tzinfo=None)`:
UTC correcto, naive deliberado, drop-in del API viejo. Usar SIEMPRE ese helper.

## Modo Demo / Dry-Run (soberanía de ejecución)

`AGENTDESK_MODE=mock` (alias `demo`, `dry-run`) hace que `core/providers.py`
intercepte TODA generación con `MockProvider`: respuestas deterministas por
SHA-256 del prompt, sin API keys, sin red, sin costo. Sirve para demos,
tests del Gate y desarrollo offline. También existe el proveedor explícito
`mock:agentdesk-demo`.

## Trampas conocidas (ya pagamos estas lecciones)

1. **Tauri aplana `_internal/`:** el glob de `resources` en `tauri.conf.json`
   aplanaba la carpeta `_internal/` de PyInstaller al empaquetar → el backend
   no arrancaba tras instalar. Mantener el patrón de resources actual de
   `build_all.ps1`/`tauri.conf.json`; verificar instaladores con
   `& "C:\Program Files\7-Zip\7z.exe" l <exe>` (7z no está en PATH).
2. **`Measure-Object -Line` NO cuenta líneas en blanco** → los conteos de
   PowerShell subestiman. La fuente de verdad de tamaños es `scripts/gate.py`.
3. **La palabra española "todo"** dispara detectores ingenuos de TODO. El
   patrón del gate es estricto y case-sensitive: `(#|//|/\*|<!--)\s*(TODO|FIXME|PATCH)\b|\b(TODO|FIXME|PATCH):`.
4. **ESLint + Prettier integrados:** siempre `npx eslint <archivos> --fix`;
   verificar límites de líneas DESPUÉS de Prettier (expande código).
5. **PowerShell 5.1:** no existe `&&` ni `?:`; usar `;` o `if ($?)`. Y evitar
   `2>&1` sobre ejecutables nativos (envuelve stderr en NativeCommandError).
6. **TestClient sin `with`:** usar `TestClient(app)` directo en tests para NO
   disparar el lifespan/startup (orquestador, scheduler).
7. **`PUT /scheduler/tareas/{id}` solo acepta `activo` e `intervalo_min`** —
   no inventar formularios contra campos que el backend no soporta.
8. **Vars de tema fantasma:** `--t-bg` y `--t-bg-card` NO existen en
   `index.css` (renderizan transparente). Usar las reales (lista arriba).
9. **eval() está prohibido** incluso con builtins vacíos (escapable vía
   atributos). La calculadora de tools.py usa un evaluador AST con lista
   blanca; Bandit en el Gate lo vigila.
10. **`urlopen` exige esquema http(s) validado** antes de llamar (B310);
    marcar con `# nosec B310` + justificación solo tras validar.

## Flujo de trabajo

1. Cambios pequeños y atómicos; correr `.\gate.ps1` antes de cada commit —
   los 4 checks (etiquetas, test_security, residuos, Guardián) deben aprobar.
2. Commits solo cuando el dueño del repo los autoriza; mensajes en inglés
   estilo convencional (`feat:`, `refactor:`, `chore:`), cuerpo sin tildes.
3. Decisiones de arquitectura → nuevo ADR en `docs/adr/` (numeración 000N).
4. Build completo: `.\build_all.ps1` (React → PyInstaller → Tauri/NSIS).
5. El ledger de sesión vive en `.superpowers/sdd/progress.md` (gitignored):
   leerlo al retomar, actualizarlo al cerrar cada hito.
