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
    gosu \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# RAG reranker (HuggingFace cross-encoder, bkz. app/services/reranker.py) — bu
# container'da GPU passthrough yok (Ollama ayrı/host tarafında GPU kullanıyor),
# bu yüzden CPU-only torch wheel index'i kullanılıyor; gereksiz CUDA runtime
# kütüphaneleri indirilmez, image küçük kalır. Model yüklenemezse (offline vb.)
# reranker.py sessizce devre dışı kalır, RAG akışı bundan etkilenmez.
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch \
    && pip install --no-cache-dir sentence-transformers==5.6.1 "numpy<2"

COPY . .

RUN mkdir -p /app/static/node_exporter && mkdir -p /app/uploads/packages && mkdir -p /app/repos \
    && mkdir -p /app/chroma

RUN addgroup --system appgroup && adduser --system --ingroup appgroup --home /app appuser \
    && chown -R appuser:appgroup /app \
    && chmod +x /app/docker-entrypoint.sh

# root ile başla: entrypoint bind-mount sahipliğini düzeltir, sonra appuser'a düşer
USER root
ENTRYPOINT ["/app/docker-entrypoint.sh"]
EXPOSE 8000

# Production: no --reload; tarih-saat formatlı log (logging.yaml)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--log-config", "/app/logging.yaml"]
