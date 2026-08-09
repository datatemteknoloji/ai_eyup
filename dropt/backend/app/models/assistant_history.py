from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Column, DateTime, Text, func
from sqlmodel import Field, SQLModel


class AssistantChatMessage(SQLModel, table=True):
    """Per-user assistant transcript; purged after ~24h."""

    __tablename__ = "assistant_chat_messages"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    role: str = Field(default="user", max_length=16)  # user | assistant
    content: str = Field(sa_column=Column(Text, nullable=False))
    operation_id: str = Field(default="", max_length=64, index=True)
    result_json: str = Field(default="", sa_column=Column(Text, nullable=False))
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    )
