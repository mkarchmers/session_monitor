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

### `pool_manager.py`
Shared pool state management, extracted into its own module so globals survive Panel session reloads (Panel re-executes the served script per session but does not re-execute imported modules).

- **Global shared `aiomultiprocess.Pool`** — Created lazily via `get_pool()`, shared across all sessions. Terminated automatically when the last session is killed.
- **`shutdown_pool()`** — Calls `pool.terminate()` to kill all subprocesses. Also registered via `atexit`.
- **Ref counter** — `increment_sessions()` / `decrement_sessions()` track active sessions; when count reaches 0, `shutdown_pool()` is called.
- **`get_manager()`** — Singleton `multiprocessing.Manager` for creating picklable cross-process proxy objects (e.g. `Manager().Event()`).

### `app_pool.py`
Demo Panel app showing shared-pool per-session cancellation (Option 2). Pool state lives in `pool_manager.py`.

- **`PoolApp`** — Each session creates a per-session `Manager().Event()`, registers `stop_event.set` + `decrement_sessions` as `on_kill` callback, and submits 2 async workers to the shared pool via `pool.apply()`. Killing all sessions triggers pool shutdown. The `kill_handler` captures `decrement_sessions` via default arg to survive namespace cleanup.
- Uses `amp.set_start_method("fork")` on macOS/Linux to avoid pickle/module-resolution issues; Windows uses default `"spawn"`.

### `worker.py`
Async subprocess worker used by `app_pool.py`.

- `_sub_task(sub_id, tag, sid, log)` — One of 5 concurrent coroutines per cycle. Sleeps 1 second then returns a result string.
- `worker(task_id, stop_event, session_id?)` — `async def` loop. Each iteration runs 5 `_sub_task` coroutines concurrently via `asyncio.gather` (~1 s per cycle). Checks `stop_event.is_set()` (via `asyncio.to_thread`) **between** cycles — in-flight coroutines always run to completion. Log lines include the first 8 chars of the session ID.

  Termination paths:
  - **`stop_event.set()`**: detected at the next cycle boundary; current cycle's coroutines finish cleanly.
  - **`pool.terminate()` / SIGTERM**: subprocess killed immediately; all coroutines vanish with no cleanup.

### `test_stop_event.py`
Standalone end-to-end test for the graceful stop path.

- Starts a `multiprocessing.Manager` and `aiomultiprocess.Pool`, submits 2 workers, sets `stop_event` after 2.5 s (mid-cycle), and verifies both workers exit cleanly after finishing their current cycle.

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
| Pool size | `pool_manager.py` → `get_pool` | 4 processes |
