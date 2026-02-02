"""
Session tracker for Panel applications.

Usage:
    from session_tracker import SessionTracker

    tracker = SessionTracker(app_name="my_app")

    # Mark a long-running task
    with tracker.task("Generating Report"):
        run_expensive_operation()
"""

import atexit
import logging
import threading
from contextlib import contextmanager
from typing import Optional

import panel as pn

import session_db

logger = logging.getLogger(__name__)


class SessionTracker:
    """Tracks a Panel session's status for monitoring purposes."""

    _instances: dict[str, 'SessionTracker'] = {}
    _lock = threading.Lock()

    @classmethod
    def get_tracker(cls, app_name: str, user_id: Optional[str] = None) -> 'SessionTracker':
        """Get or create a tracker for the current Panel session.

        Args:
            app_name: Name of the application
            user_id: Optional user identifier

        Returns:
            SessionTracker instance for the current session
        """
        session_id = cls._get_current_session_id()
        with cls._lock:
            if session_id not in cls._instances:
                cls._instances[session_id] = cls(app_name, user_id)
            return cls._instances[session_id]

    @staticmethod
    def _get_current_session_id() -> str:
        """Get the current Panel session ID (static version for class method use)."""
        try:
            if pn.state.curdoc and pn.state.curdoc.session_context:
                return pn.state.curdoc.session_context.id
        except Exception:
            pass
        import uuid
        return str(uuid.uuid4())

    def __init__(
        self,
        app_name: str,
        user_id: Optional[str] = None,
        heartbeat_interval: int = 30,
    ):
        """Initialize the session tracker.

        Args:
            app_name: Name of the application (e.g., "portfolio_reports")
            user_id: Optional user identifier. If not provided, uses session ID.
            heartbeat_interval: Seconds between heartbeat updates (default: 30)
        """
        self.app_name = app_name
        self.heartbeat_interval = heartbeat_interval
        self._stop_heartbeat = threading.Event()
        self._heartbeat_thread: Optional[threading.Thread] = None

        # Get session ID from Panel state
        self.session_id = self._get_session_id()
        self.user_id = user_id

        # Capture document reference for use in background thread
        self._curdoc = pn.state.curdoc

        # Register session
        session_db.register_session(
            session_id=self.session_id,
            app_name=self.app_name,
            user_id=self.user_id,
        )

        # Start heartbeat thread
        self._start_heartbeat()

        # Register cleanup on session end
        self._register_cleanup()

    def _get_session_id(self) -> str:
        """Get the current Panel session ID."""
        return SessionTracker._get_current_session_id()

    def _start_heartbeat(self) -> None:
        """Start the background heartbeat thread."""
        def heartbeat_loop():
            while not self._stop_heartbeat.wait(self.heartbeat_interval):
                try:
                    # Check if kill was requested
                    if session_db.check_kill_requested(self.session_id):
                        self._handle_kill_request()
                        return
                    session_db.update_heartbeat(self.session_id)
                except Exception:
                    pass

        self._heartbeat_thread = threading.Thread(
            target=heartbeat_loop,
            daemon=True,
            name=f"heartbeat-{self.session_id[:8]}"
        )
        self._heartbeat_thread.start()

    def _handle_kill_request(self) -> None:
        """Handle a kill request by destroying the Panel session."""
        try:
            doc = self._curdoc
            if doc and doc.session_context:
                # Schedule destruction on the document's IO loop
                doc.add_next_tick_callback(self._destroy_session)
            else:
                # No document available, just stop the tracker
                self.stop()
        except Exception:
            self.stop()

    def _destroy_session(self) -> None:
        """Destroy the session (called on document thread)."""
        try:
            # Stop tracking first
            self.stop()

            if self._curdoc and self._curdoc.session_context:
                ctx = self._curdoc.session_context

                # Access the underlying ServerSession
                if hasattr(ctx, '_session'):
                    session = ctx._session

                    # Close WebSocket connections first to trigger disconnect notification
                    if hasattr(session, '_subscribed_connections'):
                        for conn in list(session._subscribed_connections):
                            try:
                                if hasattr(conn, '_socket') and conn._socket:
                                    ws = conn._socket
                                    if hasattr(ws, 'close'):
                                        ws.close(1001, "Session terminated by administrator")
                            except Exception:
                                pass

                    # Schedule session destruction after a short delay
                    # to allow the disconnect notification to reach the client
                    from tornado.ioloop import IOLoop
                    IOLoop.current().call_later(0.5, lambda: self._do_destroy(session))
                    return

                # Fallback: clear the document
                self._curdoc.clear()
        except Exception:
            pass

    def _do_destroy(self, session) -> None:
        """Actually destroy the session after delay."""
        try:
            if hasattr(session, 'destroy'):
                session.destroy()
        except Exception:
            pass

    def _register_cleanup(self) -> None:
        """Register cleanup handlers for when session ends."""
        def cleanup():
            self.stop()

        # Register with atexit for process shutdown
        atexit.register(cleanup)

        # Register with Panel for session end
        try:
            if pn.state.curdoc:
                pn.state.curdoc.on_session_destroyed(lambda ctx: cleanup())
        except Exception:
            pass

    def stop(self) -> None:
        """Stop tracking and remove session from database."""
        self._stop_heartbeat.set()
        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            self._heartbeat_thread.join(timeout=1)
        try:
            session_db.remove_session(self.session_id)
        except Exception:
            pass
        # Remove from registry
        with SessionTracker._lock:
            SessionTracker._instances.pop(self.session_id, None)

    def set_status(self, status: str, task: Optional[str] = None) -> None:
        """Update the session status.

        Args:
            status: Status string ('idle', 'running', etc.)
            task: Optional task description
        """
        session_db.set_status(self.session_id, status, task)

    @contextmanager
    def task(self, name: str):
        """Context manager for tracking a task.

        Usage:
            with tracker.task("Generating Q4 Report"):
                run_report()

        Args:
            name: Human-readable task name
        """
        self.set_status("running", name)
        try:
            yield
        finally:
            self.set_status("idle", None)
