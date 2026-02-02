# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A monitoring system for Panel (HoloViz) applications that tracks active sessions across multiple apps. Sessions report status via heartbeats to a shared SQLite database, and a dashboard displays all sessions in real-time.

## Commands

```bash
# Activate virtual environment
source venv/bin/activate

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
│ SessionTracker  │     │ SessionTracker  │
└────────┬────────┘     └────────┬────────┘
         │                       │
         └───────────┬───────────┘
                     ▼
        ┌────────────────────────┐
        │   SQLite (sessions.db) │
        └────────────┬───────────┘
                     ▼
        ┌────────────────────────┐
        │   monitor.py Dashboard │
        └────────────────────────┘
```

### Key Components

- **session_db.py**: Database layer. Thread-safe SQLite operations with thread-local connections. Auto-initializes schema on import. Includes `request_kill()` and `check_kill_requested()` for session termination. Note: Connections are intentionally not explicitly closed—they persist per thread and are cleaned up on process exit. This is acceptable because Panel server threads are pooled/reused, heartbeat daemon threads die with the process, and SQLite connections are lightweight.

- **session_tracker.py**: Drop-in tracker for Panel apps. Spawns a daemon thread for heartbeats (every 30s). Use `with tracker.task("name"):` to mark running tasks. Checks for kill requests during heartbeat and gracefully terminates sessions.

- **monitor.py**: Dashboard app using Tabulator widget. Auto-refreshes every 10 seconds. Sessions become "stale" (red) after 2 minutes without heartbeat, auto-deleted after 10 minutes. Includes Kill button for each session.

### Session States

| Status | Color | Meaning |
|--------|-------|---------|
| idle | green | Session active, no task running |
| running | yellow | Task in progress |
| stale | red | No heartbeat for 2+ minutes |

### Integration Pattern

```python
from session_tracker import SessionTracker

# Get or create a tracker for the current Panel session
tracker = SessionTracker.get_tracker(app_name="my_app")

with tracker.task("Generating Report"):
    run_expensive_operation()
```

The `get_tracker` class method ensures one tracker per Panel session - calling it multiple times with the same session returns the existing instance.

### Kill Session Feature

Sessions can be terminated from the monitoring dashboard by clicking the "Kill" button. The kill flow:

1. Dashboard sets `kill_requested` flag in database via `session_db.request_kill(session_id)`
2. SessionTracker checks the flag during each heartbeat (every 30s)
3. If kill requested, tracker closes WebSocket with code 1001 ("Session terminated by administrator")
4. Client receives disconnect notification (configured via `pn.extension(disconnect_notification="...")`)
5. After 500ms delay, session is destroyed server-side

**Note**: Kill takes effect on the next heartbeat cycle (up to 30 seconds). For faster response, reduce `heartbeat_interval` in SessionTracker.
