# Manual Técnico — JMSJyT SaaS

> Versión 2.0 · Actualizado: 2026-07-03

---

## Índice

1. [Arquitectura general](#1-arquitectura-general)
2. [Sincronización automática de waybills (OutletMonitor)](#2-sincronización-automática-de-waybills-outletmonitor)
3. [Importación manual de Excel](#3-importación-manual-de-excel)
4. [Google Drive — backup de Excels](#4-google-drive--backup-de-excels)
5. [Scraper J&T (jt_scraper)](#5-scraper-jt-jt_scraper)
6. [Cron de alertas de vencimiento](#6-cron-de-alertas-de-vencimiento)
7. [Panel de administración](#7-panel-de-administración)
8. [Variables de entorno](#8-variables-de-entorno)
9. [Comandos útiles](#9-comandos-útiles)

---

## 1. Arquitectura general

```
Railway Cron (cada hora)
        │
        ▼
run_cron_alertas.py
        │
        ├── alertas_service.py
        │       ├── Lee paquetes con estado=pendiente
        │       ├── JTTracker.track() → API J&T (curl_cffi)
        │       ├── Evalúa umbrales de tiempo
        │       └── Envía alertas WhatsApp vía TextMeBot
        │
Admin Panel (Flask)
        │
        ├── Importar Excel  →  parse_excel_waybills() → BD
        ├── Sincronizar     →  OutletMonitor.fetch_waybills() → BD
        └── Importar texto  →  waybills manuales → BD
```

**Stack tecnológico:**
- Flask 3.1 + SQLAlchemy + Flask-Login
- PostgreSQL en Railway
- Playwright (Chromium headless) + OpenCV para captcha
- curl_cffi con TLS fingerprint de Chrome 120
- TextMeBot para WhatsApp
- Google Drive API v3 con OAuth2 personal (token pickle)

---

## 2. Sincronización automática de waybills (OutletMonitor)

### ¿Qué hace?

El botón **"Sincronizar"** en la página de cada franquiciado consulta directamente la API interna de JMS y trae todos los números de guía que están asociados a la cuenta del franquiciado en un rango de fechas. Luego los inserta en la BD, ignorando duplicados.

### Endpoint descubierto (proceso técnico)

El endpoint **no está documentado públicamente**. Se descubrió el 2026-07-03 mediante interceptación de red con Playwright (mismo browser session que el login):

```
POST https://gw.jtlac.com/busdicator/bigdataReport/detail/network_inbound_detail
```

| Header/Parámetro | Valor |
|---|---|
| `routename` (header) | `OutletEntryMonitoringNew` |
| `authtoken` (header) | YL_TOKEN del franquiciado |
| `lang` / `langtype` | `ES` |
| `timezone` | `GMT-0500` |

### Payload de la petición

```json
{
    "startTime":           "2026-06-01 00:00:00",
    "endTime":             "2026-07-03 23:59:59",
    "timeType":            1,
    "recevierNetworkCode": "PE04022",
    "countryId":           "1",
    "current":             1,
    "size":                500
}
```

| Campo | Tipo | Descripción |
|---|---|---|
| `startTime` | `"YYYY-MM-DD HH:MM:SS"` | Inicio del rango de fecha |
| `endTime` | `"YYYY-MM-DD HH:MM:SS"` | Fin del rango de fecha |
| `timeType` | `1` | Tipo de fecha (1 = fecha de generación de datos) |
| `recevierNetworkCode` | string | Código de red del franquiciado (= `jt_user`) |
| `countryId` | `"1"` | ID de país (Perú = 1) |
| `current` | int | Número de página (paginación) |
| `size` | int | Registros por página (máx cómodo: 500) |

### Campo que contiene el waybill

En la respuesta, cada registro usa el campo `BILLCODE` (mayúsculas):

```json
{
    "BILLCODE": "JPE000008162174",
    "PLAN_AIM_NETWORK_NAME": "ARE-02.pdv",
    "RECEIVER_NETWORK_NAME": "ARE-22.pdv",
    "RECEIVER_PROVINCE_NAME": "AREQUIPA",
    "create_time": "2026-06-06"
}
```

### Flujo completo del botón "Sincronizar"

```
1. GET /admin/franquiciados/<id>/paquetes/sincronizar (POST form)
2. Construye JTInstanceConfig con credenciales del franquiciado
3. OutletMonitor.fetch_waybills(start_date, end_date)
   a. JTAuth.get_token() → si token en caché BD: reutiliza
                         → si expirado: login con Playwright + OpenCV
   b. curl_cffi.Session(impersonate="chrome120").post(endpoint, payload)
   c. Pagina hasta obtener todos los registros
   d. Extrae BILLCODE de cada registro
4. import_waybills(waybills) → inserta en BD, ignora duplicados
5. Registra en tabla excel_imports con import_mode="auto"
6. Flash con resultado: N nuevos, N duplicados
```

### Modificar el rango de fechas

Por defecto el botón "Sincronizar" usa:
- `start_date` = primer día del mes actual
- `end_date` = hoy

Para modificarlo, editar la ruta en [app/blueprints/admin/routes.py](app/blueprints/admin/routes.py):

```python
# Línea ~250 en la ruta paquetes_sincronizar
start_date = date.today().replace(day=1).isoformat()  # ← cambiar aquí
end_date   = date.today().isoformat()                  # ← y aquí
```

Ejemplo para siempre buscar los últimos 90 días:

```python
from datetime import date, timedelta
start_date = (date.today() - timedelta(days=90)).isoformat()
end_date   = date.today().isoformat()
```

### Otros filtros disponibles en el payload

Según la estructura del portal J&T, se pueden agregar estos campos opcionales al payload si el franquiciado lo necesita (no verificados, basados en la UI del portal):

| Campo opcional | Ejemplo | Descripción |
|---|---|---|
| `timeType` | `0` o `1` | 0 = fecha de creación, 1 = fecha de generación de datos |
| `receivedStatus` | `1` | Filtrar por estado de recepción |
| `isAbnormal` | `0` o `1` | Filtrar solo paquetes anómalos |

Para agregar un filtro, editarlo en `jt_scraper/outlet_monitor.py`:

```python
base_payload = {
    "startTime":           sd,
    "endTime":             ed,
    "timeType":            1,
    "recevierNetworkCode": self._cfg.jt_user,
    "countryId":           str(COUNTRY_ID),
    # "receivedStatus":    1,   # ← agregar aquí si se necesita
}
```

---

## 3. Importación manual de Excel

### ¿Cuándo usarla?

Cuando se descarga manualmente el Excel desde el portal JMS y se quiere subirlo al sistema sin usar el scraper.

### Cómo obtener el Excel desde JMS

1. Iniciar sesión en [jms.jtlac.com](https://jms.jtlac.com)
2. Ir a **Indicadores operativos → Monitoreo de entrada al puerto del nodo (Nuevo)**
3. Clic en pestaña **Detalles**
4. Elegir rango de fechas: inicio = 1 de junio (o la fecha más antigua), fin = fecha más reciente disponible
5. Clic en **Buscar**
6. Clic en **Exportar** (junto al botón Buscar)
7. Clic en **Centro de descargas** → esperar estado "Terminado"
8. Clic en el ícono de descarga en la columna **Operación**

### Cómo importar el Excel en el panel

1. Panel Admin → Franquiciado → botón **"Importar Excel"**
2. Seleccionar el archivo `.xlsx` descargado
3. Clic en **Importar paquetes**

### ¿Qué columna se usa?

El parser busca automáticamente la columna **"Número de Guía"** (o variantes: `waybillNo`, `tracking`, `codigodeguia`, etc.) en las primeras 10 filas del Excel. La detección es insensible a mayúsculas/minúsculas y tildes.

### Deduplicación

El sistema verifica en la BD cuáles waybills ya existen para ese franquiciado (`UNIQUE (franquiciado_id, waybill_no)`) y solo inserta los nuevos. Los duplicados se reportan pero no generan error.

### Registro de importaciones

Cada importación queda registrada en la tabla `excel_imports`:

| Campo | Descripción |
|---|---|
| `filename` | Nombre del archivo subido |
| `drive_file_id` | ID en Google Drive (si se subió) |
| `total_waybills` | Total de códigos en el Excel |
| `nuevos` | Códigos efectivamente insertados |
| `duplicados` | Códigos que ya existían |
| `import_mode` | `'manual'` o `'auto'` |
| `imported_at` | Timestamp de la importación |

---

## 4. Google Drive — backup de Excels

### Propósito

Cada Excel importado manualmente se sube automáticamente a una carpeta de Google Drive como respaldo, y se guarda el link en la BD.

### Carpeta configurada

```
https://drive.google.com/drive/folders/1Uq8Po3FBcI37wB1QTmFyZi4NjQsDcHSM
```

### Configuración (variables de entorno)

| Variable | Descripción |
|---|---|
| `GOOGLE_DRIVE_FOLDER_ID` | ID de la carpeta Drive (por defecto ya tiene el valor correcto) |
| `TOKEN_PICKLE_B64` | Token OAuth2 personal codificado en base64 (para Railway) |
| `DRIVE_TOKEN_PICKLE_PATH` | Ruta al archivo `token.pickle` (para local) |

### Generar TOKEN_PICKLE_B64 para Railway

```python
# Ejecutar una vez localmente:
import base64
with open("token.pickle", "rb") as f:
    print(base64.b64encode(f.read()).decode())
# Pegar el resultado en la variable de entorno TOKEN_PICKLE_B64 de Railway
```

### Cómo funciona

```
Upload Excel → google_drive_service.upload_file(bytes, filename, mime_type, folder_id)
            → OAuth2 con token.pickle personal
            → Drive API v3 → retorna file_id
            → file_id guardado en excel_imports.drive_file_id
            → Link: https://drive.google.com/file/d/{file_id}/view
```

Si Drive no está configurado (sin `token.pickle`), la importación funciona igual pero sin subir a Drive (muestra un aviso).

---

## 5. Scraper J&T (jt_scraper)

### Tecnologías anti-bot (idéntico a vasmat)

| Tecnología | Rol |
|---|---|
| **Playwright + Chromium headless** | Login en jms.jtlac.com con `--disable-blink-features=AutomationControlled` |
| **OpenCV** | Detecta la posición del hueco en el captcha Tencent Slider |
| **Human drag (ease-in-out + seno)** | Simula movimiento de ratón humano al arrastrar el slider |
| **curl_cffi chrome120** | TLS fingerprint de Chrome 120 para las peticiones API |
| **Tenacity** | Reintentos exponenciales ante errores de red |
| **YL_TOKEN** | JWT extraído de `localStorage` tras login exitoso |

### Flujo de autenticación

```
1. JTAuth.get_token()
   ├── Lee caché en BD (franquiciados.jt_token_cache)
   ├── Si válido (< 6h): retorna directamente ← NO abre browser
   └── Si expirado:
       ├── Playwright abre Chromium headless
       ├── Navega a https://jms.jtlac.com/login
       ├── Rellena usuario/contraseña automáticamente
       ├── Detecta captcha Tencent Slider
       ├── captcha_solver.solve(screenshot) → OpenCV mide distancia_frac
       ├── _human_drag(slider, distance) → ease-in-out + sin(t*π) + overshoot
       ├── Si captcha OK → espera redirección a /index
       ├── Extrae YL_TOKEN de localStorage
       ├── Guarda en BD via token_setter callback
       └── Cierra browser
2. curl_cffi.Session(impersonate="chrome120").post(endpoint, payload, authtoken=token)
```

### Flujo de tracking de paquetes

```
JTTracker.track(waybill_no)
    ├── JTClient.get_order_detail(waybill_no) → /operatingplatform/order/getOrderDetail
    ├── JTClient.get_pod_tracking(waybill_no) → /operatingplatform/podTracking/inner/query/keywordList
    ├── parser.build_result() → TrackingResult
    └── Si TokenExpired → JTAuth.get_token(force=True) y reintenta
        Si IPBlocked   → activa proxy Decodo y reintenta
```

### Endpoints de tracking confirmados

| Endpoint | Descripción |
|---|---|
| `POST /authn/checkToken` | Verifica si el token sigue válido |
| `POST /operatingplatform/order/getOrderDetail` | Detalle de una guía |
| `POST /operatingplatform/podTracking/inner/query/keywordList` | Historial de escaneos POD |
| `POST /operatingplatform/abnormalPieceScanList/pageList` | Piezas anómalas |
| `POST /operatingplatform/rebackTransferExpress/applyForPage` | Solicitudes de devolución |

### Endpoint de sincronización de códigos (OutletMonitor)

| Endpoint | Descripción |
|---|---|
| `POST /busdicator/bigdataReport/detail/network_inbound_detail` | Lista de paquetes en el nodo (Detalles tab del portal) |

---

## 6. Cron de alertas de vencimiento

### Trigger

Railway ejecuta `python run_cron_alertas.py` **cada hora** según el cron configurado en `railway.toml`.

### Lógica de umbrales (hora Perú)

| Hora (Perú) | Umbral de alerta |
|---|---|
| 8am – 9pm | `Configuracion.umbral_dia` (default: 3h) |
| 10pm | `Configuracion.umbral_22` (default: 10h) |
| 11pm | `Configuracion.umbral_23` (default: 9h) |
| 12am – 7am | **No ejecuta** |

### ¿Qué hace en cada corrida?

1. Lee hora actual en Perú (GMT-5)
2. Para **cada franquiciado activo** en la BD:
   - Obtiene paquetes con `estado = 'pendiente'`
   - Para cada paquete, llama `JTTracker.track(waybill_no)`
   - Evalúa si el último escaneo superó el umbral configurado
   - Si sí → envía alerta WhatsApp al grupo del franquiciado
3. Registra resultado en tabla `cron_logs`
4. Envía reporte global al grupo de monitoreo del admin

### Cambiar umbrales

Panel Admin → **Configuración** → ajustar los valores de umbral.

También se pueden cambiar directamente en BD:
```sql
UPDATE configuracion SET umbral_dia = 4.0, umbral_22 = 12.0 WHERE id = 1;
```

---

## 7. Panel de administración

### Acceso

`https://tu-dominio.railway.app/` → Login con usuario admin

### Páginas disponibles

| Ruta | Descripción |
|---|---|
| `/admin/` | Dashboard: totales de franquiciados, paquetes, último cron |
| `/admin/franquiciados` | Lista de franquiciados |
| `/admin/franquiciados/nuevo` | Crear franquiciado |
| `/admin/franquiciados/<id>` | Detalle: paquetes, alertas, botones de importar/sincronizar |
| `/admin/franquiciados/<id>/editar` | Editar credenciales |
| `/admin/franquiciados/<id>/paquetes/importar` | Importar waybills por texto |
| `/admin/franquiciados/<id>/paquetes/importar-excel` | Importar Excel de JMS + backup Drive |
| `/admin/franquiciados/<id>/paquetes/sincronizar` | Sincronización automática desde JMS |
| `/admin/paquetes/<id>/cancelar` | Cancelar un paquete |
| `/admin/alertas` | Log de alertas enviadas por WhatsApp |
| `/admin/cron-logs` | Historial de ejecuciones del cron |
| `/admin/configuracion` | Umbrales de alerta y horarios |

### Botones en la página de detalle de franquiciado

| Botón | Acción |
|---|---|
| **Importar (texto)** | Pegar códigos manualmente uno por línea |
| **Importar Excel** | Subir archivo .xlsx exportado de JMS |
| **Sincronizar** | Extrae automáticamente desde JMS API (requiere credenciales válidas) |

---

## 8. Variables de entorno

### Obligatorias (Railway)

| Variable | Descripción |
|---|---|
| `SECRET_KEY` | Clave secreta Flask (string aleatorio largo) |
| `DATABASE_URL` | URI PostgreSQL de Railway |
| `FLASK_ENV` | `production` |

### WhatsApp y monitoreo

| Variable | Descripción |
|---|---|
| `ADMIN_STATUS_API_KEY` | API key de TextMeBot para el grupo del admin |
| `ADMIN_STATUS_GROUP` | ID del grupo WhatsApp del admin |

### Scraper J&T

| Variable | Descripción | Default |
|---|---|---|
| `JT_HEADLESS` | `true` para headless (Railway), `false` para ver el browser | `true` |
| `JT_CAPTCHA_ATTEMPTS` | Intentos máximos de resolver el captcha | `6` |
| `JT_API_BASE` | Base URL del gateway J&T | `https://gw.jtlac.com` |
| `JT_COUNTRY_ID` | ID de país | `1` |
| `JT_PROXY_USER` | Usuario proxy Decodo (opcional) | — |
| `JT_PROXY_PASS` | Contraseña proxy Decodo (opcional) | — |
| `JT_PROXY_HOST` | Host proxy Decodo | `gate.decodo.com` |
| `JT_PROXY_PORT` | Puerto proxy Decodo | `10001` |

### Google Drive

| Variable | Descripción |
|---|---|
| `GOOGLE_DRIVE_FOLDER_ID` | ID carpeta Drive (default: `1Uq8Po3FBcI37wB1QTmFyZi4NjQsDcHSM`) |
| `TOKEN_PICKLE_B64` | Token OAuth2 en base64 (usar en Railway) |
| `DRIVE_TOKEN_PICKLE_PATH` | Ruta a `token.pickle` local (usar en desarrollo) |

---

## 9. Comandos útiles

### Arrancar localmente

```powershell
cd D:\ProyectosPython\JMSJyT
.venv\Scripts\Activate.ps1
$env:FLASK_ENV="development"
python run.py
# App en: http://localhost:5000
```

### Aplicar cambios de BD (local)

```powershell
$env:PGPASSWORD="postgres"
psql -U postgres -d jmsjyt -f "D:\ProyectosPython\JMSJyT\sql\schema.sql"
```

### Aplicar cambios de BD (Railway)

```powershell
$env:PGPASSWORD="QjxLqIKMrlbXWrIiMIBQMTmDythBfyiM"
psql -h reseau.proxy.rlwy.net -p 15338 -U postgres -d railway -f "D:\ProyectosPython\JMSJyT\sql\schema.sql"
```

### Crear primer admin (shell Flask)

```python
from app.models import AdminUser
from app.extensions import db
u = AdminUser(username='admin')
u.set_password('TU_CLAVE_SEGURA')
db.session.add(u); db.session.commit()
```

### Probar el OutletMonitor manualmente

```python
from jt_scraper.outlet_monitor import OutletMonitor
from jt_scraper.instance_config import JTInstanceConfig

store = {}
cfg = JTInstanceConfig(
    jt_user="PE04022",
    jt_pass="tu_clave",
    token_getter=lambda: store.get("r"),
    token_setter=lambda v: store.update({"r": v}),
)

monitor  = OutletMonitor(cfg)
waybills = monitor.fetch_waybills("2026-06-01", "2026-07-03")
print(f"Total: {len(waybills)}")
print(f"Primeros: {waybills[:5]}")
```

### Encodear token.pickle para Railway

```python
import base64
with open("token.pickle", "rb") as f:
    print(base64.b64encode(f.read()).decode())
# Pegar en Railway → Variables → TOKEN_PICKLE_B64
```

---

*Documento generado para el proyecto JMSJyT · [github.com/diegomedflo/jmsjyt](https://github.com/diegomedflo/jmsjyt)*
