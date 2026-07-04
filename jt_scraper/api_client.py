"""Cliente HTTP ligero para la API de tracking de J&T LAC (gw.jtlac.com).

Usa curl_cffi con impersonación de Chrome para máxima compatibilidad TLS y,
como respaldo, ``requests``.  Requiere un ``authtoken`` y un ``JTInstanceConfig``
para obtener los proxies activos por instancia.
"""
from __future__ import annotations

from typing import Any, Optional

from loguru import logger
from tenacity import (
    retry,
    retry_if_not_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .instance_config import JTInstanceConfig, API_BASE, COUNTRY_ID, LANG, TIMEZONE, USER_AGENT
from .instance_config import (
    EP_CHECK_TOKEN,
    EP_ORDER_DETAIL,
    EP_POD_TRACKING,
    EP_ABNORMAL,
    EP_RETURN_APPLY,
    APPLY_NETWORK_ID,
)

try:
    from curl_cffi import requests as _curl

    _HAS_CURL = True
except Exception:
    import requests as _curl  # type: ignore

    _HAS_CURL = False


class TokenExpired(Exception):
    """El authtoken dejó de ser válido."""


class IPBlocked(Exception):
    """Señal de posible bloqueo de IP (429/503 o respuesta WAF)."""


class JTClient:
    """Cliente HTTP para la API J&T LAC.  Una instancia por token/franquiciado."""

    def __init__(self, token: str, instance_config: Optional[JTInstanceConfig] = None) -> None:
        self.token           = token
        self._instance_cfg   = instance_config
        self._session        = self._build_session()

    def _build_session(self):
        if _HAS_CURL:
            return _curl.Session(impersonate="chrome120")
        return _curl.Session()

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "content-type": "application/json;charset=UTF-8",
            "accept":        "application/json, text/plain, */*",
            "authtoken":     self.token,
            "lang":          LANG,
            "langtype":      LANG,
            "timezone":      TIMEZONE,
            "routename":     "trackingExpress",
            "origin":        "https://jms.jtlac.com",
            "referer":       "https://jms.jtlac.com/",
            "user-agent":    USER_AGENT,
        }

    def _current_proxies(self) -> Optional[dict]:
        if self._instance_cfg:
            return self._instance_cfg.current_proxies()
        return None

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.6, max=6),
        retry=retry_if_not_exception_type(TokenExpired),
        reraise=True,
    )
    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        import time as _time
        url = API_BASE + path
        _t0 = _time.monotonic()
        try:
            resp = self._session.post(
                url,
                json=payload,
                headers=self._headers,
                timeout=25,
                proxies=self._current_proxies(),
            )
        except Exception as exc:
            _dur = _time.monotonic() - _t0
            logger.warning(f"[api] POST {path} — fallo de conexión tras {_dur:.1f}s: {exc}")
            raise IPBlocked(f"Fallo de conexión en {path}: {exc}") from exc

        _dur = _time.monotonic() - _t0
        logger.debug(f"[api] POST {path} — HTTP {resp.status_code} en {_dur:.1f}s")

        if resp.status_code in (401, 403):
            raise TokenExpired(f"HTTP {resp.status_code} en {path}")
        if resp.status_code in (429, 503):
            logger.warning(f"[api] POST {path} — posible bloqueo IP ({resp.status_code})")
            raise IPBlocked(f"HTTP {resp.status_code} en {path}")

        resp.raise_for_status()

        try:
            data = resp.json()
        except Exception as exc:
            raise IPBlocked(f"Respuesta no-JSON en {path}") from exc

        code = data.get("code")
        msg  = str(data.get("msg", ""))
        if code in (401, 1001, 1002) or "重新登录" in msg:
            raise TokenExpired(f"Sesión inválida: {msg}")

        return data

    # ── Endpoints ────────────────────────────────────────────────────────
    def check_token(self) -> bool:
        try:
            data = self._post(EP_CHECK_TOKEN, {})
            return bool(data.get("data"))
        except TokenExpired:
            return False
        except Exception as exc:
            logger.warning(f"check_token error: {exc}")
            return False

    def get_order_detail(self, waybill_no: str) -> dict[str, Any]:
        return self._post(
            EP_ORDER_DETAIL,
            {"waybillNo": waybill_no, "countryId": COUNTRY_ID},
        )

    def get_pod_tracking(self, waybill_no: str) -> dict[str, Any]:
        return self._post(
            EP_POD_TRACKING,
            {
                "keywordList":    [waybill_no],
                "trackingTypeEnum": "WAYBILL",
                "countryId":      COUNTRY_ID,
            },
        )

    def get_abnormal(self, waybill_no: str) -> dict[str, Any]:
        return self._post(
            EP_ABNORMAL,
            {
                "current":   1,
                "size":      100,
                "waybillId": waybill_no,
                "countryId": COUNTRY_ID,
            },
        )

    def get_return_applications(
        self,
        apply_time_from: str,
        apply_time_to:   str,
        apply_network_id: Optional[int] = None,
        status:  int = 0,
        current: int = 1,
        size:    int = 200,
    ) -> dict[str, Any]:
        return self._post(
            EP_RETURN_APPLY,
            {
                "current":        current,
                "size":           size,
                "applyNetworkId": apply_network_id or APPLY_NETWORK_ID,
                "status":         status,
                "applyTimeFrom":  apply_time_from,
                "applyTimeTo":    apply_time_to,
                "countryId":      COUNTRY_ID,
            },
        )
