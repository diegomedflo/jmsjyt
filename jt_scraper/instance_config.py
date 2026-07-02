"""Configuración por instancia del scraper J&T LAC.

En lugar de leer variables de entorno a nivel de módulo (como en el proyecto
original), se usa un objeto ``JTInstanceConfig`` que se construye con las
credenciales específicas de cada franquiciado.

Valores compartidos (URLs, endpoints, etc.) se leen una sola vez desde el
entorno al importar el módulo y se almacenan como constantes de clase.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Callable, Optional

from dotenv import load_dotenv

load_dotenv()

# ── Constantes globales (iguales para todos los franquiciados) ────────────────

LOGIN_URL = "https://jms.jtlac.com/login"
INDEX_URL = "https://jms.jtlac.com/index"
API_BASE  = os.getenv("JT_API_BASE", "https://gw.jtlac.com")

COUNTRY_ID = os.getenv("JT_COUNTRY_ID", "1")
LANG       = os.getenv("JT_LANG", "ES")
TIMEZONE   = os.getenv("JT_TIMEZONE", "GMT-0500")

HEADLESS            = os.getenv("JT_HEADLESS", "true").lower() == "true"
CAPTCHA_MAX_ATTEMPTS = int(os.getenv("JT_CAPTCHA_ATTEMPTS", "6"))

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Endpoints de la API (relativos a API_BASE)
EP_CHECK_TOKEN  = "/authn/checkToken"
EP_ORDER_DETAIL = "/operatingplatform/order/getOrderDetail"
EP_POD_TRACKING = "/operatingplatform/podTracking/inner/query/keywordList"
EP_ABNORMAL     = "/operatingplatform/abnormalPieceScanList/pageList"
EP_RETURN_APPLY = "/operatingplatform/rebackTransferExpress/applyForPage"

APPLY_NETWORK_ID = int(os.getenv("JT_APPLY_NETWORK_ID", "1638"))

# Proxy de respaldo (Decodo) — compartido pero activado por instancia
_PROXY_USER = os.getenv("JT_PROXY_USER", "").strip()
_PROXY_PASS = os.getenv("JT_PROXY_PASS", "").strip()
_PROXY_HOST = os.getenv("JT_PROXY_HOST", "gate.decodo.com").strip()
_PROXY_PORT = os.getenv("JT_PROXY_PORT", "10001").strip()
PROXY_AVAILABLE = bool(_PROXY_USER and _PROXY_PASS)


# ── Configuración por instancia ───────────────────────────────────────────────

@dataclass
class JTInstanceConfig:
    """Agrupa las credenciales y callbacks de un franquiciado para el scraper.

    Args:
        jt_user:       Usuario en jms.jtlac.com.
        jt_pass:       Contraseña en jms.jtlac.com.
        manual_token:  Token manual (evita el login con captcha si está presente).
        token_getter:  Callable que devuelve el JSON del cache de token (o None).
        token_setter:  Callable que persiste el JSON del cache (recibe None para borrar).
    """

    jt_user:      str
    jt_pass:      str
    manual_token: str = ""

    # Callbacks de persistencia del token — la capa de servicio los implementa
    # leyendo/escribiendo en la columna ``jt_token_cache`` del franquiciado.
    token_getter: Callable[[], Optional[str]] = field(default=lambda: None)
    token_setter: Callable[[Optional[str]], None] = field(default=lambda _: None)

    # Estado de proxy por instancia (no compartido entre franquiciados)
    _proxy_active: bool = field(default=False, init=False, repr=False)

    # ── Proxy helpers ──────────────────────────────────────────────────
    @property
    def proxy_active(self) -> bool:
        return self._proxy_active

    def activate_proxy(self) -> bool:
        """Activa el proxy de respaldo para esta instancia. Devuelve True si disponible."""
        if not PROXY_AVAILABLE:
            return False
        self._proxy_active = True
        return True

    def current_proxies(self) -> Optional[dict]:
        if self._proxy_active and PROXY_AVAILABLE:
            url = f"http://{_PROXY_USER}:{_PROXY_PASS}@{_PROXY_HOST}:{_PROXY_PORT}"
            return {"http": url, "https": url}
        return None

    def playwright_proxy(self) -> Optional[dict]:
        if not (self._proxy_active and PROXY_AVAILABLE):
            return None
        return {
            "server":   f"http://{_PROXY_HOST}:{_PROXY_PORT}",
            "username": _PROXY_USER,
            "password": _PROXY_PASS,
        }
