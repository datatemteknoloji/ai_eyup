"""Geriye dönük uyumluluk: kayıt defteri artık ``services.integrations.registry`` içindedir.

Aynı nesneler (sözlükler dahil) yeniden dışa aktarılır; Veeam ve donanım sağlayıcıları tek kayıt defterini paylaşır.
"""
from app.services.integrations.registry import (  # noqa: F401
    _FACTORIES,
    _KIND_CAPS,
    capabilities_for_instance,
    get_provider_factory,
    list_provider_kinds,
    parse_meta,
    register_provider,
)
