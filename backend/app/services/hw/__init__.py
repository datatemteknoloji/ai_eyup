"""Opsiyonel donanım yönetimi sağlayıcı çerçevesi (Dell OME + HPE OneView/OVGD).

Salt-okunur; resmi API dokümanlarına göre (docs/plans/hw-api-sources.md). Entegrasyon yoksa hiçbir etkisi olmaz.
"""

from app.services.hw import providers  # noqa: E402,F401  (sağlayıcıları kayıt defterine kaydeder)
