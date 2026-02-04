"""
Pydantic models for Session Monitoring API.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class SessionCreate(BaseModel):
    """Request model for creating a new session."""
    app_name: str
    user_id: Optional[str] = None


class SessionStatus(BaseModel):
    """Request model for updating session status."""
    status: str
    current_task: Optional[str] = None


class HeartbeatResponse(BaseModel):
    """Response model for heartbeat endpoint."""
    kill_requested: bool


class Session(BaseModel):
    """Full session model for API responses."""
    session_id: str
    app_name: str
    user_id: Optional[str]
    start_time: datetime
    last_heartbeat: datetime
    duration_seconds: int
    status: str
    current_task: Optional[str]
    is_stale: bool
    kill_requested: bool


class SessionList(BaseModel):
    """Response model for listing sessions."""
    sessions: list[Session]


class SessionCreated(BaseModel):
    """Response model for session creation."""
    session_id: str


class CleanupResponse(BaseModel):
    """Response model for cleanup endpoint."""
    deleted_count: int
