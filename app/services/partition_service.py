"""Servicio de gestión automática de particiones mensuales.

PostgreSQL requiere que las particiones de tracking_historial existan
ANTES de que lleguen datos. Este servicio se llama al inicio de cada
corrida del cron y crea las particiones del mes actual y el siguiente
si aún no existen. Usa SQL directo (no ORM) porque las particiones
no son entidades SQLAlchemy.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

from app.extensions import db

logger = logging.getLogger(__name__)

_PARTITION_TABLE = "tracking_historial"


def _partition_name(year: int, month: int) -> str:
    return f"{_PARTITION_TABLE}_{year}_{month:02d}"


def _first_day(year: int, month: int) -> str:
    return f"{year}-{month:02d}-01 00:00:00+00"


def _first_day_next(year: int, month: int) -> str:
    """Primer día del mes siguiente (maneja diciembre → enero)."""
    if month == 12:
        return f"{year + 1}-01-01 00:00:00+00"
    return f"{year}-{month + 1:02d}-01 00:00:00+00"


def _partition_exists(name: str) -> bool:
    """True si la tabla de partición ya existe en PostgreSQL."""
    result = db.session.execute(
        db.text(
            "SELECT 1 FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE c.relname = :name AND n.nspname = 'public'"
        ),
        {"name": name},
    ).fetchone()
    return result is not None


def _create_partition(year: int, month: int) -> bool:
    """Crea la partición para el mes dado si no existe.

    Returns True si fue creada, False si ya existía.
    """
    name  = _partition_name(year, month)
    start = _first_day(year, month)
    end   = _first_day_next(year, month)

    if _partition_exists(name):
        return False

    sql = (
        f"CREATE TABLE {name} "
        f"PARTITION OF {_PARTITION_TABLE} "
        f"FOR VALUES FROM ('{start}') TO ('{end}')"
    )
    db.session.execute(db.text(sql))
    db.session.commit()
    logger.info(f"Partición creada: {name} ({start} → {end})")
    return True


def asegurar_particiones_proximos_meses(meses_adelante: int = 2) -> list[str]:
    """Crea las particiones del mes actual y los próximos N meses si no existen.

    Se llama al inicio de cada corrida del cron para garantizar que siempre
    haya particiones disponibles para los datos entrantes.

    Args:
        meses_adelante: cuántos meses adicionales al actual crear (default 2).

    Returns:
        Lista de nombres de particiones creadas en esta llamada.
    """
    creadas: list[str] = []
    hoy = date.today()

    for delta in range(meses_adelante + 1):
        # Avanzar delta meses desde hoy
        target = date(hoy.year, hoy.month, 1) + timedelta(days=32 * delta)
        target = target.replace(day=1)

        try:
            fue_creada = _create_partition(target.year, target.month)
            if fue_creada:
                creadas.append(_partition_name(target.year, target.month))
        except Exception as exc:
            db.session.rollback()
            logger.error(
                f"Error al crear partición {target.year}-{target.month:02d}: {exc}"
            )

    return creadas
