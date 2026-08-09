from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.models.user import AuthSource, UserRole


class PortalUserCreate(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=6, max_length=256)
    role: UserRole = UserRole.operator
    is_active: bool = True


class PortalUserUpdate(BaseModel):
    role: Optional[UserRole] = None
    is_active: Optional[bool] = None
    password: Optional[str] = Field(default=None, min_length=6, max_length=256)


class PortalUserPublic(BaseModel):
    id: int
    username: str
    role: UserRole
    auth_source: AuthSource
    is_active: bool
    last_login_at: Optional[datetime] = None
    created_at: datetime


class PortalUserListResponse(BaseModel):
    items: list[PortalUserPublic]
    total: int
