"""Shared pool state management for app_pool.py.

This module is imported (not re-executed) by Panel, so its globals
persist across session reloads.  All mutable pool state lives here
to avoid the "name not defined" errors that occur when Panel clears
the served script's namespace on session teardown.
"""

import atexit
import logging
import multiprocessing
import threading

import aiomultiprocess as amp

logger = logging.getLogger(__name__)

_pool: amp.Pool | None = None
_manager: multiprocessing.managers.SyncManager | None = None
_pool_lock = threading.Lock()
_active_sessions = 0


def get_pool() -> amp.Pool:
    """Return the global shared pool, creating it on first call."""
    global _pool
    with _pool_lock:
        if _pool is None:
            _pool = amp.Pool(processes=4)
            logger.info("Pool created with 4 processes")
        return _pool


def shutdown_pool() -> None:
    """Terminate the pool and kill all its subprocesses."""
    global _pool
    with _pool_lock:
        if _pool is None:
            return
        pool = _pool
        _pool = None
    logger.info("Terminating pool and killing subprocesses")
    try:
        pool.terminate()
    except Exception as e:
        logger.warning(f"pool.terminate() error: {e}")
    logger.info("Pool shut down")


def increment_sessions() -> None:
    """Track a new session using the pool."""
    global _active_sessions
    with _pool_lock:
        _active_sessions += 1
        logger.info(f"Active pool sessions: {_active_sessions}")


def decrement_sessions() -> None:
    """Untrack a session. Shuts down the pool when count reaches 0."""
    global _active_sessions
    with _pool_lock:
        _active_sessions = max(0, _active_sessions - 1)
        count = _active_sessions
    logger.info(f"Active pool sessions: {count}")
    if count == 0:
        shutdown_pool()


def get_manager() -> multiprocessing.managers.SyncManager:
    """Return a singleton Manager for cross-process proxy objects."""
    global _manager
    if _manager is None:
        _manager = multiprocessing.Manager()
    return _manager


atexit.register(shutdown_pool)
