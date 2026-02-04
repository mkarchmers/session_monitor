# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A monitoring system for Panel (HoloViz) applications that tracks active sessions across multiple apps. Sessions report status via REST API to a FastAPI server, and a dashboard displays all sessions in real-time.

## Commands

```bash
# Activate virtual environment
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Start the API server (required first)
uvicorn server:app --port 8000

# Start the monitoring dashboard
panel serve monitor.py --port 5000

# Start the example task runner app
panel serve app.py --port 5001

# Run multiple apps simultaneously (use different ports)
panel serve app.py --port 5001 &
panel serve app.py --port 5002 &
```

## Architecture

```
┌─────────────────┐     ┌─────────────────┐
│   Panel App     │     │   Panel App     │
│                 │     │                 │
│ SessionClient   │     │ SessionClient   │
└────────┬────────┘     └────────┬────────┘
         │  HTTP              │  HTTP
         └───────────┬────────┘
                     ▼
        ┌────────────────────────┐
        │   FastAPI Server       │
        │   (server.py)          │
        │   - REST endpoints     │
        │   - SQLite storage     │
        └────────────┬───────────┘
                     │  HTTP
        ┌────────────┴───────────┐
        │   monitor.py Dashboard │
        │   (uses REST API)      │
        └────────────────────────┘
```

### Key Components

- **models.py**: Pydantic models for API request/response schemas.

- **server.py**: FastAPI server with REST endpoints. Manages all session state in SQLite. Thread-safe with thread-local connections.

  | Method | Path | Description |
  |--------|------|-------------|
  | POST | `/sessions` | Register new session, returns session_id |
  | DELETE | `/sessions/{session_id}` | Remove session |
  | POST | `/sessions/{session_id}/heartbeat` | Update heartbeat, returns kill_requested |
  | PUT | `/sessions/{session_id}/status` | Update status and task |
  | POST | `/sessions/{session_id}/kill` | Request session termination |
  | GET | `/sessions` | List all sessions with computed fields |
  | DELETE | `/sessions/stale` | Cleanup stale sessions |

- **session_client.py**: HTTP-based tracker for Panel apps. Same API as the old SessionTracker. Spawns a daemon thread for heartbeats (every 30s). Use `with tracker.task("name"):` to mark running tasks. Checks for kill requests via heartbeat response.

- **monitor.py**: Dashboard app using Perspective widget. Auto-refreshes every 10 seconds. Sessions become "stale" (red) after 2 minutes without heartbeat, auto-deleted after 10 minutes. Includes Kill button for each session.

### Session States

| Status | Color | Meaning |
|--------|-------|---------|
| idle | green | Session active, no task running |
| running | yellow | Task in progress |
| stale | red | No heartbeat for 2+ minutes |

### Integration Pattern

```python
from session_client import SessionClient

# Get or create a tracker for the current Panel session
tracker = SessionClient.get_tracker(app_name="my_app")

with tracker.task("Generating Report"):
    run_expensive_operation()
```

The `get_tracker` class method ensures one tracker per Panel session - calling it multiple times with the same session returns the existing instance.

Optional parameters:
- `user_id`: Optional user identifier
- `server_url`: API server URL (default: `http://localhost:8000`)

### Kill Session Feature

Sessions can be terminated from the monitoring dashboard by clicking the "Kill" button. The kill flow:

1. Dashboard sends `POST /sessions/{session_id}/kill` to the API server
2. Server sets `kill_requested` flag in database
3. SessionClient checks the flag via heartbeat response (every 30s)
4. If kill requested, tracker closes WebSocket with code 1001 ("Session terminated by administrator")
5. Client receives disconnect notification (configured via `pn.extension(disconnect_notification="...")`)
6. After 500ms delay, session is destroyed server-side

**Note**: Kill takes effect on the next heartbeat cycle (up to 30 seconds). For faster response, reduce `heartbeat_interval` in SessionClient.

## Dependencies

- `panel>=1.8.0` - Panel framework
- `fastapi>=0.109.0` - REST API framework
- `uvicorn>=0.27.0` - ASGI server
- `httpx>=0.26.0` - HTTP client
- `aiosqlite>=0.19.0` - Async SQLite (kept for compatibility)
