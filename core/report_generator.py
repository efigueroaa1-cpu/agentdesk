"""
core/report_generator.py — Informe PDF de ingeniería (fpdf2, sin dependencias externas).

Estructura:
  1. Portada   — título, proyecto, agente, archivo, fecha
  2. Resumen   — párrafo ejecutivo completo
  3. KPIs      — tabla de indicadores en 2 columnas con valor destacado
  4. Gráfico   — barras horizontales dibujadas con primitivas PDF (sin PIL)
  5. Detalle   — tabla con todas las partidas
  6. Evidencia — fuentes de los KPIs
  7. Pie       — logo AgentDesk + número de página en todas las páginas
"""
from __future__ import annotations
from datetime import datetime


# ── Paleta de colores (R, G, B) ───────────────────────────────────────────────
AZUL_OSC  = (10,  45,  95)
AZUL_MED  = (26,  92, 140)
CYAN      = (0,  140, 190)
GRIS_OSC  = (40,  50,  65)
GRIS_MED  = (110, 120, 135)
GRIS_CLA  = (235, 240, 245)
BLANCO    = (255, 255, 255)

COLORES_BAR = [
    (0, 175, 230), (0, 200, 140), (235, 165, 0), (155, 90, 215),
    (230, 90, 140),(80,  185, 145),(90,  155, 225),(240, 115, 65),
]


def generar_pdf(
    reporte:        dict,
    titulo:         str = "Informe de Análisis",
    subtitulo:      str = "",
    nombre_agente:  str = "AgentDesk",
    archivo_nombre: str = "",
    empresa:        str = "AgentDesk",
) -> bytes:
    """Genera un PDF de ingeniería. Devuelve bytes del PDF."""
    from fpdf import FPDF

    # Limpiar texto Unicode no compatible con Helvetica (latin-1)
    titulo         = _txt(titulo)
    subtitulo      = _txt(subtitulo)
    nombre_agente  = _txt(nombre_agente)
    archivo_nombre = _txt(archivo_nombre)
    empresa        = _txt(empresa)

    kpis_raw  = reporte.get("kpis",      {})
    tabla_raw = reporte.get("tabla",     [])
    resumen   = _txt(reporte.get("resumen",   ""))
    evidencia = {_txt(k): _txt(str(v)) for k, v in reporte.get("evidencia", {}).items()}
    kpis      = {_txt(k): _txt(str(v)) for k, v in kpis_raw.items()}
    tabla     = [[_txt(str(c)) for c in row] for row in tabla_raw]
    headers   = tabla[0]  if tabla          else []
    rows      = tabla[1:] if len(tabla) > 1 else []
    kpi_list  = list(kpis.items())

    fecha_es = _txt(_fecha_es())

    class InformePDF(FPDF):
        def header(self):
            if self.page_no() == 1:
                return
            # Header páginas interiores
            self.set_fill_color(*AZUL_OSC)
            self.rect(0, 0, 210, 10, "F")
            self.set_y(2)
            self.set_font("Helvetica", "B", 8)
            self.set_text_color(*BLANCO)
            self.cell(0, 6, titulo[:70], align="C")
            self.set_text_color(*GRIS_OSC)
            self.ln(10)

        def footer(self):
            self.set_y(-15)
            self.set_draw_color(*CYAN)
            self.set_line_width(0.5)
            self.line(15, self.get_y(), 195, self.get_y())
            self.set_font("Helvetica", "", 7)
            self.set_text_color(*GRIS_MED)
            self.cell(0, 6,
                f"AgentDesk - {empresa} - {fecha_es} - Pag. {self.page_no()}",
                align="C")

    pdf = InformePDF()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.set_margins(15, 15, 15)

    # ═══════════════════════════════════════════════════════════════
    # PORTADA
    # ═══════════════════════════════════════════════════════════════
    pdf.add_page()

    # Banda azul superior
    pdf.set_fill_color(*AZUL_OSC)
    pdf.rect(0, 0, 210, 45, "F")
    pdf.set_fill_color(*CYAN)
    pdf.rect(0, 45, 210, 3, "F")

    # Título en la banda (ancho explícito para evitar conflicto con márgenes)
    pdf.set_xy(10, 8)
    pdf.set_font("Helvetica", "B", 20)
    pdf.set_text_color(*BLANCO)
    pdf.multi_cell(190, 10, titulo.upper(), align="C")

    if subtitulo:
        pdf.set_x(10)
        pdf.set_font("Helvetica", "", 12)
        pdf.set_text_color(170, 210, 235)
        pdf.multi_cell(190, 7, subtitulo, align="C")

    # Metadatos
    pdf.set_y(60)
    pdf.set_text_color(*GRIS_OSC)
    meta = [
        ("Agente Analista",    nombre_agente),
        ("Fecha de Emisión",   fecha_es),
        ("Sistema",            empresa),
    ]
    if archivo_nombre:
        meta.insert(2, ("Archivo Analizado", archivo_nombre))

    for k, v in meta:
        pdf.set_x(20)
        pdf.set_fill_color(*GRIS_CLA)
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(*AZUL_MED)
        pdf.cell(55, 8, k, border=0, fill=True, align="L")
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(*GRIS_OSC)
        pdf.cell(0, 8, str(v)[:90], border=0, fill=True, align="L", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(1)

    # Síntesis en portada
    if resumen:
        pdf.ln(8)
        pdf.set_x(20)
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(*CYAN)
        pdf.cell(0, 6, "SÍNTESIS EJECUTIVA", new_x="LMARGIN", new_y="NEXT")
        pdf.set_x(20)
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(*GRIS_OSC)
        pdf.set_fill_color(240, 248, 255)
        resumen_corto = resumen[:500] + ("..." if len(resumen) > 500 else "")
        pdf.multi_cell(170, 6, resumen_corto, border=0, fill=True, align="J")

    # Banda inferior portada
    pdf.set_y(-30)
    pdf.set_fill_color(*CYAN)
    pdf.rect(0, pdf.get_y(), 210, 2, "F")
    pdf.ln(3)
    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(*GRIS_MED)
    pdf.cell(0, 5, f"Generado por AgentDesk · {fecha_es}", align="C")

    # ═══════════════════════════════════════════════════════════════
    # RESUMEN EJECUTIVO
    # ═══════════════════════════════════════════════════════════════
    if resumen:
        pdf.add_page()
        _titulo_seccion(pdf, "1.  RESUMEN EJECUTIVO")
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(*GRIS_OSC)
        for parrafo in resumen.split("\n"):
            p = parrafo.strip()
            if p:
                pdf.set_x(15)
                pdf.multi_cell(0, 6, p, align="J")
                pdf.ln(2)

    # ═══════════════════════════════════════════════════════════════
    # INDICADORES CLAVE (KPIs)
    # ═══════════════════════════════════════════════════════════════
    if kpi_list:
        pdf.add_page()
        _titulo_seccion(pdf, "2.  INDICADORES CLAVE")
        col_w  = 85.0
        row_h  = 16.0
        cols   = 2

        for idx, (nombre, valor) in enumerate(kpi_list):
            col = idx % cols
            if col == 0 and idx > 0:
                pdf.ln(row_h + 2)

            x = 15 + col * (col_w + 5)
            y = pdf.get_y()
            i = idx % len(COLORES_BAR)

            # Fondo de la tarjeta
            pdf.set_fill_color(235, 245, 252)
            pdf.set_draw_color(*COLORES_BAR[i])
            pdf.set_line_width(0.8)
            pdf.rect(x, y, col_w, row_h, "FD")

            # Nombre del KPI
            pdf.set_xy(x + 2, y + 1)
            pdf.set_font("Helvetica", "", 7)
            pdf.set_text_color(*GRIS_MED)
            txt = nombre[:38]
            pdf.cell(col_w - 4, 5, txt, align="L")

            # Valor del KPI
            pdf.set_xy(x + 2, y + 6)
            pdf.set_font("Helvetica", "B", 13)
            r, g, b = COLORES_BAR[i]
            pdf.set_text_color(max(0,r-30), max(0,g-30), max(0,b-30))
            val_txt = str(valor)[:22]
            pdf.cell(col_w - 4, 9, val_txt, align="L")

            if col == cols - 1 or idx == len(kpi_list) - 1:
                pdf.set_y(y + row_h + 2)
                if idx != len(kpi_list) - 1:
                    pdf.set_y(pdf.get_y())

        pdf.ln(5)

    # ═══════════════════════════════════════════════════════════════
    # GRÁFICO DE BARRAS HORIZONTALES
    # ═══════════════════════════════════════════════════════════════
    chart_entries = [(k, _a_numero(v)) for k, v in kpi_list if _a_numero(v) > 0][:10]
    if chart_entries:
        pdf.add_page()
        _titulo_seccion(pdf, "3.  GRÁFICO DE INDICADORES")

        max_v    = max(v for _, v in chart_entries)
        bar_area = 130.0  # ancho máximo de barra
        bar_h    = 10.0
        gap      = 14.0
        x0       = 70.0   # donde empieza la barra (espacio para etiqueta)
        y0       = pdf.get_y() + 5

        for i, (label, val) in enumerate(chart_entries):
            y   = y0 + i * gap
            bw  = (val / max_v) * bar_area if max_v > 0 else 0
            rgb = COLORES_BAR[i % len(COLORES_BAR)]

            # Etiqueta izquierda
            pdf.set_xy(15, y + 1)
            pdf.set_font("Helvetica", "", 8)
            pdf.set_text_color(*GRIS_OSC)
            lbl = label[:22] if len(label) > 22 else label
            pdf.cell(53, bar_h - 2, lbl, align="R")

            # Barra
            pdf.set_fill_color(*rgb)
            pdf.set_draw_color(*rgb)
            pdf.rect(x0, y, max(bw, 1), bar_h, "F")

            # Valor a la derecha
            pdf.set_xy(x0 + bw + 2, y + 1)
            pdf.set_font("Helvetica", "B", 8)
            r2, g2, b2 = rgb
            pdf.set_text_color(max(0,r2-40), max(0,g2-40), max(0,b2-40))
            pdf.cell(40, bar_h - 2, _formatear_numero(val), align="L")

        # Línea base del gráfico
        pdf.set_draw_color(*GRIS_MED)
        pdf.set_line_width(0.4)
        pdf.line(x0, y0 - 2, x0, y0 + len(chart_entries) * gap)
        pdf.ln(len(chart_entries) * gap / pdf.k + 10)

    # ═══════════════════════════════════════════════════════════════
    # TABLA DE DETALLE
    # ═══════════════════════════════════════════════════════════════
    if rows and headers:
        pdf.add_page()
        _titulo_seccion(pdf, "4.  DETALLE POR PARTIDA")
        n      = len(headers)
        avail  = 180.0
        # Primera columna más ancha
        if n > 1:
            col_ws = [avail * 0.42] + [avail * 0.58 / (n - 1)] * (n - 1)
        else:
            col_ws = [avail]

        # Encabezado de tabla
        pdf.set_fill_color(*AZUL_OSC)
        pdf.set_text_color(*BLANCO)
        pdf.set_font("Helvetica", "B", 8)
        for j, h in enumerate(headers):
            pdf.cell(col_ws[j], 8, str(h)[:22], border=0, fill=True, align="C")
        pdf.ln()

        # Filas
        pdf.set_font("Helvetica", "", 8)
        for ri, row in enumerate(rows[:60]):
            if pdf.get_y() > 270:
                pdf.add_page()
            pdf.set_fill_color(*GRIS_CLA) if ri % 2 == 0 else pdf.set_fill_color(*BLANCO)
            pdf.set_text_color(*GRIS_OSC)
            for j, cell in enumerate(row[:n]):
                txt = str(cell)[:35]
                align = "L" if j == 0 else "R"
                fw    = "B" if j == 0 else ""
                pdf.set_font("Helvetica", fw, 8)
                pdf.cell(col_ws[j], 7, txt, border=0, fill=True, align=align)
            pdf.ln()

        pdf.ln(4)

    # ═══════════════════════════════════════════════════════════════
    # EVIDENCIA / FUENTES
    # ═══════════════════════════════════════════════════════════════
    if evidencia:
        if pdf.get_y() > 220:
            pdf.add_page()
        _titulo_seccion(pdf, "5.  FUENTES Y EVIDENCIA")
        for k, v in list(evidencia.items())[:20]:
            pdf.set_font("Helvetica", "B", 8)
            pdf.set_text_color(*AZUL_MED)
            pdf.set_x(15)
            pdf.cell(55, 6, str(k)[:32], align="L")
            pdf.set_font("Helvetica", "", 8)
            pdf.set_text_color(*GRIS_OSC)
            pdf.multi_cell(0, 6, str(v)[:120], align="L")
            pdf.ln(1)

    return bytes(pdf.output())


# ── Helpers ────────────────────────────────────────────────────────────────────
def _titulo_seccion(pdf, texto: str) -> None:
    from fpdf import FPDF
    pdf.set_font("Helvetica", "B", 12)
    pdf.set_text_color(*AZUL_OSC)
    pdf.cell(0, 8, texto, new_x="LMARGIN", new_y="NEXT")
    pdf.set_draw_color(*CYAN)
    pdf.set_line_width(0.8)
    pdf.line(15, pdf.get_y(), 195, pdf.get_y())
    pdf.ln(4)


def _txt(s: str) -> str:
    """Convierte caracteres Unicode no latin-1 a equivalentes ASCII."""
    reemplazos = {
        "—": "-", "–": "-", "‒": "-",   # guiones
        "’": "'", "‘": "'",                   # comillas simples
        "“": '"', "”": '"',                   # comillas dobles
        "…": "...",                                 # puntos suspensivos
        "→": "->", "←": "<-", "↔": "<->",# flechas
        "×": "x",                                  # multiplicación
        "·": "*",                                  # punto medio
        "•": "*",                                  # viñeta
        "★": "*", "☆": "*",                   # estrellas
        "►": ">", "▶": ">",                   # triángulos
    }
    for k, v in reemplazos.items():
        s = s.replace(k, v)
    # Eliminar cualquier carácter fuera de latin-1
    return s.encode("latin-1", errors="replace").decode("latin-1")


def _fecha_es() -> str:
    meses = ["enero","febrero","marzo","abril","mayo","junio",
             "julio","agosto","septiembre","octubre","noviembre","diciembre"]
    n = datetime.now()
    return f"{n.day} de {meses[n.month-1]} de {n.year} — {n.strftime('%H:%M')}"


def _es_numerico(v: object) -> bool:
    return _a_numero(v) > 0


def _a_numero(v: object) -> float:
    try:
        s = str(v).replace(",", "").replace("$", "").replace("%", "").replace(" ", "").replace(".", "")
        return float(s) if s else 0.0
    except Exception:
        return 0.0


def _formatear_numero(n: float) -> str:
    if n >= 1_000_000:
        return f"${n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"${n:,.0f}"
    return f"{n:.1f}"
