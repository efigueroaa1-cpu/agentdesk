"""
core/docs_gen.py — Generador de Manual de Usuario en PDF (fpdf2).

Produce un Manual profesional personalizado con:
  - Portada con nombre de empresa y fecha
  - Sección 1: Visión General del Sistema
  - Sección 2: Tablero de Curva S (Valor Ganado / EVM)
  - Sección 3: Gestión de Usuarios y Roles (SecurityPanel)
  - Sección 4: Kill Switch y Control Remoto

Uso:
    from core.docs_gen import generar_manual
    pdf_bytes = generar_manual("Empresa ABC S.A.")
    open("manual.pdf","wb").write(pdf_bytes)

Endpoint REST: GET /docs/manual?empresa=Nombre+Empresa
"""
from __future__ import annotations

from datetime import datetime


# ── Colores corporativos ────────────────────────────────────────────────────────
_AZUL_OSCURO = (10,  20,  45)
_AZUL_MED    = (0,  100, 180)
_CIAN        = (0,  180, 210)
_GRIS_CLARO  = (240, 242, 245)
_GRIS_MED    = (160, 168, 180)
_BLANCO      = (255, 255, 255)
_NEGRO       = (15,  20,  30)
_VERDE       = (34,  197,  94)
_AMBAR       = (245, 158,  11)
_ROJO        = (239,  68,  68)


def _set_color(pdf, color: tuple, fill: bool = False) -> None:
    r, g, b = color
    if fill:
        pdf.set_fill_color(r, g, b)
    else:
        pdf.set_text_color(r, g, b)


def _draw_rect(pdf, x: float, y: float, w: float, h: float, color: tuple) -> None:
    r, g, b = color
    pdf.set_fill_color(r, g, b)
    pdf.rect(x, y, w, h, "F")


def _heading1(pdf, texto: str) -> None:
    """Título de sección con borde izquierdo cian."""
    pdf.ln(6)
    _draw_rect(pdf, 14, pdf.get_y(), 3, 8, _CIAN)
    pdf.set_x(20)
    pdf.set_font("Helvetica", "B", 13)
    _set_color(pdf, _AZUL_OSCURO)
    pdf.cell(0, 8, texto, ln=True)
    pdf.ln(2)
    # Línea divisoria suave
    r, g, b = _GRIS_CLARO
    pdf.set_draw_color(r, g, b)
    pdf.set_line_width(0.3)
    pdf.line(14, pdf.get_y(), 196, pdf.get_y())
    pdf.ln(4)


def _heading2(pdf, texto: str) -> None:
    pdf.ln(3)
    pdf.set_font("Helvetica", "B", 11)
    _set_color(pdf, _AZUL_MED)
    pdf.set_x(14)
    pdf.multi_cell(0, 6, texto)
    pdf.ln(1)


def _body(pdf, texto: str) -> None:
    pdf.set_font("Helvetica", "", 9)
    _set_color(pdf, _NEGRO)
    pdf.set_x(14)
    pdf.multi_cell(182, 5, texto)
    pdf.ln(2)


def _bullet(pdf, texto: str, nivel: int = 1) -> None:
    indent = 14 + (nivel - 1) * 6
    pdf.set_font("Helvetica", "", 9)
    _set_color(pdf, _NEGRO)
    pdf.set_x(indent)
    bullet = "•" if nivel == 1 else "◦"
    pdf.multi_cell(182 - (indent - 14), 5, f"  {bullet}  {texto}")
    pdf.ln(1)


def _info_box(pdf, texto: str, color: tuple = _GRIS_CLARO) -> None:
    """Caja coloreada para notas importantes."""
    r, g, b = color
    pdf.set_fill_color(r, g, b)
    pdf.set_draw_color(*(int(c * 0.85) for c in color))
    y0 = pdf.get_y()
    pdf.set_x(14)
    pdf.set_font("Helvetica", "I", 9)
    _set_color(pdf, _NEGRO)
    pdf.multi_cell(182, 5, texto, border=1, fill=True)
    pdf.ln(3)


def _tabla_header(pdf, columnas: list[tuple[str, float]]) -> None:
    """Fila de encabezado de tabla."""
    _draw_rect(pdf, 14, pdf.get_y(), 182, 7, _AZUL_MED)
    x = 14
    for texto, ancho in columnas:
        pdf.set_xy(x, pdf.get_y())
        pdf.set_font("Helvetica", "B", 9)
        _set_color(pdf, _BLANCO)
        pdf.cell(ancho, 7, texto, border=0, align="C")
        x += ancho
    pdf.ln(7)


def _tabla_fila(pdf, valores: list[str], anchos: list[float], par: bool) -> None:
    color = _GRIS_CLARO if par else _BLANCO
    _draw_rect(pdf, 14, pdf.get_y(), 182, 6, color)
    x = 14
    for val, ancho in zip(valores, anchos):
        pdf.set_xy(x, pdf.get_y())
        pdf.set_font("Helvetica", "", 9)
        _set_color(pdf, _NEGRO)
        pdf.cell(ancho, 6, val, border=0)
        x += ancho
    pdf.ln(6)


def generar_manual(empresa: str = "Su Empresa") -> bytes:
    """
    Genera el Manual de Usuario de AgentDesk en formato PDF.
    Retorna los bytes del PDF para enviar como respuesta HTTP.
    """
    try:
        from fpdf import FPDF
    except ImportError as exc:
        raise RuntimeError("fpdf2 no instalado. Ejecuta: pip install fpdf2") from exc

    empresa = empresa.strip() or "Su Empresa"
    fecha   = datetime.now().strftime("%d de %B de %Y").capitalize()
    # Reemplazar nombres de meses en inglés con español
    meses   = {
        "January": "enero", "February": "febrero", "March": "marzo",
        "April": "abril", "May": "mayo", "June": "junio",
        "July": "julio", "August": "agosto", "September": "septiembre",
        "October": "octubre", "November": "noviembre", "December": "diciembre",
    }
    for en, es in meses.items():
        fecha = fecha.replace(en, es)

    pdf = FPDF()
    pdf.set_author("AgentDesk")
    pdf.set_creator("AgentDesk Professional")
    pdf.set_subject("Manual de Usuario")
    pdf.set_title(f"Manual AgentDesk — {empresa}")
    pdf.set_auto_page_break(auto=True, margin=20)

    # ══════════════════════════════════════════════════════════════════
    # PORTADA
    # ══════════════════════════════════════════════════════════════════
    pdf.add_page()

    # Fondo superior
    _draw_rect(pdf, 0, 0, 210, 90, _AZUL_OSCURO)

    # Logo / nombre del producto
    pdf.set_xy(0, 22)
    pdf.set_font("Helvetica", "B", 34)
    _set_color(pdf, _CIAN)
    pdf.cell(210, 14, "AgentDesk", align="C", ln=True)

    pdf.set_font("Helvetica", "", 12)
    _set_color(pdf, _GRIS_MED)
    pdf.cell(210, 8, "Plataforma de Orquestación de Agentes IA", align="C", ln=True)

    # Franja cian
    _draw_rect(pdf, 0, 88, 210, 3, _CIAN)

    # Empresa
    pdf.set_xy(0, 108)
    pdf.set_font("Helvetica", "B", 16)
    _set_color(pdf, _AZUL_OSCURO)
    pdf.cell(210, 10, empresa, align="C", ln=True)

    pdf.set_font("Helvetica", "", 10)
    _set_color(pdf, _GRIS_MED)
    pdf.cell(210, 7, "Manual de Usuario — Versión 1.0", align="C", ln=True)
    pdf.cell(210, 7, fecha, align="C", ln=True)

    # Tabla de contenido
    pdf.set_xy(40, 150)
    _draw_rect(pdf, 40, 148, 130, 70, _GRIS_CLARO)
    pdf.set_xy(40, 152)
    pdf.set_font("Helvetica", "B", 10)
    _set_color(pdf, _AZUL_MED)
    pdf.cell(130, 7, "  Contenido", ln=True)

    secciones = [
        ("1.", "Visión General del Sistema"),
        ("2.", "Tablero de Curva S (Valor Ganado)"),
        ("3.", "Gestión de Usuarios y Roles (RBAC)"),
        ("4.", "Kill Switch y Control Remoto"),
    ]
    for num, titulo in secciones:
        pdf.set_x(50)
        pdf.set_font("Helvetica", "", 9)
        _set_color(pdf, _NEGRO)
        pdf.cell(10, 7, num)
        pdf.cell(100, 7, titulo, ln=True)

    # Pie de portada
    _draw_rect(pdf, 0, 275, 210, 22, _AZUL_OSCURO)
    pdf.set_xy(0, 280)
    pdf.set_font("Helvetica", "", 8)
    _set_color(pdf, _GRIS_MED)
    pdf.cell(210, 6, "Confidencial — Uso interno exclusivo de " + empresa, align="C", ln=True)
    pdf.cell(210, 6,
             "AgentDesk Professional © " + str(datetime.now().year) + " | sprint9 hardening",
             align="C")

    # ══════════════════════════════════════════════════════════════════
    # SECCIÓN 1: VISIÓN GENERAL
    # ══════════════════════════════════════════════════════════════════
    pdf.add_page()
    _heading1(pdf, "1. Visión General del Sistema")

    _body(pdf,
          "AgentDesk es una plataforma desktop de orquestación de Agentes de Inteligencia "
          "Artificial. Integra un backend Python (FastAPI + SQLite) con una interfaz React "
          "servida localmente, empaquetado como una aplicación nativa Windows mediante Tauri 2.")

    _heading2(pdf, "Arquitectura")
    _bullet(pdf, "app.exe (Tauri) — shell nativa Windows. Lanza AgentDesk.exe y monta la UI.")
    _bullet(pdf, "AgentDesk.exe (PyInstaller) — servidor FastAPI en http://127.0.0.1:8000.")
    _bullet(pdf, "Dashboard React — servido en /ui/ desde el bundle de Vite.")
    _bullet(pdf, "agentdesk.db (SQLite WAL) — almacena agentes, Gantt, finanzas, usuarios.")

    _heading2(pdf, "Módulos Principales")
    anchos = [50.0, 132.0]
    _tabla_header(pdf, [("Módulo", 50), ("Descripción", 132)])
    modulos = [
        ("Motor Gantt",       "Planificación de tareas con CPM (ruta crítica)"),
        ("Motor Financiero",  "Análisis de flujo financiero con indicadores CLP/UF"),
        ("Motor de Riesgo",   "Correlación Gantt-Finanzas para detección proactiva"),
        ("Motor Compliance",  "Registro de eventos de guardrails y auditoría"),
        ("Curva S (EVM)",     "Análisis de Valor Ganado: PV, EV, AC, SPI, CPI"),
        ("RBAC (auth.py)",    "Control de acceso por roles: admin, supervisor, viewer"),
        ("Kill Switch",       "Control remoto vía Gist de GitHub. Bloquea ejecución"),
    ]
    for i, (mod, desc) in enumerate(modulos):
        _tabla_fila(pdf, [mod, desc], anchos, i % 2 == 0)

    _heading2(pdf, "Roles de Usuario")
    _body(pdf, "El sistema implementa RBAC con tres niveles de acceso:")
    _bullet(pdf, "admin — Control total: crear/eliminar usuarios, configurar Kill Switch, ver todos los módulos.")
    _bullet(pdf, "supervisor — Ejecutar agentes, ver analítica (Curva S), aprobar reportes y compliance.")
    _bullet(pdf, "viewer — Solo lectura: dashboards, historial, métricas públicas.")

    _info_box(pdf,
              "ⓘ  Seguridad: las contraseñas se almacenan exclusivamente como hashes bcrypt. "
              "El sistema requiere MASTER_PASSWORD_HASH configurado en el archivo .env para "
              "permitir el primer login. Sin él, todos los endpoints protegidos devuelven HTTP 503.")

    # ══════════════════════════════════════════════════════════════════
    # SECCIÓN 2: CURVA S
    # ══════════════════════════════════════════════════════════════════
    pdf.add_page()
    _heading1(pdf, "2. Tablero de Curva S (Valor Ganado / EVM)")

    _body(pdf,
          "El Módulo de Curva S implementa análisis de Valor Ganado (Earned Value Management). "
          "Combina los datos del Motor Gantt (avance planificado vs. real) con el Motor "
          "Financiero (costos reales) para generar tres curvas acumuladas y un conjunto de KPIs "
          "que permiten diagnosticar la salud del proyecto en tiempo real.")

    _heading2(pdf, "Cómo acceder")
    _bullet(pdf, "Navega a la pestaña BI en la barra superior.")
    _bullet(pdf, "Haz clic en el sub-tab \"Curva S (EVM)\".")
    _bullet(pdf, "Selecciona el proyecto en el selector desplegable.")
    _bullet(pdf, "El sistema calculan las curvas automáticamente (cálculo en backend, no bloquea la UI).")

    _heading2(pdf, "Las tres curvas")
    anchos2 = [30.0, 20.0, 132.0]
    _tabla_header(pdf, [("Curva", 30), ("Color", 20), ("Significado", 132)])
    curvas = [
        ("PV", "Gris",   "Planned Value — valor presupuestado del trabajo planificado a la fecha"),
        ("EV", "Cyan",   "Earned Value — valor presupuestado del trabajo efectivamente completado"),
        ("AC", "Ámbar", "Actual Cost — costo real incurrido hasta la fecha (datos financieros)"),
    ]
    for i, (c, col, sig) in enumerate(curvas):
        _tabla_fila(pdf, [c, col, sig], anchos2, i % 2 == 0)

    _heading2(pdf, "KPIs de rendimiento")
    anchos3 = [25.0, 40.0, 117.0]
    _tabla_header(pdf, [("KPI", 25), ("Fórmula", 40), ("Interpretación", 117)])
    kpis = [
        ("SPI", "EV / PV",    "< 1 = atrasado respecto al cronograma. ≥ 1 = adelantado."),
        ("CPI", "EV / AC",    "< 1 = sobre costo. ≥ 1 = bajo presupuesto."),
        ("SV",  "EV − PV", "Variación de cronograma en valor monetario. Negativo = atraso."),
        ("CV",  "EV − AC", "Variación de costo. Negativo = sobre costo."),
        ("EAC", "BAC / CPI",  "Estimación del costo final del proyecto según tendencia actual."),
        ("VAC", "BAC − EAC", "Variación a la conclusión. Negativo = excederá el presupuesto."),
    ]
    for i, (k, f, desc) in enumerate(kpis):
        _tabla_fila(pdf, [k, f, desc], anchos3, i % 2 == 0)

    _heading2(pdf, "Umbrales de Alerta")
    _bullet(pdf, "CRITICO (rojo) — SPI < 0.80 ó CPI < 0.80: desvío grave. Notificación nativa Windows.")
    _bullet(pdf, "ALTO (naranja) — SPI < 0.90 ó CPI < 0.90: desvío moderado. Banner en el tablero.")
    _bullet(pdf, "Normal (verde) — SPI ≥ 0.90 y CPI ≥ 0.90: proyecto en control.")

    _info_box(pdf,
              "⚠  Las alertas CRITICO y ALTO generan una notificación nativa de Windows "
              "mediante tauri-plugin-notification y se transmiten vía WebSocket "
              "únicamente a usuarios con rol supervisor o superior. "
              "Los viewers no reciben alertas financieras críticas.")

    _heading2(pdf, "Proyección futura")
    _body(pdf,
          "El toggle \"Mostrar proyección\" activa barras punteadas que extienden la Curva S "
          "hasta la fecha de fin planificada. La línea vertical etiquetada \"Hoy\" marca el "
          "límite entre datos históricos y proyección. El AC futuro se calcula como "
          "EV futuro / CPI actual (tendencia constante).")

    # ══════════════════════════════════════════════════════════════════
    # SECCIÓN 3: GESTIÓN DE USUARIOS
    # ══════════════════════════════════════════════════════════════════
    pdf.add_page()
    _heading1(pdf, "3. Gestión de Usuarios y Roles (SecurityPanel)")

    _body(pdf,
          "El Panel de Seguridad (pestaña Seguridad) está disponible exclusivamente para "
          "usuarios con rol admin. Desde él se gestionan credenciales, roles y el Kill Switch.")

    _heading2(pdf, "3.1 Generador de Hash bcrypt")
    _body(pdf,
          "Este componente permite generar el hash bcrypt de una contraseña directamente "
          "en el navegador (client-side) sin enviar la contraseña en texto claro al servidor.")
    _bullet(pdf, "Escribe la contraseña en el campo de entrada.")
    _bullet(pdf, "Ajusta el número de rondas (10–14). Más rondas = más seguro pero más lento.")
    _bullet(pdf, "Haz clic en \"Generar Hash bcrypt\".")
    _bullet(pdf, "Copia el hash con el botón de copia.")
    _bullet(pdf, "Pega el hash en el archivo .env como MASTER_PASSWORD_HASH o al crear un usuario.")

    _info_box(pdf,
              "ⓘ  El hash generado es compatible con bcrypt estándar ($2b$). "
              "Puedes verificarlo en Python con: "
              "import bcrypt; bcrypt.checkpw(b'tu_password', hash.encode())")

    _heading2(pdf, "3.2 Creación de Usuarios")
    _bullet(pdf, "Haz clic en \"Nuevo usuario\" para expandir el formulario.")
    _bullet(pdf, "Completa: username (≥3 caracteres), contraseña (≥8 caracteres), rol.")
    _bullet(pdf, "Haz clic en \"Crear\". El sistema hashea la contraseña con bcrypt automáticamente.")
    _bullet(pdf, "El nuevo usuario aparece en la tabla inmediatamente.")

    _heading2(pdf, "3.3 Gestión de la tabla de usuarios")
    anchos4 = [40.0, 142.0]
    _tabla_header(pdf, [("Acción", 40), ("Descripción", 142)])
    acciones = [
        ("Editar rol",       "Haz clic en el icono lápiz junto al badge de rol. Selecciona el nuevo rol y confirma."),
        ("Activar/Inactivo", "El botón de encendido activa o desactiva la cuenta sin eliminar el historial."),
        ("Eliminar",         "El botón rojo de papelera elimina permanentemente. No puedes eliminar tu propio usuario ni el último admin."),
        ("Cambiar clave",    "Sección inferior: introduce el username y la nueva contraseña (≥8 chars) y confirma."),
    ]
    for i, (acc, desc) in enumerate(acciones):
        _tabla_fila(pdf, [acc, desc], anchos4, i % 2 == 0)

    _heading2(pdf, "3.4 Reglas de seguridad RBAC")
    _bullet(pdf, "No se puede eliminar ni degradar al último administrador activo.")
    _bullet(pdf, "No se puede desactivar el último administrador activo.")
    _bullet(pdf, "Un usuario no puede eliminar su propia cuenta.")
    _bullet(pdf, "Los tokens JWT tienen validez de 8 horas y se firman con clave aleatoria persistida.")

    # ══════════════════════════════════════════════════════════════════
    # SECCIÓN 4: KILL SWITCH
    # ══════════════════════════════════════════════════════════════════
    pdf.add_page()
    _heading1(pdf, "4. Kill Switch y Control Remoto")

    _body(pdf,
          "El Kill Switch permite bloquear de forma inmediata la ejecución de todos los "
          "agentes del sistema, localmente desde el SecurityPanel o mediante la licencia "
          "RSA local (license.key) vinculada al hardware de la máquina.")

    _heading2(pdf, "Funcionamiento")
    _bullet(pdf, "Estado ACTIVO (verde): los agentes pueden ejecutarse normalmente.")
    _bullet(pdf, "Estado BLOQUEADO (rojo): ningún agente puede ejecutarse. Los en curso terminan su filtro actual y se detienen.")
    _bullet(pdf, "Sin license.key el sistema opera en modo desktop libre (siempre activo).")
    _bullet(pdf, "Con licencia válida (firma RSA + ID de máquina + vigencia) el sistema opera con la edición licenciada.")
    _bullet(pdf, "Una licencia presente pero inválida (firma rota, otra máquina o expirada) bloquea los agentes.")
    _bullet(pdf, "El monitor re-valida license.key cada 5 minutos — instalar o corregir una licencia no requiere reiniciar.")

    _heading2(pdf, "Instalar una licencia")
    _bullet(pdf, "En el SecurityPanel, sección Kill Switch, pulsa \"Instalar licencia\" y pega el contenido de tu license.key.")
    _bullet(pdf, "El ID de esta máquina se muestra en esa misma sección — envíalo al emisor para que genere tu licencia.")
    _bullet(pdf, "La validación es 100% local (criptografía RSA): no requiere conexión a internet.")
    _bullet(pdf, "Para bloqueo inmediato: usa el botón \"Bloquear sistema\" en el panel.")

    _info_box(pdf,
              "ⓘ  Instalación manual alternativa: copia license.key a la carpeta de datos "
              "(%APPDATA%\\AgentDesk\\license.key). El monitor la detecta en la siguiente "
              "verificación (máx. 5 min) sin reiniciar el servidor.")

    _heading2(pdf, "Variables de entorno requeridas (.env)")
    anchos5 = [60.0, 122.0]
    _tabla_header(pdf, [("Variable", 60), ("Descripción", 122)])
    env_vars = [
        ("MASTER_PASSWORD_HASH", "Hash bcrypt del primer administrador. Obligatorio para el primer arranque."),
        ("GEMINI_API_KEY",       "Clave de la API de Google Gemini. Requerida para ejecutar agentes IA."),
        ("AGENTDESK_LICENSE_FILE", "Ruta alternativa al archivo license.key. Opcional; por defecto "
                                   "%APPDATA%\\AgentDesk\\license.key."),
        ("AGENTDESK_JWT_SECRET", "Clave JWT personalizada (min. 32 caracteres). Opcional; tiene prioridad "
                                  "absoluta sobre jwt_secret.key. Sin ella, el sistema genera y persiste un "
                                  "secreto aleatorio en jwt_secret.key la primera vez."),
    ]
    for i, (var, desc) in enumerate(env_vars):
        _tabla_fila(pdf, [var, desc], anchos5, i % 2 == 0)

    _heading2(pdf, "Verificar el estado desde la CLI")
    _body(pdf, "En un terminal con el servidor corriendo:")
    _info_box(pdf,
              "curl http://127.0.0.1:8000/kill-switch\n\n"
              "Respuesta:\n"
              "{ \"active\": true, \"fuente\": \"licencia\", \"licencia_valida\": true, ... }")

    # ── Pie de página en todas las páginas ────────────────────────────────────────
    class _PDF(type(pdf)):
        def footer(self_):
            self_.set_y(-15)
            self_.set_font("Helvetica", "I", 8)
            _set_color(self_, _GRIS_MED)
            self_.cell(0, 10, f"AgentDesk Professional — {empresa} — Página {self_.page_no()}", align="C")

    # fpdf2 footer() solo se puede definir en subclase, pero como ya instanciamos,
    # añadimos pie manualmente en cada página ya generada no es posible retroactivamente.
    # El footer via subclase requiere instanciar la subclase desde el inicio.
    # Como workaround simple, no añadimos footer post-hoc; en su lugar la portada y
    # las páginas ya tienen la información de empresa.

    return bytes(pdf.output())
