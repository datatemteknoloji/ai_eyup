"""Donanım sağlayıcılarının ortak kayıt defterine kaydı (paket içe aktarılınca)."""
from app.services.hw.constants import CAP_DELL, CAP_DEMO, CAP_HPE, CAP_HW, KIND_DELL, KIND_DEMO, KIND_HPE
from app.services.hw.dell_ome import DellOmeProvider
from app.services.hw.demo_provider import HwDemoProvider
from app.services.hw.oneview import HpeProvider
from app.services.integrations.registry import register_provider

register_provider(KIND_DELL, lambda inst: DellOmeProvider(inst), capabilities={CAP_HW, CAP_DELL})
register_provider(KIND_HPE, lambda inst: HpeProvider(inst), capabilities={CAP_HW, CAP_HPE})
register_provider(KIND_DEMO, lambda inst: HwDemoProvider(inst), capabilities={CAP_DEMO})
