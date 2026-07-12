"""Scraper para 'Monitoreo de entrada al puerto del nodo (Nuevo)'.

Endpoint confirmado mediante interceptación de red con Playwright:
  POST https://gw.jtlac.com/busdicator/bigdataReport/detail/network_inbound_detail
  routename : OutletEntryMonitoringNew
  waybill   : BILLCODE

El campo recevierNetworkCode toma el valor de jt_user del franquiciado
(su código de red, ej. "PE04022"), que el portal usa para filtrar solo
sus paquetes.

ADVERTENCIA: ese filtro del backend de J&T no es 100% confiable — se ha
observado que ocasionalmente devuelve waybills de OTRAS redes (ver
`OutletMonitor.expected_network` / `last_rejected` más abajo para la
segunda capa de verificación que corrige esto).
"""
from __future__ import annotations

import time
from datetime import date
from typing import Optional

from loguru import logger

from .auth import JTAuth
from .instance_config import (
    JTInstanceConfig,
    API_BASE,
    COUNTRY_ID,
    LANG,
    TIMEZONE,
    USER_AGENT,
)

# ── Constantes confirmadas ─────────────────────────────────────────────────────

_EP        = "/busdicator/bigdataReport/detail/network_inbound_detail"
_ROUTENAME = "OutletEntryMonitoringNew"
_PAGE_SIZE = 500   # máximo cómodo; el portal usa 20 por defecto

# Umbral de contaminación para el circuit breaker. Se disparó una vez
# (2026-07-11: incidente ARE-05 vs ARE-22/ARE-11/ARE-08, 477/542 = 88%
# rechazados) por un fallo transitorio del backend de J&T que ignoró
# recevierNetworkCode por completo. Un puñado de registros sueltos mal
# etiquetados es normal y se descarta en silencio; una MAYORÍA rechazada
# indica que el filtro completo falló, no casos aislados.
_CONTAMINATION_RATIO_THRESHOLD = 0.5
_CONTAMINATION_MIN_REJECTED    = 5   # evita ruido en lotes chicos (ej. 1 de 2)


def _build_headers(token: str) -> dict[str, str]:
    return {
        "content-type": "application/json;charset=UTF-8",
        "accept":        "application/json, text/plain, */*",
        "authtoken":     token,
        "lang":          LANG,
        "langtype":      LANG,
        "timezone":      TIMEZONE,
        "routename":     _ROUTENAME,
        "origin":        "https://jms.jtlac.com",
        "referer":       "https://jms.jtlac.com/",
        "user-agent":    USER_AGENT,
    }


# ── Clase principal ────────────────────────────────────────────────────────────

def _network_matches(detected: Optional[str], expected: str) -> bool:
    """Compara una red detectada (ej. "ARE-22.pdv") contra el código
    esperado (ej. "ARE-22") de forma tolerante (substring, case-insensitive).
    """
    if not detected:
        return False
    return expected.strip().upper() in detected.strip().upper()


class OutletMonitor:
    """Obtiene waybills del 'Monitoreo de entrada al puerto del nodo (Nuevo)'.

    Usa la API interna de J&T JMS directamente con curl_cffi chrome120.
    El login con captcha (OpenCV) se realiza solo si el token expiró.

    Uso:
        monitor  = OutletMonitor(instance_config, expected_network="ARE-22")
        waybills = monitor.fetch_waybills("2026-06-01", "2026-07-03")
        if monitor.last_rejected:
            ...  # waybills descartados por no coincidir con expected_network

    IMPORTANTE — origen de la contaminación cruzada detectada 2026-07-11:
    El payload envía `recevierNetworkCode` (= jt_user del franquiciado) para
    que J&T filtre solo los paquetes de esa red, pero ese filtro del backend
    de J&T no siempre es confiable (ver también la inestabilidad documentada
    de `timeType=2` en este mismo módulo). Cada registro de la respuesta trae
    igualmente su propio `RECEIVER_NETWORK_NAME` (ej. "ARE-22.pdv"), que antes
    se descartaba sin usar. Ahora, si se provee `expected_network`, cada
    registro se contrasta contra ese campo y los que no coinciden se excluyen
    de `fetch_waybills` y quedan disponibles en `self.last_rejected`.
    """

    def __init__(
        self,
        instance_config: JTInstanceConfig,
        expected_network: Optional[str] = None,
    ) -> None:
        self._cfg  = instance_config
        self._auth = JTAuth(instance_config)
        self.expected_network = (expected_network or "").strip() or None
        # Poblado por el último fetch_waybills(): [{"waybill","red_detectada","red_esperada"}]
        self.last_rejected: list[dict] = []
        # Circuit breaker: True si el % de rechazados sugiere que el filtro
        # recevierNetworkCode falló por completo en esta llamada (no solo
        # unos pocos registros sueltos) — ver CONTAMINATION_RATIO_THRESHOLD.
        self.contamination_alert: bool = False
        self.contamination_ratio: float = 0.0

    # ── Punto de entrada público ───────────────────────────────────────────

    def fetch_waybills(
        self,
        start_date: Optional[str] = None,
        end_date:   Optional[str] = None,
        time_type:  int = 1,
    ) -> list[str]:
        """Retorna la lista de waybills (BILLCODE) en el rango de fechas.

        Args:
            start_date: "YYYY-MM-DD" — por defecto: hace 30 días.
            end_date:   "YYYY-MM-DD" — por defecto: hoy.
            time_type:  0 = fecha de creación del pedido (sin datos en rango típico),
                        1 = fecha de generación de datos (default portal — RECOMENDADO,
                            único que da resultados estables/completos: verificado
                            2026-07-06 con match exacto 131/131 contra export manual),
                        2 = fecha de llegada al nodo — NO USAR: el campo es inestable
                            en el backend de J&T, dos llamadas idénticas seguidas
                            devuelven conjuntos casi totalmente distintos de guías,
                        3 = dimensión adicional — trae superset con ruido de otros días.

        Returns:
            Lista de strings con los números de guía (ej. "JPE000008162174").
        """
        if not start_date:
            from datetime import timedelta
            start_date = (date.today() - timedelta(days=30)).isoformat()
        if not end_date:
            end_date = date.today().isoformat()

        sd = f"{start_date} 00:00:00"
        ed = f"{end_date} 23:59:59"

        logger.info(f"[outlet_monitor] Fetching waybills {start_date} → {end_date} "
                    f"timeType={time_type} usuario={self._cfg.jt_user!r} "
                    f"expected_network={self.expected_network!r}")

        self.last_rejected = []
        self.contamination_alert = False
        self.contamination_ratio = 0.0

        token = self._auth.get_token()
        result = self._paginate(token, sd, ed, time_type)

        # Si falló con token en caché, forzar login fresco y reintentar
        if not result:
            logger.info("[outlet_monitor] Sin resultados con token cacheado — forzando login fresco…")
            self._auth.clear_cache()
            token = self._auth.get_token(force=True)
            self.last_rejected = []
            result = self._paginate(token, sd, ed, time_type)

        n_rej = len(self.last_rejected)
        n_total = n_rej + len(result)
        if n_total:
            self.contamination_ratio = n_rej / n_total

        if n_rej:
            logger.warning(
                f"[outlet_monitor] {n_rej} waybill(s) descartados por "
                f"RECEIVER_NETWORK_NAME distinto de {self.expected_network!r}: "
                f"{[r['waybill'] for r in self.last_rejected][:20]}"
            )

        if (n_rej >= _CONTAMINATION_MIN_REJECTED
                and self.contamination_ratio > _CONTAMINATION_RATIO_THRESHOLD):
            self.contamination_alert = True
            logger.critical(
                f"[outlet_monitor] 🚨 CIRCUIT BREAKER — {self.contamination_ratio:.0%} "
                f"de los resultados ({n_rej}/{n_total}) no coinciden con "
                f"{self.expected_network!r}. Esto sugiere que el filtro "
                f"recevierNetworkCode falló por completo en esta llamada "
                f"(no son casos aislados) — revisar antes de confiar en el resto."
            )

        return result

    # ── Paginación ────────────────────────────────────────────────────────

    def _paginate(self, token: str, sd: str, ed: str, time_type: int = 1) -> list[str]:
        try:
            from curl_cffi import requests as _curl
            session = _curl.Session(impersonate="chrome120")
        except ImportError:
            import requests as _curl  # type: ignore
            session = _curl.Session()

        url      = API_BASE + _EP
        headers  = _build_headers(token)
        proxy    = self._cfg.current_proxies() if self._cfg else None
        all_wbs: list[str] = []
        page     = 1

        base_payload = {
            "startTime":           sd,
            "endTime":             ed,
            "timeType":            time_type,
            "recevierNetworkCode": self._cfg.jt_user,
            "countryId":           str(COUNTRY_ID),
        }

        _token_refreshed = False

        while True:
            payload = {**base_payload, "current": page, "size": _PAGE_SIZE}
            try:
                resp = session.post(
                    url, json=payload, headers=headers,
                    timeout=30, proxies=proxy,
                )
                # HTTP 4xx generalmente indica token expirado en J&T
                if resp.status_code in (401, 403, 405) and not _token_refreshed:
                    logger.warning(f"[outlet_monitor] HTTP {resp.status_code} → renovando token…")
                    self._auth.clear_cache()
                    token   = self._auth.get_token(force=True)
                    headers = _build_headers(token)
                    _token_refreshed = True
                    continue  # reintentar misma página con token fresco
                resp.raise_for_status()
                body = resp.json()
            except Exception as exc:
                logger.error(f"[outlet_monitor] Error en página {page}: {exc}")
                break

            code = body.get("code")
            if code in (401, 1001, 1002) or "重新登录" in str(body.get("msg", "")):
                logger.warning("[outlet_monitor] Token expirado — renovando…")
                self._auth.clear_cache()
                token   = self._auth.get_token(force=True)
                headers = _build_headers(token)
                continue   # reintentar la misma página

            data = body.get("data")
            if not data:
                logger.warning(f"[outlet_monitor] Sin datos en página {page}: "
                               f"code={code} msg={body.get('msg','')[:60]}")
                break

            # Extraer lista de registros
            records: list[dict] = []
            if isinstance(data, list):
                records = data
            elif isinstance(data, dict):
                for k in ("list", "records", "rows", "items", "content"):
                    if isinstance(data.get(k), list):
                        records = data[k]
                        break

            if not records:
                break

            # El campo waybill confirmado es BILLCODE. Cada registro también
            # trae su propia red de destino (RECEIVER_NETWORK_NAME) — se usa
            # como segunda capa de verificación cuando expected_network está
            # configurado (ver docstring de la clase).
            for rec in records:
                wb = rec.get("BILLCODE") or rec.get("billCode") or rec.get("waybillNo")
                if not (wb and isinstance(wb, str)):
                    continue
                wb = wb.strip()

                red_detectada = (
                    rec.get("RECEIVER_NETWORK_NAME")
                    or rec.get("receiverNetworkName")
                )

                # Solo se rechaza cuando J&T SÍ informó una red y esta no
                # coincide con la esperada. Si el campo viene vacío (a veces
                # J&T no lo llena) no se puede verificar, así que se deja
                # pasar como antes para no perder paquetes legítimos.
                if self.expected_network and red_detectada and not _network_matches(red_detectada, self.expected_network):
                    self.last_rejected.append({
                        "waybill":       wb,
                        "red_detectada": red_detectada,
                        "red_esperada":  self.expected_network,
                    })
                    continue

                all_wbs.append(wb)

            total = data.get("total", 0) if isinstance(data, dict) else len(records)
            logger.info(f"[outlet_monitor] Pág {page}: {len(records)} registros "
                        f"(acum={len(all_wbs)} / total={total})")

            if len(all_wbs) >= total or len(records) < _PAGE_SIZE:
                break

            page += 1
            time.sleep(0.3)   # cortesía al servidor

        logger.success(f"[outlet_monitor] Total waybills obtenidos: {len(all_wbs)}")
        return list(dict.fromkeys(all_wbs))   # deduplicar conservando orden
