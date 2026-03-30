FROM mcr.microsoft.com/playwright/python:v1.55.0-jammy

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false \
    SALES_FACTORY_REQUIRE_PDF=1 \
    LIBREOFFICE_BIN=/usr/bin/soffice

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libreoffice libreoffice-writer fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

COPY . .

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir ".[web]"

EXPOSE 10000

CMD ["sh", "-c", "streamlit run web_dashboard.py --server.address 0.0.0.0 --server.port ${PORT:-10000}"]
