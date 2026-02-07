# Global Pool Recommendation

## Problem

If all sessions share a single global `Pool`, then registering `pool.terminate` as an `on_kill` callback from **any single session** will kill the workers for **every session**. Session A gets killed from the dashboard → pool is terminated → Sessions B and C lose their in-flight work too.

## Recommendations

### 1. Per-session pools (simplest)

Don't share a pool across sessions if kill is enabled. The `on_kill` callback design assumes each session owns its cleanup targets. A shared pool violates that assumption. With per-session pools, `on_kill(pool.terminate)` works correctly as written in `pool_plan.md`.

### 2. Shared pool with per-session cancellation

If you must share a pool, don't register `pool.terminate` as the kill callback. Use a cancellation pattern per-session instead:

```python
pool = get_global_pool()  # shared

tracker = SessionClient.get_tracker(app_name="my_app")
cancel_event = asyncio.Event()

tracker.on_kill(cancel_event.set)  # just signal, don't terminate

with tracker.task("Processing"):
    futures = [pool.apply(func, (item,)) for item in items]
    results = []
    for f in asyncio.as_completed(futures):
        if cancel_event.is_set():
            # cancel remaining futures, but leave pool alive
            for pending in futures:
                pending.cancel()
            break
        results.append(await f)
```

This way a kill only cancels **that session's work**, not the entire pool.

### 3. Shared pool with reference counting

If sessions create the pool lazily and you want it to shut down when the last session exits:

```python
_pool = None
_pool_refcount = 0
_pool_lock = threading.Lock()

def acquire_pool():
    global _pool, _pool_refcount
    with _pool_lock:
        if _pool is None:
            _pool = Pool()
        _pool_refcount += 1
        return _pool

def release_pool():
    global _pool, _pool_refcount
    with _pool_lock:
        _pool_refcount -= 1
        if _pool_refcount == 0:
            _pool.terminate()
            _pool = None
```

Then the `on_kill` callback calls `release_pool()` instead of `pool.terminate()`.

## Summary

| Strategy | `on_kill` callback | Safe for shared pool? |
|---|---|---|
| Per-session pool | `pool.terminate` | N/A (not shared) |
| Shared + cancellation | `cancel_event.set` | Yes |
| Shared + refcount | `release_pool` | Yes |
