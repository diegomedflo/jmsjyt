"""Transforma las respuestas crudas de la API en modelos limpios."""
from __future__ import annotations

from typing import Any, Optional

from .models import (
    OrderDetail,
    Party,
    RouteInfo,
    ScanRecord,
    TrackingResult,
)


def _f(value: Any) -> Optional[float]:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def parse_order_detail(raw: dict[str, Any], waybill_no: str) -> Optional[OrderDetail]:
    d = (raw or {}).get("data") or {}
    det = d.get("details") or {}
    if not det:
        return None
    return OrderDetail(
        waybill_no=det.get("waybillNo") or waybill_no,
        pick_time=det.get("pickTime"),
        order_source=det.get("orderSourceName"),
        goods_type=det.get("goodsTypeName"),
        goods_name=det.get("goodsName"),
        customer_name=det.get("customerName"),
        customer_code=det.get("customerCode"),
        express_type=det.get("expressTypeName"),
        payment_mode=det.get("paymentModeName"),
        charge_weight=_f(det.get("packageChargeWeight")),
        volume_weight=_f(det.get("packageVolume")),
        third_code=det.get("terminalDispatchCode"),
        pick_network=det.get("pickNetworkName"),
        sender=Party(
            name=det.get("senderName"),
            phone=det.get("senderMobilePhone"),
            country=det.get("senderCountryName"),
            province=det.get("senderProvinceName"),
            city=det.get("senderCityName"),
            area=det.get("senderAreaName"),
            address=det.get("senderDetailedAddress"),
            postal_code=det.get("senderPostalCode"),
        ),
        receiver=Party(
            name=det.get("receiverName"),
            phone=det.get("receiverMobilePhone"),
            country=det.get("receiverCountryName"),
            province=det.get("receiverProvinceName"),
            city=det.get("receiverCityName"),
            area=det.get("receiverAreaName"),
            address=det.get("receiverDetailedAddress"),
            postal_code=det.get("receiverPostalCode"),
        ),
        route=RouteInfo(
            origin_pdv=det.get("realPickNetworkName") or det.get("pickNetworkName"),
            origin_hub=det.get("initDistributeName"),
            dest_pdv=det.get("dispatchNetworkName"),
            dest_hub=det.get("destinationDistributeName"),
        ),
    )


def parse_pod(raw: dict[str, Any]) -> list[ScanRecord]:
    data = (raw or {}).get("data") or []
    if not data:
        return []
    details = data[0].get("details") or []
    events: list[ScanRecord] = []
    for it in details:
        events.append(
            ScanRecord(
                scan_time=it.get("scanTime"),
                upload_time=it.get("uploadTime"),
                scan_type=it.get("scanTypeName"),
                network=it.get("scanNetworkName"),
                operator_code=it.get("scanByCode"),
                operator_name=it.get("scanByName"),
                next_stop=it.get("nextStopName"),
                weight=str(it.get("weight")) if it.get("weight") is not None else None,
                transport_guide=it.get("remark2"),
                description=it.get("waybillTrackingContent"),
                status=it.get("status"),
                source=it.get("sourceCn"),
            )
        )
    # Garantizar orden descendente (más reciente primero) independientemente
    # de cómo los devuelva la API. scan_time tiene formato ISO-like comparable
    # lexicográficamente. Los registros sin fecha quedan al final.
    return events


def build_result(
    waybill_no: str,
    detail_raw: dict[str, Any],
    pod_raw: dict[str, Any],
    include_raw: bool = False,
) -> TrackingResult:
    detail = parse_order_detail(detail_raw, waybill_no)
    events = parse_pod(pod_raw)
    # Los eventos vienen del más reciente al más antiguo.
    last = events[0] if events else None
    return TrackingResult(
        waybill_no=waybill_no,
        detail=detail,
        events=events,
        last_status=(last.status or last.scan_type) if last else None,
        last_scan_time=last.scan_time if last else None,
        raw={"detail": detail_raw, "pod": pod_raw} if include_raw else None,
    )
