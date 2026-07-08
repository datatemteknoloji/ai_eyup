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
    
    # Yönetim sunucusunun client'lardan erişilebilir IP'si
    # Repo dosyalarını (.repo) sunuculara göndermede kullanılır
    # Örnek: MANAGEMENT_SERVER_IP=192.168.1.100
    MANAGEMENT_SERVER_IP: str = os.getenv("MANAGEMENT_SERVER_IP", "")

    # Ollama AI - Docker container'dan host'a erişim için
    OLLAMA_URL: str = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
    OLLAMA_TIMEOUT_SECONDS: int = int(os.getenv("OLLAMA_TIMEOUT_SECONDS", "60"))
    OLLAMA_DEFAULT_MODEL: str = os.getenv("OLLAMA_DEFAULT_MODEL", "gpt-oss:20b")
    OLLAMA_EMBED_MODEL: str = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")
    OLLAMA_AUTO_MODEL_ENABLED: bool = os.getenv("OLLAMA_AUTO_MODEL_ENABLED", "true").lower() == "true"

    # Uzak AI Gateway (OpenAI-uyumlu, örn. Bifrost) — ayarlıysa ve aktifse tüm chat/agent
    # çağrıları yerel Ollama yerine buraya gider. URL kökü olmalı (örn. .../v1/chat/completions
    # olmadan), API key aynen curl örneğindeki gibi Authorization header'ına konur.
    REMOTE_LLM_ENABLED: bool = os.getenv("REMOTE_LLM_ENABLED", "false").lower() == "true"
    REMOTE_LLM_URL: str = os.getenv("REMOTE_LLM_URL", "")
    REMOTE_LLM_API_KEY: str = os.getenv("REMOTE_LLM_API_KEY", "")
    REMOTE_LLM_MODEL: str = os.getenv("REMOTE_LLM_MODEL", "")
    REMOTE_LLM_TIMEOUT_SECONDS: int = int(os.getenv("REMOTE_LLM_TIMEOUT_SECONDS", "120"))

    # Agentic AI — ana agent (tool-calling) ve guard (safety classifier) modelleri
    AGENT_MODEL: str = os.getenv("AGENT_MODEL", "qwen3.5:35b")
    AGENT_GUARD_ENABLED: bool = os.getenv("AGENT_GUARD_ENABLED", "true").lower() == "true"
    AGENT_GUARD_MODEL: str = os.getenv("AGENT_GUARD_MODEL", "gpt-oss-safeguard:latest")
    # true ise mutating (sudo) işlemlerde, kayıtlı sudo şifresi olsa bile her zaman
    # kullanıcıdan root şifresi istenir (yetki yükseltme onayı).
    AGENT_FORCE_ROOT_PROMPT: bool = os.getenv("AGENT_FORCE_ROOT_PROMPT", "false").lower() == "true"

    # Harici AI Sağlayıcıları (isteğe bağlı - API anahtarı varsa kullanılır)
    # Groq - Ücretsiz, çok hızlı (llama3-70b-8192, mixtral-8x7b, gemma2-9b-it)
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
    GROQ_API_URL: str = "https://api.groq.com/openai/v1/chat/completions"
    # OpenAI - GPT-4o, GPT-4o-mini
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_API_URL: str = os.getenv("OPENAI_API_URL", "https://api.openai.com/v1/chat/completions")
    # Anthropic - Claude 3.5 Sonnet/Haiku
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
    ANTHROPIC_API_URL: str = "https://api.anthropic.com/v1/messages"
    # OpenRouter - 100+ model tek API (openai/gpt-4o, anthropic/claude-3.5-sonnet, vs.)
    OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY", "")
    OPENROUTER_API_URL: str = "https://openrouter.ai/api/v1/chat/completions"

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
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))
    # İlk admin parolası (yalnızca hiç kullanıcı yokken seed'de kullanılır)
    ADMIN_DEFAULT_PASSWORD: str = os.getenv("ADMIN_DEFAULT_PASSWORD", "admin123")
    
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


def get_active_model(db) -> str:
    """DB'den seçilen aktif Ollama modelini okur. Yoksa config default'una döner."""
    try:
        from app.models.app_settings import AppSettings
        row = db.query(AppSettings).filter(AppSettings.key == "ollama_active_model").first()
        if row and row.value:
            return row.value
    except Exception:
        pass
    return settings.OLLAMA_DEFAULT_MODEL


def _get_setting(db, key: str, default: str) -> str:
    try:
        from app.models.app_settings import AppSettings
        row = db.query(AppSettings).filter(AppSettings.key == key).first()
        if row and row.value:
            return row.value
    except Exception:
        pass
    return default


def get_agent_model(db) -> str:
    """Agent (tool-calling) modeli — app_settings override, yoksa config."""
    return _get_setting(db, "agent_active_model", settings.AGENT_MODEL)


def get_guard_model(db) -> str:
    """Guard (safety classifier) modeli — app_settings override, yoksa config."""
    return _get_setting(db, "agent_guard_model", settings.AGENT_GUARD_MODEL)


def remote_llm_enabled() -> bool:
    """Uzak (OpenAI-uyumlu) LLM gateway aktif mi — URL + API key ayarlı olmalı."""
    return bool(settings.REMOTE_LLM_ENABLED and settings.REMOTE_LLM_URL and settings.REMOTE_LLM_API_KEY)
