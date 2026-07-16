"""
core/services/gantt_report_service.py — Reporte de Avance de Obra en PDF
(ADR-0003). Generación con primitivas fpdf (sin imágenes externas), extraída
de core/api.py. Sin FastAPI: recibe el proyecto ya resuelto y retorna bytes.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from core.timeutil import utcnow
from core.services.resource_guard import costo_recursos


@costo_recursos(cpu="medio", memoria="bajo")
def generar_pdf_gantt(proyecto: dict, indicadores=None, _agente_id: str | None = None) -> bytes:
    """Genera PDF de avance de obra usando primitivas fpdf (sin imágenes externas)."""
    from fpdf import FPDF

    AZUL_OSC = (10,  45,  95)
    AZUL_MED = (26,  92, 140)
    CYAN     = (0,  140, 190)
    GRIS_OSC = (40,  50,  65)
    GRIS_CLA = (235, 240, 245)
    BLANCO   = (255, 255, 255)
    CRITICO  = (220, 60,  60)

    resumen   = proyecto["resumen"]
    tareas    = proyecto["tareas"]
    pid       = proyecto["proyecto_id"]

    def _txt(s):
        if not s:
            return ""
        for k, v in {"á":"a","é":"e","í":"i","ó":"o","ú":"u","ñ":"n","ü":"u",
                     "Á":"A","É":"E","Í":"I","Ó":"O","Ú":"U","Ñ":"N"}.items():
            s = s.replace(k, v)
        return s.encode("latin-1", errors="replace").decode("latin-1")

    class GanttPDF(FPDF):
        def header(self):
            if self.page_no() == 1:
                return
            self.set_fill_color(*AZUL_OSC)
            self.rect(0, 0, 210, 10, "F")
            self.set_y(2)
            self.set_font("Helvetica", "B", 8)
            self.set_text_color(*BLANCO)
            self.cell(0, 6, _txt(f"Reporte de Avance - Proyecto: {pid}"), align="C")
            self.set_text_color(0, 0, 0)
            self.ln(10)

        def footer(self):
            self.set_y(-13)
            self.set_draw_color(*CYAN)
            self.set_line_width(0.4)
            self.line(15, self.get_y(), 195, self.get_y())
            self.set_font("Helvetica", "", 7)
            self.set_text_color(*GRIS_OSC)
            meses = ["enero","febrero","marzo","abril","mayo","junio",
                     "julio","agosto","septiembre","octubre","noviembre","diciembre"]
            n = utcnow()
            fecha = f"{n.day} de {meses[n.month-1]} de {n.year}"
            self.cell(0, 6, _txt(f"AgentDesk - {fecha} - Pag. {self.page_no()}"), align="C")

    pdf = GanttPDF()
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.set_margins(12, 12, 12)

    # ── Portada ─────────────────────────────────────────────────────────────────
    pdf.add_page()
    pdf.set_fill_color(*AZUL_OSC)
    pdf.rect(0, 0, 210, 48, "F")
    pdf.set_fill_color(*CYAN)
    pdf.rect(0, 48, 210, 2.5, "F")

    pdf.set_xy(10, 10)
    pdf.set_font("Helvetica", "B", 18)
    pdf.set_text_color(*BLANCO)
    pdf.multi_cell(190, 9, "REPORTE DE AVANCE DE OBRA", align="C")
    pdf.set_x(10)
    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(170, 210, 235)
    pdf.multi_cell(190, 7, _txt(f"Proyecto: {pid}"), align="C")

    # Métricas portada
    pdf.set_y(60)
    meta = [
        ("Avance Global",    f"{resumen.get('pct_avance', 0):.1f}%"),
        ("Total Tareas",     str(resumen.get("total_tareas", 0))),
        ("Tareas Criticas",  str(resumen.get("tareas_criticas", 0))),
        ("Fecha Inicio",     (resumen.get("fecha_inicio") or "")[:10]),
        ("Fecha Fin Plan",   (resumen.get("fecha_fin")    or "")[:10]),
    ]
    if indicadores:
        meta += [
            ("UF (BCCh)",    f"${indicadores.uf:,.2f} CLP"),
            ("Dolar (BCCh)", f"${indicadores.dolar:,.2f} CLP"),
            ("IPC",          f"{indicadores.ipc:.2f}%"),
        ]
    for k, v in meta:
        pdf.set_x(20)
        pdf.set_fill_color(*GRIS_CLA)
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(*AZUL_MED)
        pdf.cell(60, 7, _txt(k), border=0, fill=True)
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(*GRIS_OSC)
        pdf.cell(0, 7, _txt(str(v)), border=0, fill=True, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(1)

    # ── Cronograma Gantt (barras horizontales) ──────────────────────────────────
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 13)
    pdf.set_text_color(*AZUL_OSC)
    pdf.cell(0, 9, "Cronograma de Tareas", new_x="LMARGIN", new_y="NEXT")
    pdf.set_draw_color(*CYAN)
    pdf.set_line_width(0.5)
    pdf.line(12, pdf.get_y(), 198, pdf.get_y())
    pdf.ln(3)

    # Calcular escala de fechas
    fechas_inicio = [t["inicio_plan"] for t in tareas if t["inicio_plan"]]
    fechas_fin    = [t["fin_plan"]    for t in tareas if t["fin_plan"]]
    if not fechas_inicio or not fechas_fin:
        pdf.set_font("Helvetica", "", 9)
        pdf.cell(0, 7, "Sin tareas con fechas definidas.")
        return bytes(pdf.output())

    t0 = datetime.fromisoformat(min(fechas_inicio)[:19])
    t1 = datetime.fromisoformat(max(fechas_fin)[:19])
    rango_dias = max(1, (t1 - t0).days)

    COL_NOMBRE = 55
    GAP        = 3
    BAR_AREA   = 186 - 12 - COL_NOMBRE - GAP   # mm disponibles para barras
    ROW_H      = 9
    BAR_H      = 5.5
    BAR_Y_OFF  = (ROW_H - BAR_H) / 2

    # Cabecera de escala (semanas)
    pdf.set_font("Helvetica", "", 6.5)
    pdf.set_text_color(*GRIS_OSC)
    pdf.set_x(12 + COL_NOMBRE + GAP)
    semanas = max(1, rango_dias // 7)
    ancho_sem = BAR_AREA / max(semanas, 1)
    for i in range(min(semanas, 20)):
        fecha_sem = t0 + timedelta(weeks=i)
        pdf.cell(ancho_sem, 5, fecha_sem.strftime("%d/%m"), border=0, align="L")
    pdf.ln(5)

    # Filas de tareas
    for tarea in tareas:
        if pdf.get_y() > 270:
            pdf.add_page()

        y0 = pdf.get_y()
        critica = tarea.get("en_ruta_critica", False)

        # Nombre de la tarea
        pdf.set_font("Helvetica", "B" if critica else "", 7.5)
        pdf.set_text_color(*CRITICO if critica else GRIS_OSC)
        pdf.set_x(12)
        nombre_corto = _txt(tarea["nombre"])[:32]
        pdf.cell(COL_NOMBRE, ROW_H, nombre_corto, border=0)

        # Calcular posición de la barra
        inicio_t = datetime.fromisoformat((tarea["inicio_plan"] or tarea.get("es") or "")[:19] or t0.isoformat())
        fin_t    = datetime.fromisoformat((tarea["fin_plan"]    or tarea.get("ef") or "")[:19] or t1.isoformat())
        x_start  = 12 + COL_NOMBRE + GAP + ((inicio_t - t0).days / rango_dias) * BAR_AREA
        w_total  = max(2, ((fin_t - inicio_t).days / rango_dias) * BAR_AREA)
        w_done   = w_total * (tarea["pct_completado"] / 100.0)

        bar_y = y0 + BAR_Y_OFF

        # Fondo de la barra (gris claro)
        pdf.set_fill_color(*GRIS_CLA)
        pdf.set_draw_color(*AZUL_MED)
        pdf.set_line_width(0.3)
        pdf.rect(x_start, bar_y, w_total, BAR_H, "FD")

        # Progreso (relleno azul o rojo para críticas)
        if w_done > 0:
            r, g, b = (CRITICO if critica else (0, 140, 190))
            pdf.set_fill_color(r, g, b)
            pdf.rect(x_start, bar_y, w_done, BAR_H, "F")

        # Etiqueta de porcentaje
        pdf.set_font("Helvetica", "", 6)
        pdf.set_text_color(*GRIS_OSC)
        pdf.set_xy(x_start + w_total + 1, y0 + BAR_Y_OFF)
        pdf.cell(12, BAR_H, f"{tarea['pct_completado']:.0f}%", border=0)

        pdf.ln(ROW_H)

    # ── Leyenda ─────────────────────────────────────────────────────────────────
    pdf.ln(4)
    pdf.set_font("Helvetica", "", 7)
    pdf.set_fill_color(0, 140, 190)
    pdf.rect(12, pdf.get_y(), 5, 3.5, "F")
    pdf.set_x(19)
    pdf.set_text_color(*GRIS_OSC)
    pdf.cell(40, 3.5, "Avance real")
    pdf.set_fill_color(*CRITICO)
    pdf.rect(62, pdf.get_y(), 5, 3.5, "F")
    pdf.set_x(69)
    pdf.cell(0, 3.5, "Tarea en ruta critica")
    pdf.ln(8)

    # ── Tabla de tareas ──────────────────────────────────────────────────────────
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_text_color(*AZUL_OSC)
    pdf.cell(0, 7, "Detalle de Tareas", new_x="LMARGIN", new_y="NEXT")
    pdf.set_line_width(0.4)
    pdf.line(12, pdf.get_y(), 198, pdf.get_y())
    pdf.ln(1)

    cols = ["Tarea", "Agente", "Inicio Plan", "Fin Plan", "Dur.", "Avance", "Holgura", "Critica"]
    widths = [52, 30, 22, 22, 10, 14, 14, 12]
    pdf.set_fill_color(*AZUL_MED)
    pdf.set_font("Helvetica", "B", 7)
    pdf.set_text_color(*BLANCO)
    for col, w in zip(cols, widths):
        pdf.cell(w, 6, col, fill=True, border=0)
    pdf.ln(6)

    pdf.set_font("Helvetica", "", 6.5)
    for i, t in enumerate(tareas):
        if pdf.get_y() > 275:
            pdf.add_page()
        fill = i % 2 == 0
        pdf.set_fill_color(*GRIS_CLA)
        pdf.set_text_color(*GRIS_OSC)
        critica_txt = "SI" if t.get("en_ruta_critica") else "no"
        fila = [
            _txt(t["nombre"])[:28],
            _txt(t.get("agente_id") or "—")[:16],
            (t["inicio_plan"] or "")[:10],
            (t["fin_plan"]    or "")[:10],
            f"{t['duracion_dias']:.0f}d",
            f"{t['pct_completado']:.0f}%",
            f"{t.get('holgura_dias', 0):.1f}d",
            critica_txt,
        ]
        for val, w in zip(fila, widths):
            pdf.cell(w, 5.5, val, fill=fill, border=0)
        pdf.ln(5.5)

    return bytes(pdf.output())
