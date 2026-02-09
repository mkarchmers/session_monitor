# Code Map

## Files

### `session_client.py`
HTTP client for Panel apps to report session status to the monitoring server.

- **`SessionClient`** — One-per-session tracker. Registers with the server, sends periodic heartbeats in a daemon thread, and checks for kill requests.
  - `get_tracker(app_name, user_id?, server_url?, heartbeat_interval?)` — Class method factory. Returns the existing instance for the current Panel session or creates a new one.
  - `task(name)` — Context manager that sets status to `running`/`idle` around a block.
  - `on_kill(callback)` — Register a no-argument callback to run when the session is killed or destroyed (page reload, tab close, atexit). Used for per-session cleanup (e.g. setting a stop event) without tearing down shared resources.
  - `stop()` — Runs on_kill callbacks (once), stops heartbeat, deregisters session, closes HTTP client.
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
| `POST` | `/apps/{app_name}/kill-all` | `kill_all_sessions` — flag all sessions of an app for termination |
| `GET` | `/sessions` | `list_sessions` — all sessions with computed fields |

### `session_db.py`
SQLite persistence layer. Thread-safe via thread-local connections (`threading.local`).

- `init_db()` — Creates `sessions` table and indexes on import.
- `create_session(app_name, user_id?) -> session_id`
- `delete_session(session_id) -> bool`
- `update_heartbeat(session_id) -> Optional[bool]` — Returns `kill_requested`.
- `update_status(session_id, status, current_task?) -> bool`
- `request_kill(session_id) -> bool`
- `request_kill_by_app(app_name) -> int` — Sets `kill_requested` on all sessions for a given app.
- `get_all_sessions() -> list[dict]` — Computes `duration_seconds`, `is_stale` (no heartbeat for 2+ min).
- `cleanup_stale_sessions(older_than_minutes) -> int`

### `models.py`
Pydantic request/response schemas: `SessionCreate`, `SessionStatus`, `HeartbeatResponse`, `Session`, `SessionList`, `SessionCreated`, `CleanupResponse`, `KillAllResponse`.

### `monitor.py`
Panel dashboard app. Shows all sessions in a Perspective table, auto-refreshes every 10s, supports row selection and kill.

- `load_sessions_data()` — Fetches sessions from the API, triggers stale cleanup, returns a DataFrame.
- `request_kill(session_id)` — Sends kill request to the API.
- `request_kill_all(app_name) -> int` — Sends kill-all request for an app, returns count.
- **`MonitorDashboard`** — `pn.viewable.Viewer` with Perspective widget, kill button, kill-all button, and refresh controls.

### `app.py`
Example Panel app that uses `SessionClient`.

- **`TaskRunner`** — UI with task name input, duration slider, and run button. Runs a `time.sleep` task in a background thread wrapped in `tracker.task()`.
- **`App`** — Bootstraps the tracker and serves the template.

### `app_pool.py`
Demo Panel app showing shared-pool per-session cancellation (Option 2).

- **Global shared `aiomultiprocess.Pool`** — Created lazily via `get_pool()`, shared across all sessions. Terminated automatically when the last session is killed.
- **`shutdown_pool()`** — Calls `pool.terminate()` + `pool.join()` to kill all subprocesses. Also registered via `atexit`.
- **Ref counter** — `_increment_sessions()` / `_decrement_sessions()` track active sessions; when count reaches 0, `shutdown_pool()` is called.
- **`get_manager()`** — Singleton `multiprocessing.Manager` for creating picklable cross-process proxy objects (e.g. `Manager().Event()`).
- **`PoolApp`** — Each session creates a per-session `Manager().Event()`, registers `stop_event.set` + `_decrement_sessions` as `on_kill` callback, and submits 2 async workers to the shared pool via `pool.apply()`. Killing all sessions triggers pool shutdown.
- Uses `amp.set_start_method("fork")` on macOS/Linux to avoid pickle/module-resolution issues; Windows uses default `"spawn"`.

### `worker.py`
Async subprocess worker used by `app_pool.py`.

- `worker(task_id, stop_event, session_id?)` — `async def` that logs every 5 seconds until `stop_event` is set. Uses `asyncio.to_thread(stop_event.wait, 5)` for non-blocking, responsive shutdown. Log lines include the first 8 chars of the session ID.

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
| Pool size | `app_pool.py` → `get_pool` | 4 processes |
