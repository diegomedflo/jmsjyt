# Imagen oficial de Playwright para Python — incluye Chromium y todas
# sus dependencias de sistema (libxcb, libxcomposite, etc.) preinstaladas.
FROM mcr.microsoft.com/playwright/python:v1.50.0-jammy

WORKDIR /app

# Dependencias Python primero (capa cacheada si requirements.txt no cambia)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Código de la aplicación
COPY . .

# Puerto expuesto (Railway inyecta $PORT en tiempo de ejecución)
EXPOSE 8080

# Gunicorn: $PORT lo inyecta Railway; default 8080 para tests locales
CMD ["sh", "-c", "gunicorn run:app --bind 0.0.0.0:${PORT:-8080} --workers 2 --timeout 120"]
