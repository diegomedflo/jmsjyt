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

    def track(self, waybill_no: str, include_raw: bool = False, include_detail: bool = True) -> TrackingResult:
        """Rastrea una guía.  Re-autentica si el token expiró; activa el proxy
        de respaldo ante señales de bloqueo de IP.

        Args:
            include_detail: Si True (default) llama a get_order_detail para obtener
                datos del destinatario (solo la primera vez).  Pasar False cuando
                ya fueron guardados.
        """
        waybill_no = waybill_no.strip()

        # ── Detalle estático (no crítico) — un solo intento ───────────────────
        # Si falla por cualquier motivo (token, red, etc.) se omite sin bloquear
        # el tracking del paquete.  El cron lo reintentará en la siguiente corrida
        # si detalle_cargado sigue en False.
        detail_raw: dict = {}
        if include_detail:
            try:
                detail_raw = self._client.get_order_detail(waybill_no)
            except TokenExpired:
                logger.warning(
                    f"[{waybill_no}] get_order_detail: token expirado — "
                    "renovando y omitiendo detalle estático por esta vez."
                )
                try:
                    self._refresh()
                except Exception:
                    pass
            except Exception as exc:
                logger.warning(
                    f"[{waybill_no}] get_order_detail falló (no crítico, se omite): {exc}"
                )

        # ── POD tracking (crítico) — hasta 3 intentos ─────────────────────────
        for attempt in range(3):
            try:
                pod_raw = self._client.get_pod_tracking(waybill_no)
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
