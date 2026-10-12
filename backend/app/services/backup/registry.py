"""Sağlayıcı kayıt defteri.

Kayıtlı ama yapılandırılmamış kind'ın etkisi yoktur. Capability üretimi yalnız
``integration_instances.enabled`` ve sağlıklı last_status üzerinden gider.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Callable, Dict, Optional, Set, Type

from app.models.integration_instance import IntegrationInstance

logger = logging.getLogger(__name__)

# kind → factory(instance) -> BackupProvider
_FACTORIES: Dict[str, Callable[[IntegrationInstance], Any]] = {}

# kind → statik capability seti (instance yokken UI keşfi; aktif etki yok)
_KIND_CAPS: Dict[str, Set[str]] = {}


def register_provider(
    kind: str,
    factory: Callable[[IntegrationInstance], Any],
    *,
    capabilities: Optional[Set[str]] = None,
) -> None:
    _FACTORIES[kind] = factory
    if capabilities is not None:
        _KIND_CAPS[kind] = set(capabilities)


def list_provider_kinds() -> Dict[str, Set[str]]:
    return {k: set(v) for k, v in _KIND_CAPS.items()}


def get_provider_factory(kind: str) -> Optional[Callable[[IntegrationInstance], Any]]:
    return _FACTORIES.get(kind)


def capabilities_for_instance(row: IntegrationInstance) -> Set[str]:
    """Enabled instance için capability kümesi (sağlayıcıdan veya kind varsayılanı)."""
    if not row.enabled:
        return set()
    factory = _FACTORIES.get(row.kind)
    if factory is None:
        return set(_KIND_CAPS.get(row.kind) or set())
    try:
        provider = factory(row)
        caps = set(provider.capabilities())
        if caps:
            return caps
    except Exception as e:  # noqa: BLE001
        logger.debug("provider capabilities %s: %s", row.kind, e)
    return set(_KIND_CAPS.get(row.kind) or set())


def parse_meta(row: IntegrationInstance) -> Dict[str, Any]:
    if not row.meta_json:
        return {}
    try:
        return json.loads(row.meta_json)
    except Exception:  # noqa: BLE001
        return {}
