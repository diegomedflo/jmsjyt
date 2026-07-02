"""Cliente HTTP para textmebot.com — envío de mensajes WhatsApp.

API no oficial de textmebot.
Endpoint: GET https://api.textmebot.com/send.php?recipient=...&apikey=...&text=...
"""
from __future__ import annotations

import logging
import urllib.parse
from typing import Tuple

import requests

logger = logging.getLogger(__name__)

ENDPOINT       = "https://api.textmebot.com/send.php"
REQUEST_TIMEOUT = 30  # segundos


def enviar_whatsapp(api_key: str, recipient: str, text: str) -> Tuple[bool, str]:
    """Envía un mensaje vía textmebot.  Devuelve ``(ok, response_texto)``.

    - ``ok``:            True si HTTP 200 y body indica éxito.
    - ``response_texto``: cuerpo crudo para auditoría.
    """
    if not api_key:
        return False, "api_key vacía"
    if not recipient:
        return False, "recipient vacío"
    if not text:
        return False, "texto vacío"

    params = {"recipient": recipient, "apikey": api_key, "text": text}

    try:
        url  = f"{ENDPOINT}?{urllib.parse.urlencode(params)}"
        resp = requests.get(url, timeout=REQUEST_TIMEOUT)
        body = (resp.text or "").strip()

        if resp.status_code != 200:
            return False, f"HTTP {resp.status_code}: {body[:400]}"

        lower = body.lower()
        if any(k in lower for k in ("success", "sent", "ok", "scheduled")):
            return True, body[:2000]

        return False, body[:2000]
    except requests.RequestException as exc:
        logger.exception("Error HTTP textmebot")
        return False, f"RequestException: {exc}"
