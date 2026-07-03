"""Servicio para subir/bajar archivos de Google Drive (OAuth2 personal — token pickle)."""

from __future__ import annotations

import base64
import io
import logging
import os
import pickle
import socket

from google.auth.transport.requests import Request as GoogleAuthRequest
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload

logger = logging.getLogger(__name__)


class GoogleDriveService:
    """Wrapper delgado sobre Google Drive API v3 con OAuth2 tipo whatsappbot."""

    def __init__(self) -> None:
        self._folder_id: str | None = None
        self._token_pickle_path: str = os.path.join(os.getcwd(), "token.pickle")

    def init_app(self, app) -> None:
        self._folder_id = app.config.get("GOOGLE_DRIVE_FOLDER_ID")
        self._token_pickle_path = (
            app.config.get("DRIVE_TOKEN_PICKLE_PATH")
            or os.path.join(os.getcwd(), "token.pickle")
        )

    @property
    def has_creds(self) -> bool:
        return self._load_drive_creds() is not None

    @property
    def is_configured(self) -> bool:
        return bool(self._folder_id) and self._load_drive_creds() is not None

    def _load_drive_creds(self):
        try:
            token_b64 = os.environ.get("TOKEN_PICKLE_B64")
            if token_b64:
                creds = pickle.loads(base64.b64decode(token_b64))
            elif os.path.exists(self._token_pickle_path):
                with open(self._token_pickle_path, "rb") as f:
                    creds = pickle.load(f)
            else:
                logger.warning("[DRIVE] Token no encontrado")
                return None

            if creds and creds.expired and creds.refresh_token:
                creds.refresh(GoogleAuthRequest())
                if not token_b64 and os.path.exists(self._token_pickle_path):
                    with open(self._token_pickle_path, "wb") as f:
                        pickle.dump(creds, f)
                logger.info("[DRIVE] Access token refrescado automáticamente")
            return creds
        except Exception:
            logger.exception("[DRIVE] Error cargando token OAuth2")
            return None

    def upload_file(
        self,
        file_bytes: bytes,
        filename: str,
        mime_type: str,
        folder_id: str | None = None,
    ) -> str:
        """Sube cualquier archivo a Drive y retorna el file_id."""
        target_folder = folder_id or self._folder_id
        if not target_folder:
            raise RuntimeError("GoogleDriveService: folder_id no especificado")
        creds = self._load_drive_creds()
        if not creds:
            raise RuntimeError("Sin credenciales OAuth2 para Drive")
        metadata = {"name": filename, "parents": [target_folder]}
        media = MediaIoBaseUpload(io.BytesIO(file_bytes), mimetype=mime_type, resumable=False)
        socket.setdefaulttimeout(120)
        service = build("drive", "v3", credentials=creds, cache_discovery=False)
        created = (
            service.files()
            .create(body=metadata, media_body=media, fields="id", supportsAllDrives=True)
            .execute(num_retries=5)
        )
        return created["id"]

    def download_file(self, file_id: str) -> bytes:
        creds = self._load_drive_creds()
        if not creds:
            raise RuntimeError("Sin credenciales OAuth2 para Drive")
        socket.setdefaulttimeout(120)
        service = build("drive", "v3", credentials=creds, cache_discovery=False)
        request = service.files().get_media(fileId=file_id)
        buf = io.BytesIO()
        downloader = MediaIoBaseDownload(buf, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        return buf.getvalue()

    def get_web_link(self, file_id: str) -> str:
        return f"https://drive.google.com/file/d/{file_id}/view"


google_drive_service = GoogleDriveService()
