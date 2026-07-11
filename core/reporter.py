"""
Reporter: persiste reportes de agentes como archivos Markdown legibles.

Formatos de nombre:
  Éxito      →  reportes/reporte_{agente}_{timestamp}.md
  Corrección →  reportes/correccion_{agente}_{timestamp}.md
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from core.correction_agent import Sugerencia
from core.path_manager import data_path

logger = logging.getLogger(__name__)


# ── Helpers internos ───────────────────────────────────────────────────────────

def _slug(texto: str) -> str:
    return texto.lower().replace(" ", "_").replace("-", "_")


def _ruta(prefijo: str, agente: str) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return data_path(f"reportes/{prefijo}_{_slug(agente)}_{ts}.md")


def _tabla_md(filas: list[list]) -> str:
    if not filas:
        return "_Sin datos_"
    header = "| " + " | ".join(str(c) for c in filas[0]) + " |"
    sep    = "| " + " | ".join("---" for _ in filas[0]) + " |"
    cuerpo = "\n".join(
        "| " + " | ".join(str(c) for c in fila) + " |"
        for fila in filas[1:]
    )
    return f"{header}\n{sep}\n{cuerpo}" if cuerpo else f"{header}\n{sep}"


def _kpis_md(kpis: dict) -> str:
    if not kpis:
        return "_Sin KPIs_"
    filas = "\n".join(f"| {k} | {v} |" for k, v in kpis.items())
    return f"| Indicador | Valor |\n|:----------|:------|\n{filas}"


# ── API pública ────────────────────────────────────────────────────────────────

def guardar_reporte(agente: str, data: dict) -> Path:
    """
    Genera un reporte Markdown para un resultado exitoso del pipeline.
    Retorna la ruta del archivo creado.
    """
    ruta = _ruta("reporte", agente)
    ts   = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    estado = "Exitoso"

    integridad_md = ""
    if aviso := data.get("_integridad"):
        estado = "Exitoso con aviso de integridad"
        integridad_md = f"\n---\n\n## ⚠ Aviso de Integridad\n\n> {aviso}\n"

    contenido = f"""\
# Reporte Ejecutivo — {agente}

**Generado:** {ts}
**Estado:** {estado}

---

## Resumen

{data.get("resumen", "_Sin datos_")}

---

## KPIs

{_kpis_md(data.get("kpis", {}))}

---

## Tabla de Datos

{_tabla_md(data.get("tabla", []))}
{integridad_md}"""

    with open(ruta, "w", encoding="utf-8") as f:
        f.write(contenido)

    logger.info(
        "Reporte Markdown guardado",
        extra={"agente": agente, "path": str(ruta), "estado": estado},
    )
    return ruta


def guardar_correccion(agente: str, sugerencia: Sugerencia) -> Path:
    """
    Genera un reporte Markdown para un resultado abortado por guardrail.
    Retorna la ruta del archivo creado.
    """
    ruta = _ruta("correccion", agente)
    ts   = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    ejemplo_md = ""
    if sugerencia.ejemplo:
        ejemplo_md = f"\n### Ejemplo\n\n```\n{sugerencia.ejemplo}\n```\n"

    log_md = ""
    if sugerencia.log_excerpt:
        fragmento = json.dumps(sugerencia.log_excerpt, indent=2, ensure_ascii=False)
        log_md = f"\n### Extracto del log JSON\n\n```json\n{fragmento}\n```\n"

    contenido = f"""\
# Reporte de Corrección — {agente}

**Generado:** {ts}
**Estado:** ABORTADO
**Filtro:** {sugerencia.filtro}
**Severidad:** {sugerencia.severidad}

---

## Causa Raíz

{sugerencia.causa_raiz}

---

## Acción Recomendada

{sugerencia.accion}
{ejemplo_md}{log_md}"""

    with open(ruta, "w", encoding="utf-8") as f:
        f.write(contenido)

    logger.info(
        "Correccion Markdown guardada",
        extra={"agente": agente, "path": str(ruta), "filtro": sugerencia.filtro},
    )
    return ruta


# ── Exportación PDF ────────────────────────────────────────────────────────────

def _crear_pdf_base():
    """Devuelve una instancia FPDF con estilos corporativos."""
    from fpdf import FPDF

    class _PDF(FPDF):
        AZUL   = (15,  52, 96)
        GRIS   = (80,  80, 80)
        CLARO  = (240, 245, 250)
        BLANCO = (255, 255, 255)

        def header(self):
            self.set_fill_color(*self.AZUL)
            self.rect(0, 0, 210, 18, "F")
            self.set_font("Helvetica", "B", 12)
            self.set_text_color(*self.BLANCO)
            self.set_y(4)
            self.cell(0, 10, "AgentDesk Professional", align="C")
            self.set_text_color(0, 0, 0)

        def footer(self):
            self.set_y(-12)
            self.set_font("Helvetica", "I", 8)
            self.set_text_color(*self.GRIS)
            self.cell(0, 8, f"Pagina {self.page_no()} | AgentDesk - Confidencial", align="C")
            self.set_text_color(0, 0, 0)

        def seccion(self, titulo: str):
            self.ln(4)
            self.set_fill_color(*self.AZUL)
            self.set_text_color(*self.BLANCO)
            self.set_font("Helvetica", "B", 10)
            self.cell(0, 8, f"  {titulo}", fill=True, ln=True)
            self.set_text_color(0, 0, 0)
            self.ln(2)

        def par(self, texto: str, size: int = 9):
            self.set_font("Helvetica", "", size)
            self.set_text_color(*self.GRIS)
            self.multi_cell(0, 5, texto)
            self.set_text_color(0, 0, 0)

    pdf = _PDF()
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()
    return pdf


def guardar_reporte_pdf(agente: str, data: dict) -> Path:
    """
    Genera un reporte de éxito en PDF profesional.
    Incluye: resumen ejecutivo, tabla de KPIs y tabla de datos.
    Retorna la ruta del archivo creado.
    """
    ruta = _ruta("reporte", agente).with_suffix(".pdf")
    ts   = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    pdf  = _crear_pdf_base()

    # Metadatos
    pdf.set_font("Helvetica", "B", 14)
    pdf.set_y(22)
    pdf.cell(0, 10, f"Reporte Ejecutivo — {agente}", align="C", ln=True)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 6, f"Generado: {ts}  |  Estado: Exitoso", align="C", ln=True)
    pdf.set_text_color(0, 0, 0)
    pdf.ln(4)

    # Resumen
    pdf.seccion("Resumen Ejecutivo")
    pdf.par(data.get("resumen", "Sin datos."))

    # KPIs
    pdf.seccion("Indicadores Clave (KPIs)")
    kpis = data.get("kpis", {})
    if kpis:
        col_w = [95, 95]
        pdf.set_fill_color(15, 52, 96)
        pdf.set_text_color(255, 255, 255)
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(col_w[0], 7, "Indicador", border=0, fill=True)
        pdf.cell(col_w[1], 7, "Valor", border=0, fill=True, ln=True)
        pdf.set_text_color(0, 0, 0)
        fill = False
        for k, v in kpis.items():
            pdf.set_fill_color(240, 245, 250) if fill else pdf.set_fill_color(255, 255, 255)
            pdf.set_font("Helvetica", "", 9)
            pdf.cell(col_w[0], 6, str(k)[:50], border="B", fill=True)
            pdf.cell(col_w[1], 6, str(v)[:50], border="B", fill=True, ln=True)
            fill = not fill

    # Tabla de datos
    tabla = data.get("tabla", [])
    if tabla:
        pdf.seccion("Tabla de Datos")
        n_cols = len(tabla[0])
        col_w  = 190 // n_cols
        # Encabezado
        pdf.set_fill_color(15, 52, 96)
        pdf.set_text_color(255, 255, 255)
        pdf.set_font("Helvetica", "B", 8)
        for h in tabla[0]:
            pdf.cell(col_w, 7, str(h)[:25], border=0, fill=True)
        pdf.ln()
        # Filas
        pdf.set_text_color(0, 0, 0)
        fill = False
        for fila in tabla[1:]:
            pdf.set_fill_color(240, 245, 250) if fill else pdf.set_fill_color(255, 255, 255)
            pdf.set_font("Helvetica", "", 8)
            for celda in fila:
                pdf.cell(col_w, 6, str(celda)[:25], border="B", fill=True)
            pdf.ln()
            fill = not fill

    pdf.output(str(ruta))
    logger.info("Reporte PDF guardado", extra={"agente": agente, "path": str(ruta)})
    return ruta


def guardar_correccion_pdf(agente: str, sugerencia: Sugerencia) -> Path:
    """
    Genera un reporte de corrección en PDF profesional.
    Incluye: causa raíz, acción recomendada y extracto del log.
    Retorna la ruta del archivo creado.
    """
    ruta = _ruta("correccion", agente).with_suffix(".pdf")
    ts   = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    pdf  = _crear_pdf_base()

    # Cabecera del documento
    pdf.set_y(22)
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 10, f"Reporte de Correccion — {agente}", align="C", ln=True)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(150, 30, 30)
    pdf.cell(0, 6, f"Generado: {ts}  |  Filtro: {sugerencia.filtro}  |  Severidad: {sugerencia.severidad}", align="C", ln=True)
    pdf.set_text_color(0, 0, 0)
    pdf.ln(4)

    # Causa raíz
    pdf.seccion("Causa Raiz")
    pdf.par(sugerencia.causa_raiz)

    # Acción recomendada
    pdf.seccion("Accion Recomendada")
    pdf.par(sugerencia.accion)

    # Ejemplo
    if sugerencia.ejemplo:
        pdf.seccion("Ejemplo de Correccion")
        pdf.set_font("Courier", "", 8)
        pdf.set_fill_color(240, 245, 250)
        pdf.multi_cell(0, 5, sugerencia.ejemplo, fill=True)

    # Extracto del log JSON
    if sugerencia.log_excerpt:
        pdf.seccion("Extracto del Log JSON")
        pdf.set_font("Courier", "", 7)
        pdf.set_fill_color(240, 245, 250)
        fragmento = json.dumps(sugerencia.log_excerpt, indent=2, ensure_ascii=False)
        pdf.multi_cell(0, 4, fragmento[:800], fill=True)

    pdf.output(str(ruta))
    logger.info("Correccion PDF guardada",
                extra={"agente": agente, "path": str(ruta), "filtro": sugerencia.filtro})
    return ruta
