"""Donanım sağlayıcı sabitleri (tek kaynak)."""
from __future__ import annotations

CATEGORY = "hardware"

KIND_DELL = "dell_ome"
KIND_HPE = "hpe_oneview"
KIND_DEMO = "hw_demo"
REAL_KINDS = (KIND_DELL, KIND_HPE)

CAP_HW = "hw"
CAP_DELL = "hw.dell"
CAP_HPE = "hw.hpe"
CAP_DEMO = "hw_demo"

# HPE kartı modları
MODE_OVGD = "ovgd"            # OneView Global Dashboard (tek uç; appliance'lar keşfedilir)
MODE_ONEVIEW = "oneview"      # bir veya birkaç OneView appliance (paylaşılan hesap)

SUPPORT_VERIFIED = "verified"        # Doğrulanmış
SUPPORT_COMPATIBLE = "compatible"    # Uyumlu (en iyi çaba)
SUPPORT_UNSUPPORTED = "unsupported"  # Desteklenmeyen
SUPPORT_LABEL_TR = {SUPPORT_VERIFIED: "Doğrulanmış", SUPPORT_COMPATIBLE: "Uyumlu", SUPPORT_UNSUPPORTED: "Desteklenmeyen"}

# Normalize sağlık / şiddet
HEALTH_OK, HEALTH_WARNING, HEALTH_CRITICAL, HEALTH_UNKNOWN = "ok", "warning", "critical", "unknown"
SEV_CRITICAL, SEV_WARNING, SEV_INFO, SEV_UNKNOWN = "critical", "warning", "info", "unknown"

# Varsayılan senkron aralıkları (sn) — kartta ayarlanabilir (meta_json.intervals)
DEFAULT_ALARM_SEC = 900          # 15 dk
DEFAULT_INVENTORY_SEC = 86400    # günlük
DEFAULT_WARRANTY_SEC = 86400     # günlük
MIN_ALARM_SEC = 300

# Kimlik doğrulama koruması
TEST_COOLDOWN_SEC = 30
AUTH_FAILED = "auth_failed"
