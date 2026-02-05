"""
FastAPI server for Session Monitoring.

Run with: uvicorn server:app --port 8000
"""

from fastapi import FastAPI, HTTPException

import session_db
from models import (
    CleanupResponse,
    HeartbeatResponse,
    Session,
    SessionCreate,
    SessionCreated,
    SessionList,
    SessionStatus,
)

app = FastAPI(title="Session Monitor API")


@app.post("/sessions", response_model=SessionCreated)
def create_session(session: SessionCreate) -> SessionCreated:
    """Register a new session."""
    session_id = session_db.create_session(session.app_name, session.user_id)
    return SessionCreated(session_id=session_id)


@app.delete("/sessions/stale", response_model=CleanupResponse)
def cleanup_stale_sessions(older_than_minutes: int = 10) -> CleanupResponse:
    """Remove sessions without heartbeat for the specified time."""
    deleted_count = session_db.cleanup_stale_sessions(older_than_minutes)
    return CleanupResponse(deleted_count=deleted_count)


@app.delete("/sessions/{session_id}")
def delete_session(session_id: str) -> dict:
    """Remove a session."""
    if not session_db.delete_session(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    return {"status": "deleted"}


@app.post("/sessions/{session_id}/heartbeat", response_model=HeartbeatResponse)
def heartbeat(session_id: str) -> HeartbeatResponse:
    """Update heartbeat and return kill status."""
    kill_requested = session_db.update_heartbeat(session_id)
    if kill_requested is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return HeartbeatResponse(kill_requested=kill_requested)


@app.put("/sessions/{session_id}/status")
def update_status(session_id: str, status_update: SessionStatus) -> dict:
    """Update session status and task."""
    if not session_db.update_status(session_id, status_update.status, status_update.current_task):
        raise HTTPException(status_code=404, detail="Session not found")
    return {"status": "updated"}


@app.post("/sessions/{session_id}/kill")
def kill_session(session_id: str) -> dict:
    """Request session termination."""
    if not session_db.request_kill(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    return {"status": "kill_requested"}


@app.get("/sessions", response_model=SessionList)
def list_sessions() -> SessionList:
    """List all sessions with computed fields."""
    sessions = [Session(**s) for s in session_db.get_all_sessions()]
    return SessionList(sessions=sessions)
