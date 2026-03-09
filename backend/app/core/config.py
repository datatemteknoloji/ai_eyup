"""
Application configuration
"""
import os
import sys
from typing import List

class Settings:
    """Application settings"""
    
    # Database
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "postgresql://postgres:postgres@postgres:5432/server_management"
    )
    
    # Ollama AI - Docker container'dan host'a erişim için
    OLLAMA_URL: str = os.getenv("OLLAMA_URL", "http://192.168.1.166:11434")
    OLLAMA_TIMEOUT_SECONDS: int = int(os.getenv("OLLAMA_TIMEOUT_SECONDS", "60"))  # 300s → 60s
    OLLAMA_DEFAULT_MODEL: str = os.getenv("OLLAMA_DEFAULT_MODEL", "llama3.2:3b")
    OLLAMA_EMBED_MODEL: str = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")
    OLLAMA_AUTO_MODEL_ENABLED: bool = os.getenv("OLLAMA_AUTO_MODEL_ENABLED", "true").lower() == "true"

    # RAG (ChromaDB)
    RAG_CHROMA_PATH: str = os.getenv("RAG_CHROMA_PATH", "/var/lib/server_management/chroma")
    RAG_RUNBOOK_TOP_K: int = int(os.getenv("RAG_RUNBOOK_TOP_K", "3"))
    RAG_INCIDENTS_TOP_K: int = int(os.getenv("RAG_INCIDENTS_TOP_K", "3"))
    RAG_METRICS_TOP_K: int = int(os.getenv("RAG_METRICS_TOP_K", "5"))

    # Prometheus
    PROMETHEUS_URL: str = os.getenv("PROMETHEUS_URL", "http://prometheus:9090")
    PUSHGATEWAY_URL: str = os.getenv("PUSHGATEWAY_URL", "http://pushgateway:9091")
    
    # Security - SECRET_KEY ZORUNLU!
    SECRET_KEY: str = os.getenv("SECRET_KEY", "")
    if not SECRET_KEY:
        print("❌ FATAL: SECRET_KEY environment variable is required!")
        print("Set it in .env file: SECRET_KEY=your-random-secret-key-here")
        print("Generate with: openssl rand -hex 32")
        sys.exit(1)
    
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    
    # CORS - Production'da sadece frontend domain
    CORS_ORIGINS: List[str] = os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
    
    # Logging
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    
    # Node Exporter Binary Storage
    NODE_EXPORTER_STORAGE_PATH: str = os.getenv("NODE_EXPORTER_STORAGE_PATH", "/app/static/node_exporter")
    NODE_EXPORTER_DISTRIBUTION_METHOD: str = os.getenv("NODE_EXPORTER_DISTRIBUTION_METHOD", "scp")  # scp, http, or base64
    BACKEND_HOST: str = os.getenv("BACKEND_HOST", "backend")  # Docker compose service name veya IP
    BACKEND_PORT: int = int(os.getenv("BACKEND_PORT", "8000"))

settings = Settings()
