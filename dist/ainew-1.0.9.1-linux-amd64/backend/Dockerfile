FROM python:3.11-slim

ARG APP_VERSION=0.0.0
ENV APP_VERSION=${APP_VERSION}

WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    curl \
    wget \
    openssh-client \
    sshpass \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/static/node_exporter && mkdir -p /app/uploads/packages && mkdir -p /app/repos

RUN addgroup --system appgroup && adduser --system --ingroup appgroup --home /app appuser \
    && chown -R appuser:appgroup /app
USER appuser

EXPOSE 8000

# Production: no --reload; tarih-saat formatlı log (logging.yaml)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--log-config", "/app/logging.yaml"]
