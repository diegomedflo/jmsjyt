"""Scraper para 'Monitoreo de entrada al puerto del nodo (Nuevo)'.

URL del portal: https://jms.jtlac.com/app/businessIndicatorIndex/OutletEntryMonitoringNew

Estrategias (se intentan en orden hasta obtener resultados):
  1. Prueba-y-error de endpoints API con curl_cffi (rápido, ~5 s).
  2. Interceptación de red con Playwright para descubrir el endpoint real (~30 s).
  3. Raspado HTML página por página con Playwright como último recurso.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from datetime import date, timedelta
from typing import Optional

from loguru import logger

from .auth import JTAuth
from .instance_config import (
    JTInstanceConfig,
    API_BASE,
    COUNTRY_ID,
    HEADLESS,
    LANG,
    TIMEZONE,
    USER_AGENT,
)

# URL de la página del portal
_OUTLET_URL = (
    "https://jms.jtlac.com/app/businessIndicatorIndex/OutletEntryMonitoringNew"
    "?title=Monitoreo%20de%20entrada%20al%20puerto%20del%20nodo%20%28Nuevo%29&moduleCode="
)

# ── Candidatos de endpoints (prueba-y-error) ──────────────────────────────────

_CANDIDATE_ENDPOINTS = [
    "/operatingplatform/outletEntryMonitoringNew/detailList",
    "/operatingplatform/outletEntryMonitoringNew/pageList",
    "/operatingplatform/outletEntryMonitoring/detailList",
    "/operatingplatform/outletEntryMonitoring/pageList",
    "/businessIndicator/outletEntryMonitoringNew/detailList",
    "/businessIndicator/outletEntryMonitoringNew/pageList",
    "/businessIndicator/outletEntryMonitoring/detailList",
    "/businessIndicator/outletEntryMonitoring/pageList",
    "/operatingplatform/nodeEntryMonitoringNew/detailList",
    "/operatingplatform/nodeEntryMonitoringNew/pageList",
    "/operatingplatform/nodeEntryMonitoring/detailList",
    "/operatingplatform/nodeEntryMonitoring/pageList",
    "/operatingplatform/nodeMonitoring/detailList",
    "/operatingplatform/nodeMonitoring/pageList",
    "/businessIndicator/nodeEntryMonitoring/detailList",
    "/businessIndicator/nodeEntryMonitoring/pageList",
]

# Variantes de payload base (se rellena pageNum/pageSize por separado)
def _payload_variants(sd: str, ed: str, country: str) -> list[dict]:
    return [
        {"startDate": sd, "endDate": ed, "countryId": country},
        {"startTime": sd, "endTime": ed, "countryId": country},
        {"startDate": sd, "endDate": ed, "countryId": country, "timeType": 1},
        {"startDate": sd, "endDate": ed, "countryId": country, "timeType": 0},
        {"startDate": sd, "endDate": ed, "countryId": country, "dataTimeType": 1},
        {"startDate": sd, "endDate": ed},
        {"startTime": sd, "endTime": ed},
    ]

# Campos posibles donde se almacena el número de guía en cada registro
_WAYBILL_FIELDS = [
    "waybillNo", "waybill_no", "trackingNo", "orderNo",
    "guiaNo", "guia_no", "billNo", "expressNo",
]

# Regex para detectar un número de guía por su patrón (letras + muchos dígitos)
_WAYBILL_RE = re.compile(r"^[A-Z]{2,5}\d{6,}$")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fmt_start(d: str) -> str:
    return f"{d} 00:00:00"


def _fmt_end(d: str) -> str:
    return f"{d} 23:59:59"


def _extract_waybill(record: dict) -> Optional[str]:
    """Extrae el número de guía de un registro de la API."""
    for key in _WAYBILL_FIELDS:
        val = record.get(key)
        if val and isinstance(val, str):
            v = val.strip()
            if v:
                return v
    # Fallback: buscar cualquier campo que parezca un waybill
    for val in record.values():
        if isinstance(val, str) and _WAYBILL_RE.match(val.strip()):
            return val.strip()
    return None


def _extract_list_from_data(data) -> Optional[list]:
    """Extrae la lista de registros de la sección 'data' de la respuesta."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("list", "records", "rows", "items", "data", "content"):
            val = data.get(key)
            if isinstance(val, list):
                return val
    return None


def _build_headers(token: str, routename: str = "outletEntryMonitoringNew") -> dict:
    return {
        "content-type": "application/json;charset=UTF-8",
        "accept":        "application/json, text/plain, */*",
        "authtoken":     token,
        "lang":          LANG,
        "langtype":      LANG,
        "timezone":      TIMEZONE,
        "routename":     routename,
        "origin":        "https://jms.jtlac.com",
        "referer":       "https://jms.jtlac.com/",
        "user-agent":    USER_AGENT,
    }


# ── Clase principal ────────────────────────────────────────────────────────────

class OutletMonitor:
    """Obtiene la lista de waybills del 'Monitoreo de entrada al puerto del nodo'.

    Uso:
        monitor = OutletMonitor(instance_config)
        waybills = monitor.fetch_waybills("2026-06-01", "2026-07-03")
    """

    def __init__(self, instance_config: JTInstanceConfig) -> None:
        self._cfg  = instance_config
        self._auth = JTAuth(instance_config)

    # ── Punto de entrada público ───────────────────────────────────────────

    def fetch_waybills(
        self,
        start_date: Optional[str] = None,
        end_date:   Optional[str] = None,
    ) -> list[str]:
        """Retorna la lista de números de guía en el rango de fechas dado.

        start_date / end_date: "YYYY-MM-DD" (por defecto: primer día del mes
        actual hasta hoy).

        El método prueba tres estrategias en orden y retorna con la primera
        que tenga éxito.
        """
        if not start_date:
            today = date.today()
            start_date = today.replace(day=1).isoformat()
        if not end_date:
            end_date = date.today().isoformat()

        sd = _fmt_start(start_date)
        ed = _fmt_end(end_date)

        logger.info(f"[outlet_monitor] Fetching waybills {start_date} → {end_date}")

        token = self._auth.get_token()

        # ── Estrategia 1: Prueba-y-error de endpoints API ─────────────────
        logger.info("[outlet_monitor] Estrategia 1: prueba-y-error de endpoints API")
        result = self._try_api_endpoints(token, sd, ed)
        if result is not None:
            logger.success(f"[outlet_monitor] Estrategia 1 OK — {len(result)} waybills")
            return result

        # ── Estrategia 2: Interceptación con Playwright ───────────────────
        logger.info("[outlet_monitor] Estrategia 2: interceptación de red con Playwright")
        try:
            result = asyncio.run(self._intercept_via_playwright(token, sd, ed))
            if result is not None:
                logger.success(f"[outlet_monitor] Estrategia 2 OK — {len(result)} waybills")
                return result
        except Exception as exc:
            logger.warning(f"[outlet_monitor] Estrategia 2 falló: {exc}")

        # ── Estrategia 3: Raspado HTML página por página ──────────────────
        logger.info("[outlet_monitor] Estrategia 3: raspado HTML con Playwright")
        try:
            result = asyncio.run(self._scrape_via_playwright(token, sd, ed))
            if result:
                logger.success(f"[outlet_monitor] Estrategia 3 OK — {len(result)} waybills")
                return result
        except Exception as exc:
            logger.error(f"[outlet_monitor] Estrategia 3 falló: {exc}")

        raise RuntimeError(
            "No se pudieron obtener waybills del portal J&T. "
            "Revisa los logs para ver qué endpoints se probaron."
        )

    # ── Estrategia 1: prueba-y-error de endpoints ─────────────────────────

    def _try_api_endpoints(
        self, token: str, sd: str, ed: str
    ) -> Optional[list[str]]:
        try:
            from curl_cffi import requests as _curl
            session = _curl.Session(impersonate="chrome120")
        except ImportError:
            import requests as _curl  # type: ignore
            session = _curl.Session()

        proxy = self._cfg.current_proxies() if self._cfg else None

        for endpoint in _CANDIDATE_ENDPOINTS:
            url = API_BASE + endpoint
            for base_payload in _payload_variants(sd, ed, str(COUNTRY_ID)):
                # Sondeo rápido con pageSize=1
                probe_payload = {**base_payload, "pageNum": 1, "pageSize": 1}
                try:
                    resp = session.post(
                        url,
                        json=probe_payload,
                        headers=_build_headers(token),
                        timeout=15,
                        proxies=proxy,
                    )
                except Exception as exc:
                    logger.debug(f"[API] {endpoint} → conexión fallida: {exc}")
                    continue

                if resp.status_code in (401, 403, 404, 405):
                    logger.debug(f"[API] {endpoint} → HTTP {resp.status_code}")
                    break  # Este endpoint no existe, pasar al siguiente

                if resp.status_code != 200:
                    logger.debug(f"[API] {endpoint} → HTTP {resp.status_code}")
                    continue

                try:
                    data_resp = resp.json()
                except Exception:
                    continue

                code = data_resp.get("code")
                if code in (401, 1001, 1002) or "重新登录" in str(data_resp.get("msg", "")):
                    logger.warning("[API] Token expirado durante prueba de endpoints")
                    return None  # No vale la pena continuar sin token válido

                if code not in ("1", 1, "200", 200):
                    logger.debug(f"[API] {endpoint} code={code} — payload no coincide")
                    continue

                inner_data = data_resp.get("data")
                if not inner_data:
                    logger.debug(f"[API] {endpoint} — data vacío con este payload")
                    continue

                lst = _extract_list_from_data(inner_data)
                total = (inner_data.get("total", 0) if isinstance(inner_data, dict) else 0)

                logger.success(f"[API] Endpoint válido: {endpoint} — total={total}")
                logger.info(f"[API] Payload válido: {base_payload}")

                # ── Paginación completa ────────────────────────────────────
                return self._paginate_api(session, url, base_payload, token, proxy)

        return None

    def _paginate_api(
        self, session, url: str, base_payload: dict, token: str, proxy
    ) -> list[str]:
        page_size = 500
        all_waybills: list[str] = []
        page = 1

        while True:
            payload = {**base_payload, "pageNum": page, "pageSize": page_size}
            try:
                resp = session.post(
                    url,
                    json=payload,
                    headers=_build_headers(token),
                    timeout=30,
                    proxies=proxy,
                )
                resp.raise_for_status()
                data_resp = resp.json()
            except Exception as exc:
                logger.warning(f"[API] Paginación falló en página {page}: {exc}")
                break

            inner = data_resp.get("data")
            records = _extract_list_from_data(inner)
            if not records:
                break

            for rec in records:
                wb = _extract_waybill(rec)
                if wb:
                    all_waybills.append(wb)

            total = inner.get("total", 0) if isinstance(inner, dict) else 0
            logger.info(f"[API] Página {page}: {len(records)} registros (total={total})")

            if len(all_waybills) >= total or len(records) < page_size:
                break
            page += 1
            time.sleep(0.3)  # cortesía

        return all_waybills

    # ── Estrategia 2: Playwright con interceptación de red ────────────────

    async def _intercept_via_playwright(
        self, token: str, sd: str, ed: str
    ) -> Optional[list[str]]:
        """Navega al portal con el token inyectado en localStorage e intercepta
        la llamada real a la API para descubrir el endpoint exacto."""
        from playwright.async_api import async_playwright

        discovered_url: list[str]   = []
        discovered_payload: list[dict] = []
        first_records: list[dict]   = []

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=HEADLESS,
                args=["--no-sandbox", "--disable-blink-features=AutomationControlled", "--disable-dev-shm-usage"],
            )
            context = await browser.new_context(
                user_agent=USER_AGENT,
                locale="es-PE",
                proxy=self._cfg.playwright_proxy() if self._cfg else None,
            )
            page = await context.new_page()

            # Interceptar requests ANTES de navegar
            async def handle_request(request):
                url = request.url
                if request.method == "POST" and (
                    "operatingplatform" in url or "businessIndicator" in url
                ) and "gw.jtlac.com" in url:
                    try:
                        raw = request.post_data
                        if raw:
                            pl = json.loads(raw)
                            path = url.replace("https://gw.jtlac.com", "").split("?")[0]
                            discovered_url.append(path)
                            discovered_payload.append(pl)
                            logger.info(f"[intercept] Request capturado: {path}")
                            logger.info(f"[intercept] Payload: {pl}")
                    except Exception:
                        pass

            async def handle_response(response):
                url = response.url
                if response.status == 200 and "gw.jtlac.com" in url and (
                    "operatingplatform" in url or "businessIndicator" in url
                ):
                    try:
                        body = await response.json()
                        inner = body.get("data")
                        if inner:
                            lst = _extract_list_from_data(inner)
                            if lst:
                                first_records.extend(lst)
                    except Exception:
                        pass

            page.on("request",  handle_request)
            page.on("response", handle_response)

            # Ir a jms.jtlac.com e inyectar el token en localStorage
            try:
                await page.goto("https://jms.jtlac.com", wait_until="domcontentloaded", timeout=30_000)
                await page.evaluate(f"() => localStorage.setItem('YL_TOKEN', {json.dumps(token)})")
                logger.info("[intercept] Token inyectado en localStorage")
            except Exception as exc:
                logger.warning(f"[intercept] No se pudo inyectar token: {exc}")
                await browser.close()
                return None

            # Navegar a la página objetivo
            try:
                await page.goto(_OUTLET_URL, wait_until="domcontentloaded", timeout=60_000)
                await page.wait_for_timeout(3000)
            except Exception as exc:
                logger.warning(f"[intercept] No se pudo cargar la página: {exc}")
                await browser.close()
                return None

            # Intentar hacer clic en "Detalles"
            for sel in ('text=Detalles', 'li:has-text("Detalles")', '.el-tabs__item:has-text("Detalles")'):
                try:
                    await page.click(sel, timeout=3000)
                    await page.wait_for_timeout(800)
                    break
                except Exception:
                    pass

            # Intentar ajustar la fecha de inicio (eliminar y reescribir)
            try:
                date_inputs = await page.query_selector_all('input[type="text"]')
                start_str = sd[:10]  # "YYYY-MM-DD"
                # El primer input de fecha debería ser la fecha de inicio
                for inp in date_inputs[:4]:
                    val = await inp.input_value()
                    if val and re.match(r"\d{4}-\d{2}-\d{2}", val):
                        await inp.triple_click()
                        await inp.type(start_str)
                        await page.keyboard.press("Enter")
                        await page.wait_for_timeout(400)
                        break
            except Exception:
                pass

            # Hacer clic en "Buscar"
            for sel in (
                'button:has-text("Buscar")',
                '.el-button:has-text("Buscar")',
                'button.search-btn',
            ):
                try:
                    await page.click(sel, timeout=4000)
                    logger.info("[intercept] Clic en Buscar")
                    await page.wait_for_timeout(5000)
                    break
                except Exception:
                    pass

            # Esperar a que lleguen las respuestas
            await page.wait_for_timeout(4000)
            await browser.close()

        if not discovered_url:
            logger.warning("[intercept] No se capturó ningún endpoint de la API")
            return None

        real_endpoint = discovered_url[0]
        real_payload_base = {
            k: v for k, v in discovered_payload[0].items()
            if k not in ("pageNum", "pageSize", "current", "size")
        }
        logger.success(f"[intercept] Endpoint descubierto: {real_endpoint}")
        logger.info(f"[intercept] Payload base: {real_payload_base}")

        # Usar curl_cffi para paginar con el endpoint descubierto
        try:
            from curl_cffi import requests as _curl
            session = _curl.Session(impersonate="chrome120")
        except ImportError:
            import requests as _curl  # type: ignore
            session = _curl.Session()

        url = API_BASE + real_endpoint
        proxy = self._cfg.current_proxies() if self._cfg else None
        return self._paginate_api(session, url, real_payload_base, token, proxy)

    # ── Estrategia 3: Raspado HTML página por página ──────────────────────

    async def _scrape_via_playwright(
        self, token: str, sd: str, ed: str
    ) -> list[str]:
        """Navega al portal, aplica filtros y extrae los waybills de la tabla
        recorriendo cada página."""
        from playwright.async_api import async_playwright

        all_waybills: list[str] = []

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=HEADLESS,
                args=["--no-sandbox", "--disable-blink-features=AutomationControlled", "--disable-dev-shm-usage"],
            )
            context = await browser.new_context(
                user_agent=USER_AGENT,
                locale="es-PE",
                proxy=self._cfg.playwright_proxy() if self._cfg else None,
            )
            page = await context.new_page()

            # Inyectar token
            await page.goto("https://jms.jtlac.com", wait_until="domcontentloaded", timeout=30_000)
            await page.evaluate(f"() => localStorage.setItem('YL_TOKEN', {json.dumps(token)})")

            # Navegar a la página
            await page.goto(_OUTLET_URL, wait_until="domcontentloaded", timeout=60_000)
            await page.wait_for_timeout(3000)

            # Clic en "Detalles"
            for sel in ('text=Detalles', '.el-tabs__item:has-text("Detalles")'):
                try:
                    await page.click(sel, timeout=4000)
                    await page.wait_for_timeout(800)
                    break
                except Exception:
                    pass

            # Buscar
            for sel in ('button:has-text("Buscar")', '.el-button:has-text("Buscar")'):
                try:
                    await page.click(sel, timeout=4000)
                    await page.wait_for_timeout(5000)
                    break
                except Exception:
                    pass

            page_num = 1
            while True:
                logger.info(f"[scrape] Raspando página {page_num}…")
                await page.wait_for_timeout(2000)

                # Extraer waybills de la tabla
                cells = await page.query_selector_all("td:nth-child(2) a, td:nth-child(2) span")
                page_waybills = []
                for cell in cells:
                    txt = (await cell.inner_text()).strip()
                    if txt and _WAYBILL_RE.match(txt):
                        page_waybills.append(txt)

                if not page_waybills:
                    # Intentar buscar por texto directamente
                    rows = await page.query_selector_all("tr.el-table__row")
                    for row in rows:
                        cols = await row.query_selector_all("td")
                        if len(cols) >= 2:
                            txt = (await cols[1].inner_text()).strip()
                            if txt and _WAYBILL_RE.match(txt):
                                page_waybills.append(txt)

                all_waybills.extend(page_waybills)
                logger.info(f"[scrape] Página {page_num}: {len(page_waybills)} waybills")

                if not page_waybills:
                    break

                # Intentar ir a la siguiente página
                next_clicked = False
                for next_sel in (
                    'button[aria-label="Siguiente página"]',
                    '.btn-next',
                    'button:has-text(">")',
                    '.el-pagination .el-pager li.active + li',
                ):
                    try:
                        next_btn = await page.query_selector(next_sel)
                        if next_btn:
                            is_disabled = await next_btn.get_attribute("disabled")
                            if is_disabled:
                                break
                            await next_btn.click()
                            await page.wait_for_timeout(2500)
                            next_clicked = True
                            break
                    except Exception:
                        pass

                if not next_clicked:
                    break
                page_num += 1

                if page_num > 200:  # salvaguarda
                    logger.warning("[scrape] Límite de 200 páginas alcanzado")
                    break

            await browser.close()

        return list(dict.fromkeys(all_waybills))  # deduplicar conservando orden
