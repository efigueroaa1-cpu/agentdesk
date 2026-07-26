# -*- coding: utf-8 -*-
"""
core/tools/schema.py — Catalogo de herramientas (schema OpenAI-compatible).

Extraido de core/tools.py (2026-07-26, Strangler Fig v1.3, incremento 1/N):
~300 lineas de DATOS PUROS (sin logica) que inflaban el archivo Dios. Las
implementaciones y el dispatcher siguen en core/tools.py y consumen este
schema. Contrato preservado: `from core.tools import TOOLS_SCHEMA` sigue
funcionando (core/tools.py lo reexporta).
"""

TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "buscar_web",
            "description": (
                "Busca información actualizada en internet. "
                "Úsala para encontrar: memorias anuales de empresas chilenas, informes del Banco Central (IPoM), "
                "noticias financieras recientes, estados financieros, documentos de la CMF, precios de mercado. "
                "Devuelve un resumen y los resultados más relevantes con sus URLs."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "Consulta de búsqueda. Sé específico para mejores resultados. "
                            "Ej: 'memoria anual 2024 Cristales Chile CMF', "
                            "'Informe Política Monetaria junio 2025 Banco Central Chile PDF', "
                            "'estados financieros SQM 2023'"
                        ),
                    },
                    "max_resultados": {
                        "type": "integer",
                        "description": "Número de resultados (1-10). Default 6.",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "obtener_pagina",
            "description": (
                "Obtiene el contenido completo de una página web o documento. "
                "Úsala con URLs encontradas en buscar_web para leer el contenido de: "
                "memorias anuales, informes PDF del Banco Central, páginas de CMF, reportes de empresas. "
                "Puede procesar páginas HTML y documentos en línea."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "URL de la página o documento a leer.",
                    },
                    "max_chars": {
                        "type": "integer",
                        "description": "Máximo de caracteres a retornar. Default 8000.",
                    },
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "listar_archivos",
            "description": "Lista todos los archivos CSV, Excel y texto que el usuario ha subido. Úsala primero para saber qué archivos hay disponibles.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "leer_archivo",
            "description": "Lee el contenido de un archivo subido por el usuario (CSV, Excel, JSON, TXT). Si no sabes el archivo_id, usa listar_archivos primero.",
            "parameters": {
                "type": "object",
                "properties": {
                    "archivo_id": {
                        "type": "string",
                        "description": "ID del archivo (ej: 'f6a22548'). Opcional — si no se da, lee el más reciente.",
                    },
                    "max_chars": {
                        "type": "integer",
                        "description": "Máximo de caracteres a leer. Default 8000.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calcular",
            "description": "Realiza cálculos matemáticos PRECISOS. Úsala siempre para sumas, restas, porcentajes, diferencias de presupuesto, etc. Evita calcular mentalmente.",
            "parameters": {
                "type": "object",
                "properties": {
                    "expresion": {
                        "type": "string",
                        "description": "Expresión matemática Python válida. Ej: '213050821 - 135014725' o '(50000 - 43478) / 43478 * 100'",
                    },
                    "descripcion": {
                        "type": "string",
                        "description": "Qué se está calculando, para contexto. Ej: 'Diferencia entre presupuesto y gasto real'",
                    },
                },
                "required": ["expresion"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "consultar_indicadores_chile",
            "description": "Obtiene indicadores económicos actuales de Chile: valor de la UF, dólar americano, euro y otros del Banco Central.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "obtener_energia_chile",
            "description": "Obtiene datos del mercado eléctrico chileno: radiación solar, velocidad del viento, estimación de demanda eléctrica y tendencias de energía renovable.",
            "parameters": {
                "type": "object",
                "properties": {
                    "tipo": {
                        "type": "string",
                        "enum": ["solar_eolico", "demanda", "spot"],
                        "description": "Tipo de datos: solar_eolico (generación renovable), demanda (consumo estimado), spot (precio del mercado)",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calcular_financiero",
            "description": (
                "Realiza cálculos financieros y estadísticos especializados sin errores de redondeo. "
                "Úsala SIEMPRE para: VAN/TIR/Payback de proyectos, métricas EVM de control de proyectos "
                "(SPI/CPI/EAC/VAC/TCPI), estadísticas descriptivas, regresión lineal, CAGR, punto de equilibrio."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "tipo": {
                        "type": "string",
                        "enum": ["van_tir", "evm", "estadisticas", "equilibrio", "regresion", "cagr"],
                        "description": (
                            "van_tir: VAN, TIR, TIRM, Payback (datos: flujos[], tasa, tasa_reinversion?). "
                            "evm: SPI/CPI/EAC/VAC/TCPI (datos: bac, pv, ev, ac). "
                            "estadisticas: descriptiva completa (datos: valores[]). "
                            "equilibrio: punto de equilibrio (datos: costos_fijos, precio_venta, costo_variable). "
                            "regresion: regresión lineal simple (datos: x[], y[]). "
                            "cagr: tasa de crecimiento compuesto (datos: valor_inicial, valor_final, periodos)."
                        ),
                    },
                    "datos": {
                        "type": "object",
                        "description": "Parámetros según el tipo. Ver descripción del campo 'tipo'.",
                    },
                },
                "required": ["tipo", "datos"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "consultar_macro_chile",
            "description": (
                "Obtiene indicadores macroeconómicos actuales e históricos de Chile en tiempo real. "
                "Cubre: UF, TPM (Tasa Política Monetaria), IPC (inflación), IMACEC, tasa de desempleo, "
                "dólar USD, euro, libra de cobre. Fuente: Banco Central de Chile vía mindicador.cl."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "indicadores": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Lista de indicadores a consultar. Opciones: 'uf', 'tpm', 'ipc', 'imacec', "
                            "'desempleo', 'dolar', 'euro', 'libra_cobre', 'utm'. "
                            "Si se omite, retorna todos los principales."
                        ),
                    },
                    "historico": {
                        "type": "boolean",
                        "description": "Si True, incluye los últimos 12 meses de datos históricos del primer indicador.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "buscar_empresa_cmf",
            "description": (
                "Busca información financiera de empresas chilenas en la CMF (Comisión para el Mercado Financiero). "
                "Retorna datos de la empresa, emisores registrados y links a estados financieros. "
                "Úsala para analizar empresas públicas chilenas: Falabella, BCI, SQM, Codelco, Entel, etc."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "nombre_empresa": {
                        "type": "string",
                        "description": "Nombre de la empresa chilena a buscar. Ej: 'Falabella', 'SQM', 'BCI'.",
                    },
                    "rut": {
                        "type": "string",
                        "description": "RUT de la empresa sin puntos ni guión (opcional si se da nombre).",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "obtener_partidos",
            "description": "Obtiene resultados, estadísticas y tendencias de fútbol. Funciona con equipos (Real Madrid, Colo-Colo, Chile) o ligas (Premier League, La Liga).",
            "parameters": {
                "type": "object",
                "properties": {
                    "consulta": {
                        "type": "string",
                        "description": "Nombre del equipo o liga. Ej: 'Real Madrid', 'Premier League', 'Chile'",
                    },
                },
                "required": ["consulta"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "consultar_a_otro_agente",
            "description": (
                "Delega una subtarea a OTRO agente del sistema y espera su respuesta. "
                "Úsalo cuando la consulta necesita el conocimiento o el rol de un agente "
                "distinto al tuyo (ej. un agente de Finanzas necesita un dato de "
                "Mantenimiento). No lo uses para delegarte una tarea a ti mismo."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "agente_id": {
                        "type": "string",
                        "description": "ID del agente al que se delega la subtarea.",
                    },
                    "pregunta": {
                        "type": "string",
                        "description": "La subtarea o pregunta concreta a delegar.",
                    },
                },
                "required": ["agente_id", "pregunta"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "proponer_comando_ot",
            "description": (
                "PROPONE un comando de escritura hacia la planta (Modbus/MQTT): "
                "resetear una alarma, ajustar un setpoint. La propuesta NO se "
                "ejecuta: queda pendiente de la aprobación de un operador humano "
                "con rol supervisor (Human-in-the-loop, ADR-0024). Úsalo solo "
                "cuando el diagnóstico esté claro, e incluye la justificación "
                "técnica completa para que el operador pueda decidir."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "adaptador": {
                        "type": "string",
                        "description": "Protocolo destino: 'modbus' o 'mqtt'.",
                    },
                    "tag_id": {
                        "type": "string",
                        "description": "Tag escribible del catálogo de actuadores. Ej: 'reset_alarma_e117'.",
                    },
                    "valor": {
                        "type": "number",
                        "description": "Valor a escribir (debe estar dentro del límite físico del tag).",
                    },
                    "justificacion": {
                        "type": "string",
                        "description": "Diagnóstico y razón técnica de la acción propuesta.",
                    },
                },
                "required": ["adaptador", "tag_id", "valor", "justificacion"],
            },
        },
    },
]
