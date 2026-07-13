"""Envanter yazma işlemleri yalnızca Entegrasyonlar modülünden yapılabilir."""
from fastapi import HTTPException, Request

INVENTORY_HEADER = "X-Inventory-Source"
INVENTORY_VALUE = "integrations"


def require_integrations_inventory(request: Request) -> None:
    if request.headers.get(INVENTORY_HEADER) != INVENTORY_VALUE:
        raise HTTPException(
            status_code=403,
            detail="Envanter kaydı yalnızca Entegrasyonlar modülünden yapılabilir.",
        )
