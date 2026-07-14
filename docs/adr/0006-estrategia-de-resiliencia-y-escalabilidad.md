# ADR-0006 — Estrategia de Resiliencia y Escalabilidad (MTTR optimizado)

- **Estado:** Aceptado
- **Fecha:** 2026-07-14
- **Relacionado:** ADR-0004 (Queue Mode OT), ADR-0005 (persistencia dual)

## Contexto

Abandonamos cualquier noción de "infalibilidad": los proveedores LLM caen,
las redes de planta parpadean y los reportes pesados tardan. El diseño pasa a
ser **Detección, Aislamiento y Recuperación** — que el fallo se note lo menos
posible y se recupere solo (MTTR bajo), con dos metas medibles: ~99.9% de
uptime de *inteligencia* (siempre hay una respuesta, aunque degradada) y una
UI fluida bajo carga pesada.

## Decisión

### 1. Resiliencia de Inteligencia (`core/services/llm_service.py`)

Cadena de fallback con Circuit Breaker por proveedor:

```
Groq → Gemini → OpenAI → MockProvider (determinista, sin red: SIEMPRE responde)
```

- **Detección:** errores de proveedor (5xx/red) o latencia >30 s por eslabón.
- **Aislamiento:** 2 fallos consecutivos abren el circuito — el proveedor
  queda 'inactivo' 120 s y la cadena lo salta sin llamarlo (transparente
  para el agente).
- **Recuperación:** semi-abierto tras el enfriamiento (un intento de prueba);
  si responde, el circuito se cierra solo.
- El eslabón final es el MockProvider: la inteligencia degrada con aviso
  (`degradado: true`), pero el sistema nunca devuelve "sin servicio".

### 2. Cola de Trabajos Pesados (`core/ports/queue_port.py` + `queue_service`)

- PDFs (Gantt, reportes), backup ZIP y analítica de embeddings salen del
  event loop: `queue_service.ejecutar_pesado(fn, ...)` los corre en un pool
  de workers y la API sigue atendiendo — el Dashboard no se "cuelga".
- Modo planta: `AGENTDESK_QUEUE_URL=redis://…` activa Celery + Redis
  (workers en procesos independientes) con fallback transparente al pool
  local si falta la infraestructura.
- **El Guardián lo hace cumplir:** una llamada directa a lógica pesada desde
  core/api.py (regla `[PESADO]`) bloquea el gate.

### 3. Code-Splitting del frontend (Vite `manualChunks` + React.lazy)

- 24 paneles pesados pasan a `React.lazy` (cargan al entrar a su pestaña) y
  los vendors se separan: `vendor-charts` (recharts+d3, 373 KB) y
  `vendor-maps` (react-simple-maps, 65 KB) ya no viajan en la carga inicial.
- **Resultado medido:** carga inicial 1.088 KB → **427 KB** (index 46,5 +
  vendor 209 + vendor-react 171) = **−61%**, bajo la meta de 500 KB.
- Hallazgo: `three` está en package.json pero ningún módulo lo importa
  (EmbeddingView3D renderiza sin Three.js) — candidata a remoción.

## Consecuencias

- Una tarea de reporte se completa aunque el proveedor principal caiga a
  mitad del proceso (verificado por tests/resilience/, 11 tests en el gate).
- Los circuitos son estado del proceso (se resetean al reiniciar) — métrica
  de apertura/cierre exportable a la Consola como siguiente paso.
- La cadena añade hasta 30 s por eslabón caído en el peor caso; el breaker
  lo acota: tras 2 fallos el proveedor se salta sin espera.
- El bundle inicial queda vigilado a ojo en cada build; regla automática de
  presupuesto de tamaño en el gate = mejora futura.
