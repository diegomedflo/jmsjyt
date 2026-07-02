"""Fachada de alto nivel: orquesta auth + API + parsing para un franquiciado."""
from __future__ import annotations

from loguru import logger

from .api_client import JTClient, IPBlocked, TokenExpired
from .auth import JTAuth
from .instance_config import JTInstanceConfig
from .models import TrackingResult
from . import parser


class JTTracker:
    """Rastreador de guías J&T LAC con manejo automático de token.

    Cada instancia opera con las credenciales de un franquiciado específico
    (``JTInstanceConfig``).  El token se renueva automáticamente cuando expira
    y el proxy de respaldo se activa ante señales de bloqueo de IP.
    """

    def __init__(self, instance_config: JTInstanceConfig) -> None:
        self._cfg    = instance_config
        self._auth   = JTAuth(instance_config)
        self._token  = self._auth.get_token()
        self._client = JTClient(self._token, instance_config)

    def _refresh(self) -> None:
        logger.info(f"Renovando token para {self._cfg.jt_user!r}…")
        self._auth.clear_cache()
        self._token  = self._auth.get_token(force=True)
        self._client = JTClient(self._token, self._cfg)

    def track(self, waybill_no: str, include_raw: bool = False) -> TrackingResult:
        """Rastrea una guía.  Re-autentica si el token expiró; activa el proxy
        de respaldo ante señales de bloqueo de IP."""
        waybill_no = waybill_no.strip()
        for attempt in range(3):
            try:
                detail_raw = self._client.get_order_detail(waybill_no)
                pod_raw    = self._client.get_pod_tracking(waybill_no)
                return parser.build_result(
                    waybill_no, detail_raw, pod_raw, include_raw=include_raw
                )
            except TokenExpired:
                if attempt < 2:
                    self._refresh()
                    continue
                raise
            except IPBlocked:
                if attempt < 2 and self._cfg.activate_proxy():
                    logger.warning(
                        "Posible bloqueo de IP → reintentando vía proxy de respaldo…"
                    )
                    self._client = JTClient(self._token, self._cfg)
                    continue
                raise
        raise RuntimeError(f"No fue posible rastrear la guía {waybill_no!r}")

    def track_many(
        self, waybills: list[str], include_raw: bool = False
    ) -> list[TrackingResult]:
        return [self.track(w, include_raw=include_raw) for w in waybills]
