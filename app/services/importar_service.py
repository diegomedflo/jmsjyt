"""Servicio de importación de waybills desde Excel.

Responsabilidades:
  - parse_excel_waybills: lee un .xlsx/.xls y extrae los números de guía
    de la columna "Número de Guía" (o variantes equivalentes).
  - import_waybills: inserta los waybills en la BD evitando duplicados
    y registra el resultado en la tabla excel_imports.
"""
from __future__ import annotations

import io
import unicodedata
from typing import Optional

from loguru import logger

from app.extensions import db
from app.models import Paquete
from app.models.excel_import import ExcelImport


# ── Aliases de nombre de columna aceptados ────────────────────────────────────

_GUIA_ALIASES = {
    "numerodeguia",
    "numerodeguias",
    "waybillno",
    "waybill",
    "trackingno",
    "codigodeguia",
    "guia",
    "tracking",
    "numeroguia",
    "numguia",
    "numguias",
}


def _normalize(s: str) -> str:
    """Quita tildes, pasa a minúsculas, elimina espacios y puntuación."""
    s = unicodedata.normalize("NFD", str(s).lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    for ch in (" ", ".", "_", "-", "#", "°", "º"):
        s = s.replace(ch, "")
    return s


# ── Parser de Excel ───────────────────────────────────────────────────────────

def parse_excel_waybills(file_bytes: bytes) -> list[str]:
    """Lee un archivo Excel de J&T (Monitoreo entrada al puerto) y retorna
    la lista de números de guía encontrados en la columna correspondiente.

    Raises:
        ValueError: si no se encuentra la columna de guías.
        Exception: si el archivo no se puede abrir como Excel.
    """
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(file_bytes), data_only=True)
    ws = wb.active

    # ── Leer TODAS las filas de una sola vez ──────────────────────────────
    # ReadOnlyWorksheet solo puede iterarse una vez (stream XML). Si se llama
    # iter_rows() dos veces, el segundo retorna vacío. Por eso leemos todo
    # en memoria primero y luego procesamos la lista.
    all_rows: list[tuple] = list(ws.iter_rows(values_only=True))
    wb.close()

    # ── Buscar la fila de encabezados (primeras 10 filas) ──────────────────
    header_row_idx: Optional[int] = None
    guia_col_idx:   Optional[int] = None
    found_headers:  list[str]     = []

    for row_idx, row in enumerate(all_rows[:10]):
        found_headers = [str(c) for c in row if c is not None]
        for col_idx, cell_val in enumerate(row):
            if cell_val is None:
                continue
            norm = _normalize(str(cell_val))
            if norm in _GUIA_ALIASES or any(alias in norm for alias in _GUIA_ALIASES):
                header_row_idx = row_idx
                guia_col_idx   = col_idx
                logger.info(f"[importar] Columna '{cell_val}' en col_idx={col_idx} fila={row_idx}")
                break
        if guia_col_idx is not None:
            break

    if guia_col_idx is None:
        raise ValueError(
            f"No se encontró la columna 'Número de Guía' en el Excel. "
            f"Columnas encontradas en primera fila: {found_headers[:10]}"
        )

    # ── Extraer waybills desde la fila siguiente al encabezado ────────────
    waybills: list[str] = []
    for row in all_rows[header_row_idx + 1:]:
        if not row:
            continue
        val = row[guia_col_idx] if guia_col_idx < len(row) else None
        if val is None:
            continue
        wb_no = str(val).strip()
        if wb_no and wb_no.lower() not in ("none", "nan", ""):
            waybills.append(wb_no)
    logger.info(f"[importar] {len(waybills)} waybills extraídos del Excel")
    return waybills


# ── Servicio de importación ───────────────────────────────────────────────────

def import_waybills(
    franquiciado_id: int,
    waybills: list[str],
    filename: str,
    drive_file_id: Optional[str] = None,
    import_mode: str = "manual",
    rechazados: int = 0,
) -> dict:
    """Inserta los waybills en la BD evitando duplicados y registra el log.

    Args:
        rechazados: cantidad de waybills descartados previamente por no
            coincidir con la red esperada del franquiciado (ver
            app.services.red_verificacion.registrar_rechazados). Solo se
            usa para dejar constancia en el log de importación.

    Retorna un dict con: nuevos, duplicados, total, rechazados, import_id, drive_file_id.
    """
    if not waybills:
        logger.warning("[importar] Lista de waybills vacía — nada que importar")
        return {
            "nuevos": 0, "duplicados": 0, "total": 0, "rechazados": rechazados,
            "import_id": None, "drive_file_id": drive_file_id,
        }

    # Obtener los que ya existen en la BD de una sola consulta
    existing = set(
        row[0]
        for row in db.session.execute(
            db.select(Paquete.waybill_no).where(
                Paquete.franquiciado_id == franquiciado_id,
                Paquete.waybill_no.in_(waybills),
            )
        ).fetchall()
    )

    nuevos    = 0
    duplicados = 0
    seen_in_batch: set[str] = set()

    for wb_no in waybills:
        if not wb_no:
            continue
        if wb_no in existing or wb_no in seen_in_batch:
            duplicados += 1
            continue
        db.session.add(Paquete(
            franquiciado_id=franquiciado_id,
            waybill_no=wb_no,
            estado="pendiente",
        ))
        seen_in_batch.add(wb_no)
        nuevos += 1

    import_log = ExcelImport(
        franquiciado_id=franquiciado_id,
        filename=filename,
        drive_file_id=drive_file_id,
        total_waybills=len(waybills),
        nuevos=nuevos,
        duplicados=duplicados,
        rechazados=rechazados,
        import_mode=import_mode,
    )
    db.session.add(import_log)
    db.session.commit()

    logger.info(
        f"[importar] franq={franquiciado_id} nuevos={nuevos} "
        f"dup={duplicados} rechazados={rechazados} total={len(waybills)} mode={import_mode!r}"
    )
    return {
        "nuevos":        nuevos,
        "duplicados":    duplicados,
        "total":         len(waybills),
        "rechazados":    rechazados,
        "import_id":     import_log.id,
        "drive_file_id": drive_file_id,
    }
