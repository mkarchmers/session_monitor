# Code Map

## Files

### `session_client.py`
HTTP client for Panel apps to report session status to the monitoring server.

- **`SessionClient`** — One-per-session tracker. Registers with the server, sends periodic heartbeats in a daemon thread, and checks for kill requests.
  - `get_tracker(app_name, user_id?, server_url?, heartbeat_interval?)` — Class method factory. Returns the existing instance for the current Panel session or creates a new one.
  - `task(name)` — Context manager that sets status to `running`/`idle` around a block.
  - `stop()` — Stops heartbeat, deregisters session, closes HTTP client.
  - Offline mode: if the server is unreachable at init, all tracking is silently skipped.

### `server.py`
FastAPI REST server. Thin layer over `session_db`.

| Method | Path | Handler |
|--------|------|---------|
| `POST` | `/sessions` | `create_session` — register new session |
| `DELETE` | `/sessions/stale` | `cleanup_stale_sessions` — remove sessions with no heartbeat for N minutes |
| `DELETE` | `/sessions/{id}` | `delete_session` |
| `POST` | `/sessions/{id}/heartbeat` | `heartbeat` — update timestamp, return `kill_requested` |
| `PUT` | `/sessions/{id}/status` | `update_status` — set status + current task |
| `POST` | `/sessions/{id}/kill` | `kill_session` — flag session for termination |
| `GET` | `/sessions` | `list_sessions` — all sessions with computed fields |

### `session_db.py`
SQLite persistence layer. Thread-safe via thread-local connections (`threading.local`).

- `init_db()` — Creates `sessions` table and indexes on import.
- `create_session(app_name, user_id?) -> session_id`
- `delete_session(session_id) -> bool`
- `update_heartbeat(session_id) -> Optional[bool]` — Returns `kill_requested`.
- `update_status(session_id, status, current_task?) -> bool`
- `request_kill(session_id) -> bool`
- `get_all_sessions() -> list[dict]` — Computes `duration_seconds`, `is_stale` (no heartbeat for 2+ min).
- `cleanup_stale_sessions(older_than_minutes) -> int`

### `models.py`
Pydantic request/response schemas: `SessionCreate`, `SessionStatus`, `HeartbeatResponse`, `Session`, `SessionList`, `SessionCreated`, `CleanupResponse`.

### `monitor.py`
Panel dashboard app. Shows all sessions in a Perspective table, auto-refreshes every 10s, supports row selection and kill.

- `load_sessions_data()` — Fetches sessions from the API, triggers stale cleanup, returns a DataFrame.
- `request_kill(session_id)` — Sends kill request to the API.
- **`MonitorDashboard`** — `pn.viewable.Viewer` with Perspective widget, kill button, and refresh controls.

### `app.py`
Example Panel app that uses `SessionClient`.

- **`TaskRunner`** — UI with task name input, duration slider, and run button. Runs a `time.sleep` task in a background thread wrapped in `tracker.task()`.
- **`App`** — Bootstraps the tracker and serves the template.

## Data Flow

```
Panel App (SessionClient)
  ├─ POST /sessions           → register
  ├─ POST /sessions/{id}/heartbeat  → every 30s (configurable), returns kill_requested
  ├─ PUT  /sessions/{id}/status     → on task start/end
  └─ DELETE /sessions/{id}          → on session destroy

FastAPI Server (server.py)
  └─ SQLite (session_db.py)

Monitor Dashboard (monitor.py)
  ├─ GET /sessions            → poll every 10s
  ├─ DELETE /sessions/stale   → cleanup on each poll
  └─ POST /sessions/{id}/kill → user-initiated kill
```

## Key Constants

| Constant | Location | Default |
|----------|----------|---------|
| Server URL | `session_client.py` | `http://localhost:8000` |
| Heartbeat interval | `SessionClient.__init__` | 30s |
| HTTP timeout | `SessionClient.__init__` | 10s |
| Stale threshold | `session_db.get_all_sessions` | 2 min |
| Auto-cleanup threshold | `monitor.py` → `load_sessions_data` | 10 min |
| Dashboard refresh | `monitor.py` → `MonitorDashboard.__panel__` | 10s |
