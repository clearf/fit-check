"""Sync audit log model."""
from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class SyncLog(SQLModel, table=True):
    """Records each sync attempt for audit and debugging."""

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(default=1)
    started_at: datetime = Field(default_factory=datetime.utcnow)
    finished_at: Optional[datetime] = None
    status: str = "running"  # "running", "success", "partial", "error"
    activities_synced: int = 0
    error_message: Optional[str] = None
