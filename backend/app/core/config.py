"""
Application configuration
"""
import os
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
    OLLAMA_TIMEOUT_SECONDS: int = int(os.getenv("OLLAMA_TIMEOUT_SECONDS", "300"))
    OLLAMA_DEFAULT_MODEL: str = os.getenv("OLLAMA_DEFAULT_MODEL", "llama3.2:3b")
    OLLAMA_AUTO_MODEL_ENABLED: bool = os.getenv("OLLAMA_AUTO_MODEL_ENABLED", "true").lower() == "true"
    
    # Prometheus
    PROMETHEUS_URL: str = os.getenv("PROMETHEUS_URL", "http://prometheus:9090")
    PUSHGATEWAY_URL: str = os.getenv("PUSHGATEWAY_URL", "http://pushgateway:9091")
    
    # Security
    SECRET_KEY: str = os.getenv("SECRET_KEY", "your-secret-key-change-in-production")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    
    # CORS
    CORS_ORIGINS: List[str] = ["*"]
    
    # Logging
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    
    # Node Exporter Binary Storage
    NODE_EXPORTER_STORAGE_PATH: str = os.getenv("NODE_EXPORTER_STORAGE_PATH", "/app/static/node_exporter")
    NODE_EXPORTER_DISTRIBUTION_METHOD: str = os.getenv("NODE_EXPORTER_DISTRIBUTION_METHOD", "scp")  # scp, http, or base64
    BACKEND_HOST: str = os.getenv("BACKEND_HOST", "backend")  # Docker compose service name veya IP
    BACKEND_PORT: int = int(os.getenv("BACKEND_PORT", "8000"))

settings = Settings()
