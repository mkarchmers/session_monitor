# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Code Map

See `codemap.md` for a detailed map of all files, functions, data flow, and key constants.

## Project Overview

A monitoring system for Panel (HoloViz) applications that tracks active sessions across multiple apps. Sessions report status via REST API to a FastAPI server, and a dashboard displays all sessions in real-time.

## Commands

```bash
# Activate virtual environment
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Start the API server (optional - apps work without it in offline mode)
uvicorn server:app --port 8000

# Start the monitoring dashboard
panel serve monitor.py --port 5000

# Start the example task runner app
panel serve app.py --port 5001

# Start the pool demo app (shared aiomultiprocess pool)
panel serve app_pool.py --port 5001

# Run multiple apps simultaneously (use different ports)
panel serve app.py --port 5001 &
panel serve app_pool.py --port 5002 &
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
  | POST | `/apps/{app_name}/kill-all` | Kill all sessions for an app |
  | GET | `/sessions` | List all sessions with computed fields |
  | DELETE | `/sessions/stale` | Cleanup stale sessions |

- **session_client.py**: HTTP-based tracker for Panel apps. Spawns a daemon thread for heartbeats (every 30s). Use `with tracker.task("name"):` to mark running tasks. Checks for kill requests via heartbeat response. **Offline mode**: If the server is unavailable, the client runs in offline mode - tasks execute normally but are not tracked.

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

**Offline mode**: If the server is unavailable, the client automatically runs in offline mode. Tasks execute normally but session status is not reported. A warning is logged at startup.

### on_kill Callbacks

Register cleanup callbacks that run when a session is killed (from the dashboard) **or** when it ends naturally (page reload, tab close, atexit):

```python
tracker = SessionClient.get_tracker(app_name="my_app")
stop_event = manager.Event()

tracker.on_kill(stop_event.set)
```

Callbacks are invoked exactly once (guard prevents double-execution across kill + stop paths).

### Shared Pool Pattern (Option 2)

When multiple sessions share a global `aiomultiprocess.Pool`, use per-session cancellation via `on_kill` instead of terminating the pool:

```python
from pool_manager import get_pool, get_manager, decrement_sessions
from session_client import SessionClient
from worker import worker

pool = get_pool()           # global shared pool (from pool_manager)
manager = get_manager()     # global shared Manager (from pool_manager)
tracker = SessionClient.get_tracker(app_name="my_app")

stop_event = manager.Event()        # per-session, picklable
tracker.on_kill(stop_event.set)     # signal, don't terminate pool

with tracker.task("Processing"):
    await asyncio.gather(
        pool.apply(worker, (1, stop_event)),
        pool.apply(worker, (2, stop_event)),
    )
```

**Important:** Pool state lives in `pool_manager.py` (a regular imported module), not in the served script. This is necessary because Panel re-executes the served script per session and clears its namespace on teardown — functions defined in the served script lose access to their module globals when old sessions clean up.

See `app_pool.py` for the full working demo and `worker.py` for the async worker implementation.

### Kill Session Feature

Sessions can be terminated from the monitoring dashboard by clicking the "Kill" button. The kill flow:

1. Dashboard sends `POST /sessions/{session_id}/kill` to the API server
2. Server sets `kill_requested` flag in database
3. SessionClient checks the flag via heartbeat response (every 30s)
4. Registered `on_kill` callbacks fire (e.g. set stop events to cancel subprocess work)
5. Tracker closes WebSocket with code 1001 ("Session terminated by administrator")
6. Client receives disconnect notification (configured via `pn.extension(disconnect_notification="...")`)
7. After 500ms delay, session is destroyed server-side

**Note**: Kill takes effect on the next heartbeat cycle (up to 30 seconds). For faster response, reduce `heartbeat_interval` in SessionClient.

### Kill All + Pool Shutdown

When using a shared `aiomultiprocess.Pool`, individual session kills only cancel that session's work. To kill **all** sessions and terminate the pool's subprocesses:

1. Dashboard "Kill All (App)" button sends `POST /apps/{app_name}/kill-all`
2. Server sets `kill_requested` on all sessions for that app
3. Each session's `on_kill` callbacks fire (set stop events + decrement ref counter)
4. When the last session decrements the counter to 0, `shutdown_pool()` is called
5. `pool.terminate()` sends SIGTERM to all pool worker processes
6. Pool is reset to `None` (will be recreated lazily if new sessions start)

The pool is also terminated via `atexit` when the Panel server process exits.

## Dependencies

- `panel>=1.8.0` - Panel framework
- `fastapi>=0.109.0` - REST API framework
- `uvicorn>=0.27.0` - ASGI server
- `httpx>=0.26.0` - HTTP client
- `aiosqlite>=0.19.0` - Async SQLite (kept for compatibility)
- `aiomultiprocess>=0.9.0` - Async multiprocessing pool
