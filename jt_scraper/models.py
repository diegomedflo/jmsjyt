"""Modelos de datos del tracking J&T LAC (Pydantic)."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class Party(BaseModel):
    """Remitente o destinatario."""

    name: Optional[str] = None
    phone: Optional[str] = None
    country: Optional[str] = None
    province: Optional[str] = None
    city: Optional[str] = None
    area: Optional[str] = None
    address: Optional[str] = None
    postal_code: Optional[str] = None


class RouteInfo(BaseModel):
    """Detalles de la guía (tabla de ruta)."""

    origin_pdv: Optional[str] = None        # PDV de origen / realPickNetworkName
    origin_hub: Optional[str] = None        # HUB de origen / initDistributeName
    dest_pdv: Optional[str] = None          # PDV de destino / dispatchNetworkName
    dest_hub: Optional[str] = None          # HUB de destino / destinationDistributeName


class OrderDetail(BaseModel):
    """Información básica del envío."""

    waybill_no: str
    pick_time: Optional[str] = None
    order_source: Optional[str] = None      # TEMU, etc.
    goods_type: Optional[str] = None
    goods_name: Optional[str] = None
    customer_name: Optional[str] = None
    customer_code: Optional[str] = None
    express_type: Optional[str] = None
    payment_mode: Optional[str] = None
    charge_weight: Optional[float] = None
    volume_weight: Optional[float] = None
    third_code: Optional[str] = None        # terminalDispatchCode (tercer código)
    pick_network: Optional[str] = None
    sender: Party = Field(default_factory=Party)
    receiver: Party = Field(default_factory=Party)
    route: RouteInfo = Field(default_factory=RouteInfo)


class ScanRecord(BaseModel):
    """Un evento del historial de seguimiento (Registro POD)."""

    scan_time: Optional[str] = None
    upload_time: Optional[str] = None
    scan_type: Optional[str] = None         # scanTypeName
    network: Optional[str] = None           # scanNetworkName
    operator_code: Optional[str] = None     # scanByCode
    operator_name: Optional[str] = None     # scanByName
    next_stop: Optional[str] = None
    weight: Optional[str] = None
    transport_guide: Optional[str] = None   # remark2 (guía de transporte)
    description: Optional[str] = None        # waybillTrackingContent
    status: Optional[str] = None
    source: Optional[str] = None             # sourceCn


class TrackingResult(BaseModel):
    """Resultado completo del rastreo de una guía."""

    waybill_no: str
    detail: Optional[OrderDetail] = None
    events: list[ScanRecord] = Field(default_factory=list)
    last_status: Optional[str] = None
    last_scan_time: Optional[str] = None
    raw: Optional[dict] = None              # respuestas crudas (opcional, debug)
