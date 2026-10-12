"""GET /api/v1/methods — yöntem kaydı (Dilim T): rozet/(i) içeriği ve 'Nasıl hesaplıyoruz?' sayfası."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.auth import get_current_user
from app.models.user import User
from app.services import method_registry

router = APIRouter()


@router.get("")
def list_methods(_user: User = Depends(get_current_user)):
    return method_registry.catalog()
