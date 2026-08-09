from typing import Optional

from sqlmodel import Field, SQLModel


class CentrifyCredential(SQLModel, table=True):
    """Hostname leave/join için Centrify AD servis hesabı (domain başına)."""

    __tablename__ = "centrify_credentials"

    id: Optional[int] = Field(default=None, primary_key=True)
    label: str = Field(default="", max_length=128)
    username: str = Field(max_length=255, index=True)
    domain: str = Field(max_length=255, index=True)
    password_enc: str = Field(default="", max_length=4096)
    enabled: bool = Field(default=True)
