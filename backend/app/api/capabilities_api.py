"""GET /api/v1/capabilities — frontend menü/sekme ve istemci keşfi."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.auth import get_current_user
from app.models.user import User
from app.services.capabilities import capabilities_payload

router = APIRouter()


@router.get("")
def list_capabilities(_user: User = Depends(get_current_user)):
    return capabilities_payload()
