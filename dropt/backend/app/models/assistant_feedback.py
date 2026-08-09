from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Column, DateTime, Text, func
from sqlmodel import Field, SQLModel


class AssistantFeedback(SQLModel, table=True):
    __tablename__ = "assistant_feedback"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    message: str = Field(sa_column=Column(Text, nullable=False))
    suggested_operation_id: str = Field(default="", max_length=64)
    correct_operation_id: str = Field(default="", max_length=64, index=True)
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
