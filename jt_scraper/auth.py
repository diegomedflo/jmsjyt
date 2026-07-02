"""Autenticación en jms.jtlac.com — versión multi-tenant.

Cada instancia de ``JTAuth`` opera con las credenciales de un franquiciado
específico (``JTInstanceConfig``).  El cache del token se persiste vía los
callbacks ``token_getter`` / ``token_setter`` del config (normalmente
leer/escribir en la columna ``jt_token_cache`` de la BD).

Flujo:
  1. Si hay token manual en config → se usa directamente.
  2. Si hay cache válido (< 6h) → se reutiliza.
  3. Si no, se hace login con Playwright resolviendo el slider captcha de
     Tencent y se extrae ``YL_TOKEN`` de localStorage.
"""
from __future__ import annotations

import asyncio
import json
import math
import random
import time
from typing import Optional

from loguru import logger

from . import captcha_solver
from .instance_config import (
    JTInstanceConfig,
    HEADLESS,
    CAPTCHA_MAX_ATTEMPTS,
    LOGIN_URL,
    USER_AGENT,
)

# Validez optimista del cache de token.
_TOKEN_CACHE_TTL = 6 * 3600  # 6 horas


class JTAuth:
    """Gestiona autenticación y cache de token para un franquiciado."""

    def __init__(self, config: JTInstanceConfig) -> None:
        self._cfg = config

    # ── Cache ──────────────────────────────────────────────────────────
    def _read_cache(self) -> Optional[str]:
        raw = self._cfg.token_getter()
        if not raw:
            return None
        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
            token = data.get("token")
            ts    = data.get("ts", 0)
            if token and (time.time() - ts) < _TOKEN_CACHE_TTL:
                return token
        except Exception:
            pass
        return None

    def _write_cache(self, token: str) -> None:
        try:
            self._cfg.token_setter(
                json.dumps({"token": token, "ts": time.time()})
            )
        except Exception as exc:
            logger.warning(f"No se pudo guardar cache de token: {exc}")

    def clear_cache(self) -> None:
        self._cfg.token_setter(None)

    # ── Movimiento humano del drag ──────────────────────────────────────
    @staticmethod
    async def _human_drag(page, start_x: float, start_y: float, distance: float) -> None:
        await page.mouse.move(start_x, start_y)
        await page.mouse.down()
        await page.wait_for_timeout(90 + random.randint(0, 80))

        steps = 38 + random.randint(0, 14)
        for i in range(1, steps + 1):
            t = i / steps
            ease = 2 * t * t if t < 0.5 else 1 - ((-2 * t + 2) ** 2) / 2
            x = start_x + distance * ease
            y = start_y + math.sin(t * math.pi) * 2 + random.uniform(-1.2, 1.2)
            await page.mouse.move(x, y)
            await page.wait_for_timeout(random.randint(6, 22))

        await page.mouse.move(start_x + distance + random.uniform(1, 3), start_y)
        await page.wait_for_timeout(random.randint(40, 90))
        await page.mouse.move(start_x + distance, start_y)
        await page.wait_for_timeout(random.randint(80, 160))
        await page.mouse.up()

    # ── Captcha ────────────────────────────────────────────────────────
    async def _solve_captcha_once(self, page) -> bool:
        area  = await page.query_selector(".tencent-captcha-dy__image-area")
        block = await page.query_selector(".tencent-captcha-dy__slider-block")
        if not area or not block:
            return False

        area_box  = await area.bounding_box()
        block_box = await block.bounding_box()
        if not area_box or not block_box:
            return False

        img_bytes = await area.screenshot()
        sol = captcha_solver.solve(img_bytes)
        logger.info(
            f"Captcha: piece={sol.piece_frac:.3f} gap={sol.gap_frac:.3f} "
            f"dist={sol.distance_frac:.3f} conf={sol.confidence:.2f}"
        )

        distance_px = max(8.0, sol.distance_frac * area_box["width"] - 2.0)
        grab_x = block_box["x"] + block_box["width"] / 2
        grab_y = block_box["y"] + block_box["height"] / 2

        await self._human_drag(page, grab_x, grab_y, distance_px)
        await page.wait_for_timeout(1600)

        body = await page.content()
        if any(k in body for k in (
            "验证成功", "验证通过", "Verification successful", "successful"
        )):
            return True
        still = await page.query_selector(".tencent-captcha-dy__image-area")
        return still is None or not await still.is_visible()

    @staticmethod
    async def _refresh_captcha(page) -> None:
        for sel in (
            'img[alt="刷新验证"]',
            'img[alt="Try a new captcha"]',
            ".tencent-captcha-dy__refresh",
        ):
            el = await page.query_selector(sel)
            if el:
                try:
                    await el.click()
                except Exception:
                    pass
                await page.wait_for_timeout(900)
                return

    # ── Login completo ─────────────────────────────────────────────────
    async def _goto_login(self, page) -> None:
        last_err: Optional[Exception] = None
        for i in range(1, 4):
            try:
                await page.goto(
                    LOGIN_URL, wait_until="domcontentloaded", timeout=60_000
                )
                await page.wait_for_selector("input", timeout=40_000, state="attached")
                await page.wait_for_timeout(1500)
                for _ in range(20):
                    has_pwd = await page.evaluate(
                        "() => !!document.querySelector('input[type=\"password\"]')"
                    )
                    if has_pwd:
                        return
                    await page.wait_for_timeout(750)
                return
            except Exception as exc:
                last_err = exc
                logger.debug(f"Carga de login intento {i} falló: {str(exc)[:120]}")
                await page.wait_for_timeout(2500)
        raise RuntimeError(f"No se pudo cargar la página de login: {last_err}")

    async def _fill_credentials(self, page) -> None:
        await page.fill('input[type="password"]', self._cfg.jt_pass)
        await page.evaluate(
            """(val) => {
                const ins = Array.from(document.querySelectorAll('input'));
                const u = ins.find(i => !i.readOnly && i.type !== 'password');
                if (u) {
                    u.value = val;
                    u.dispatchEvent(new Event('input', {bubbles: true}));
                }
            }""",
            self._cfg.jt_user,
        )
        await page.wait_for_timeout(400)

    @staticmethod
    async def _click_login(page) -> None:
        for sel in (
            "button.login-btn",
            'button:has-text("Inicio de sesión")',
            'button:has-text("登录")',
            'button:has-text("Login")',
        ):
            try:
                await page.click(sel, timeout=3000)
                return
            except Exception:
                continue
        raise RuntimeError("No se encontró el botón de login")

    @staticmethod
    async def _dump_debug(page) -> None:
        try:
            path = "/tmp/debug_jt_login.png"
            await page.screenshot(path=path)
            logger.warning(f"Captura de depuración: {path}")
        except Exception:
            pass

    async def login_async(self) -> str:
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=HEADLESS,
                args=[
                    "--no-sandbox",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                ],
            )
            context = await browser.new_context(
                user_agent=USER_AGENT,
                locale="es-PE",
                proxy=self._cfg.playwright_proxy(),
            )
            page = await context.new_page()
            try:
                logger.info(f"Login JMS para usuario {self._cfg.jt_user!r}…")
                await self._goto_login(page)
                await self._fill_credentials(page)
                await self._click_login(page)

                solved = False
                max_attempts = CAPTCHA_MAX_ATTEMPTS
                for attempt in range(1, max_attempts + 1):
                    if "/index" in page.url:
                        solved = True
                        break
                    try:
                        await page.wait_for_selector(
                            ".tencent-captcha-dy__image-area",
                            timeout=15_000,
                            state="visible",
                        )
                    except Exception:
                        if "/index" in page.url:
                            solved = True
                            break
                        await page.wait_for_timeout(1500)
                        continue

                    logger.info(f"Intento de captcha #{attempt}")
                    if await self._solve_captcha_once(page):
                        solved = True
                        break
                    await self._refresh_captcha(page)
                    await page.wait_for_timeout(800)

                if not solved:
                    await self._dump_debug(page)
                    raise RuntimeError(
                        f"No se pudo resolver el captcha para {self._cfg.jt_user!r}"
                    )

                try:
                    await page.wait_for_url("**/index*", timeout=20_000)
                except Exception:
                    pass
                await page.wait_for_timeout(2500)

                # Polling: esperar hasta ~15 s a que el SPA setee el token.
                token: Optional[str] = None
                for _ in range(8):
                    token = await page.evaluate(
                        "() => localStorage.getItem('YL_TOKEN')"
                    )
                    if token:
                        break
                    await page.wait_for_timeout(1800)

                if not token:
                    # Auto-descubrir si la plataforma cambió el nombre del token.
                    ls_dump: dict = await page.evaluate(
                        "() => { const r = {}; for (let i = 0; "
                        "i < localStorage.length; i++) { "
                        "const k = localStorage.key(i); "
                        "r[k] = (localStorage.getItem(k) || '').substring(0, 60); "
                        "} return r; }"
                    )
                    logger.warning(
                        f"YL_TOKEN no encontrado. Claves: {list(ls_dump.keys())}"
                    )
                    for k in ls_dump:
                        if any(h in k.lower() for h in ("token", "auth", "jwt", "yl_")):
                            candidate = await page.evaluate(
                                f"() => localStorage.getItem({json.dumps(k)})"
                            )
                            if candidate and len(candidate) > 10:
                                logger.info(f"Token alternativo en clave: {k!r}")
                                token = candidate
                                break

                if not token:
                    await self._dump_debug(page)
                    raise RuntimeError(
                        f"Login OK pero no se encontró YL_TOKEN para {self._cfg.jt_user!r}"
                    )

                logger.success(f"Token obtenido para {self._cfg.jt_user!r}: {token[:8]}…")
                return token
            finally:
                await browser.close()

    def login(self) -> str:
        """Versión síncrona de :meth:`login_async`.

        Si falla y el proxy de respaldo está disponible pero inactivo, reintenta
        con el proxy activado (cubre bloqueos de IP en la autenticación).
        """
        try:
            return asyncio.run(self.login_async())
        except Exception as exc:
            if not self._cfg.proxy_active and self._cfg.activate_proxy():
                logger.warning(
                    f"Login falló ({exc}) → reintentando vía proxy de respaldo…"
                )
                return asyncio.run(self.login_async())
            raise

    # ── Punto de entrada principal ─────────────────────────────────────
    def get_token(self, force: bool = False) -> str:
        """Devuelve un token válido, reutilizando manual/cache cuando es posible."""
        if self._cfg.manual_token:
            logger.info(f"Usando token manual para {self._cfg.jt_user!r}.")
            return self._cfg.manual_token
        if not force:
            cached = self._read_cache()
            if cached:
                logger.info(f"Reutilizando token en cache para {self._cfg.jt_user!r}.")
                return cached
        token = self.login()
        self._write_cache(token)
        return token
