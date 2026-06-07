# ============================================================
# VendorScout - Dockerfile
# ============================================================
# Base: Microsoft's official Playwright Python image — ships Chromium +
# all OS deps for headless browsing, so the agentic browser "just works".
# (Authentically Microsoft-native: Playwright is a Microsoft project.)
# ============================================================
FROM mcr.microsoft.com/playwright/python:v1.47.0-jammy

WORKDIR /app

# Python deps first (layer cache)
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt \
    && playwright install chromium

# App code
COPY backend /app/backend
COPY frontend /app_frontend
COPY version.py /app/version.py

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/backend \
    TEMPLATES_DIR=/app_frontend/templates \
    STATIC_DIR=/app_frontend/static \
    DATABASE_PATH=/app/data/vendorscout.db \
    HOST=0.0.0.0 \
    PORT=8000

EXPOSE 8000

HEALTHCHECK --interval=60s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')" || exit 1

# app.main:app lives under backend/app
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--app-dir", "backend"]
