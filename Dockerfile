FROM python:3.11-slim

# System dependencies for Playwright, WeasyPrint, fonts, and Node.js
RUN apt-get update && apt-get install -y --no-install-recommends \
    # WeasyPrint deps
    libpango-1.0-0 libpangoft2-1.0-0 libpangocairo-1.0-0 \
    libcairo2 libgdk-pixbuf2.0-0 libffi-dev \
    # Playwright deps
    libnss3 libnspr4 libdbus-1-3 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 \
    libxfixes3 libxrandr2 libgbm1 libasound2 libxshmfence1 \
    # Fonts
    fonts-liberation fonts-noto fontconfig \
    # Build tools
    gcc curl \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Playwright browsers
RUN playwright install chromium --with-deps

# Frontend build
COPY frontend/package*.json ./frontend/
RUN cd frontend && npm install --omit=dev
COPY frontend/ ./frontend/
RUN cd frontend && npm run build

# Backend + data
COPY backend/ ./backend/
COPY sf_accounts.json .

ENV PYTHONPATH=/app
ENV PDF_DIR=/data/pdfs
ENV SCREENSHOTS_DIR=/data/screenshots

RUN mkdir -p /data/pdfs /data/screenshots

EXPOSE 8080

CMD uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8080}
