"""Resolución del slider captcha de Tencent (TCRS) usado por jms.jtlac.com.

Estrategia:
  El puzzle muestra una pieza clara (slider, izquierda) y un hueco oscuro
  (target, derecha) sobre la misma imagen de fondo. Detectamos ambas muescas
  con visión por computador y devolvemos el desplazamiento horizontal necesario
  expresado como *fracción del ancho de la imagen* (independiente del DPR).

  El módulo de login convierte esa fracción a píxeles reales usando el ancho del
  riel del slider y arrastra con una trayectoria de aspecto humano.
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass
class CaptchaSolution:
    piece_frac: float       # centro de la pieza (0..1 del ancho)
    gap_frac: float         # centro del hueco (0..1 del ancho)
    distance_frac: float    # gap_frac - piece_frac
    confidence: float       # 0..1 heurístico
    width: int
    height: int


def _find_piece_box(gray: np.ndarray) -> tuple[int, int, int, int] | None:
    """Localiza la pieza por su borde casi blanco en la mitad izquierda."""
    h, w = gray.shape
    left_w = int(w * 0.55)
    left = gray[:, :left_w]
    _, white = cv2.threshold(left, 190, 255, cv2.THRESH_BINARY)
    white = cv2.morphologyEx(
        white, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8), iterations=2
    )
    contours, _ = cv2.findContours(white, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    best = None
    best_score = 0.0
    min_side, max_side = w * 0.07, w * 0.24
    for c in contours:
        x, y, bw, bh = cv2.boundingRect(c)
        if not (min_side <= bw <= max_side and min_side <= bh <= max_side):
            continue
        aspect = bw / float(bh)
        if not (0.55 <= aspect <= 1.8):
            continue
        cy = y + bh / 2
        vert_ok = max(0.0, 1.0 - abs(cy - h / 2) / (h / 2))
        score = bw * bh * (0.5 + 0.5 * vert_ok)
        if score > best_score:
            best_score = score
            best = (x, y, bw, bh)
    return best


def _match_gap(edges: np.ndarray, piece_box: tuple[int, int, int, int]) -> tuple[int, float] | None:
    """Centro X del hueco vía template matching del borde de la pieza."""
    x, y, bw, bh = piece_box
    pad = 2
    tmpl = edges[max(0, y - pad): y + bh + pad, max(0, x - pad): x + bw + pad]
    if tmpl.size == 0 or tmpl.shape[0] < 8 or tmpl.shape[1] < 8:
        return None
    search_x0 = x + bw // 2
    region = edges[:, search_x0:]
    if region.shape[1] <= tmpl.shape[1]:
        return None
    res = cv2.matchTemplate(region, tmpl, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(res)
    if max_val < 0.20:
        return None
    gap_x = search_x0 + max_loc[0] + tmpl.shape[1] // 2
    return int(gap_x), float(max_val)


def _fallback_dark_gap(gray: np.ndarray, piece_x: int) -> int:
    """Hueco = columna más oscura a la derecha de la pieza (banda media)."""
    h, w = gray.shape
    band = gray[int(h * 0.25): int(h * 0.78), :]
    col = band.mean(axis=0).astype(np.float32)
    col = cv2.blur(col.reshape(1, -1), (1, 9)).flatten()
    start = max(piece_x + int(w * 0.08), int(w * 0.45))
    seg = col[start: int(w * 0.97)]
    if seg.size == 0:
        return int(w * 0.75)
    return start + int(np.argmin(seg))


def solve(image_bytes: bytes) -> CaptchaSolution:
    """Resuelve el captcha a partir del PNG/JPEG del recuadro del puzzle."""
    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("No se pudo decodificar la imagen del captcha")
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(cv2.GaussianBlur(gray, (3, 3), 0), 50, 150)
    edges = cv2.dilate(edges, np.ones((2, 2), np.uint8), iterations=1)

    piece_box = _find_piece_box(gray)
    confidence = 0.4

    if piece_box is not None:
        px = piece_box[0] + piece_box[2] // 2
        match = _match_gap(edges, piece_box)
        if match is not None:
            gap_x, mval = match
            confidence = min(0.95, 0.6 + mval)
        else:
            gap_x = _fallback_dark_gap(gray, px)
            confidence = 0.6
    else:
        px = int(w * 0.18)
        gap_x = _fallback_dark_gap(gray, px)
        confidence = 0.5

    piece_frac = px / w
    gap_frac = gap_x / w
    return CaptchaSolution(
        piece_frac=piece_frac,
        gap_frac=gap_frac,
        distance_frac=max(0.0, gap_frac - piece_frac),
        confidence=confidence,
        width=w,
        height=h,
    )
