# Pool Cleanup on Kill

## Problem

When a session is killed from the monitoring dashboard, any `aiomultiprocess.Pool` worker processes keep running. The current kill flow (`_handle_kill_request` → `stop()` → `_destroy_session`) has no way to reach into a running pool to terminate its workers.

## Proposed Solution: on_kill Callback

Add an `on_kill` callback mechanism to `SessionClient`. Users register cleanup functions that fire when a kill request is received, before session destruction.

### Usage

```python
tracker = SessionClient.get_tracker(app_name="my_app")

async with Pool() as pool:
    tracker.on_kill(pool.terminate)  # register cleanup

    with tracker.task("Processing"):
        results = await pool.map(func, items)
```

### Implementation

- Add `_on_kill_callbacks: list[Callable]` to `SessionClient.__init__`
- Add `on_kill(callback)` method to register callbacks
- In `_handle_kill_request`, invoke all registered callbacks before calling `stop()` / `_destroy_session`

### Considerations

- **Multiple callbacks** — support registering more than one (e.g., terminate pool + cancel pending futures)
- **Thread safety** — the kill comes from the heartbeat thread, so `pool.terminate()` needs to be safe to call from another thread (it is, since it just sends signals)
- **Timing** — kill still has up to 30s delay (heartbeat interval). Reduce `heartbeat_interval` for faster response if needed.
