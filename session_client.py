"""
Session client for Panel applications using REST API.

Usage:
    from session_client import SessionClient

    tracker = SessionClient.get_tracker(app_name="my_app")

    # Mark a long-running task
    with tracker.task("Generating Report"):
        run_expensive_operation()
"""

import atexit
import logging
import threading
from contextlib import contextmanager
from typing import Optional

import httpx
import panel as pn

logger = logging.getLogger(__name__)

DEFAULT_SERVER_URL = "http://localhost:8000"


class SessionClient:
    """Tracks a Panel session's status via REST API."""

    _instances: dict[str, "SessionClient"] = {}
    _lock = threading.Lock()

    @classmethod
    def get_tracker(
        cls,
        app_name: str,
        user_id: Optional[str] = None,
        server_url: str = DEFAULT_SERVER_URL,
    ) -> "SessionClient":
        """Get or create a tracker for the current Panel session.

        Args:
            app_name: Name of the application
            user_id: Optional user identifier
            server_url: URL of the session monitoring server

        Returns:
            SessionClient instance for the current session
        """
        panel_session_id = cls._get_current_session_id()
        with cls._lock:
            if panel_session_id not in cls._instances:
                cls._instances[panel_session_id] = cls(
                    app_name, user_id, server_url, panel_session_id
                )
            return cls._instances[panel_session_id]

    @staticmethod
    def _get_current_session_id() -> str:
        """Get the current Panel session ID."""
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
        server_url: str = DEFAULT_SERVER_URL,
        panel_session_id: Optional[str] = None,
        heartbeat_interval: int = 30,
    ):
        """Initialize the session client.

        Args:
            app_name: Name of the application
            user_id: Optional user identifier
            server_url: URL of the session monitoring server
            panel_session_id: Panel session ID (used internally)
            heartbeat_interval: Seconds between heartbeat updates
        """
        self.app_name = app_name
        self.user_id = user_id
        self.server_url = server_url.rstrip("/")
        self.heartbeat_interval = heartbeat_interval
        self._stop_heartbeat = threading.Event()
        self._heartbeat_thread: Optional[threading.Thread] = None
        self._panel_session_id = panel_session_id or self._get_current_session_id()

        # Capture document reference for use in background thread
        self._curdoc = pn.state.curdoc

        # HTTP client
        self._client = httpx.Client(timeout=10.0)

        # Register session with server
        self.session_id = self._register_session()

        # Start heartbeat thread
        self._start_heartbeat()

        # Register cleanup on session end
        self._register_cleanup()

    def _register_session(self) -> str:
        """Register this session with the server."""
        try:
            response = self._client.post(
                f"{self.server_url}/sessions",
                json={"app_name": self.app_name, "user_id": self.user_id},
            )
            response.raise_for_status()
            return response.json()["session_id"]
        except Exception as e:
            logger.error(f"Failed to register session: {e}")
            raise

    def _start_heartbeat(self) -> None:
        """Start the background heartbeat thread."""

        def heartbeat_loop():
            while not self._stop_heartbeat.wait(self.heartbeat_interval):
                try:
                    response = self._client.post(
                        f"{self.server_url}/sessions/{self.session_id}/heartbeat"
                    )
                    response.raise_for_status()
                    data = response.json()
                    if data.get("kill_requested"):
                        self._handle_kill_request()
                        return
                except Exception:
                    pass

        self._heartbeat_thread = threading.Thread(
            target=heartbeat_loop,
            daemon=True,
            name=f"heartbeat-{self.session_id[:8]}",
        )
        self._heartbeat_thread.start()

    def _handle_kill_request(self) -> None:
        """Handle a kill request by destroying the Panel session."""
        try:
            doc = self._curdoc
            if doc and doc.session_context:
                doc.add_next_tick_callback(self._destroy_session)
            else:
                self.stop()
        except Exception:
            self.stop()

    def _destroy_session(self) -> None:
        """Destroy the session (called on document thread)."""
        try:
            self.stop()

            if self._curdoc and self._curdoc.session_context:
                ctx = self._curdoc.session_context

                if hasattr(ctx, "_session"):
                    session = ctx._session

                    if hasattr(session, "_subscribed_connections"):
                        for conn in list(session._subscribed_connections):
                            try:
                                if hasattr(conn, "_socket") and conn._socket:
                                    ws = conn._socket
                                    if hasattr(ws, "close"):
                                        ws.close(1001, "Session terminated by administrator")
                            except Exception:
                                pass

                    from tornado.ioloop import IOLoop

                    IOLoop.current().call_later(0.5, lambda: self._do_destroy(session))
                    return

                self._curdoc.clear()
        except Exception:
            pass

    def _do_destroy(self, session) -> None:
        """Actually destroy the session after delay."""
        try:
            if hasattr(session, "destroy"):
                session.destroy()
        except Exception:
            pass

    def _register_cleanup(self) -> None:
        """Register cleanup handlers for when session ends."""

        def cleanup():
            self.stop()

        atexit.register(cleanup)

        try:
            if pn.state.curdoc:
                pn.state.curdoc.on_session_destroyed(lambda ctx: cleanup())
        except Exception:
            pass

    def stop(self) -> None:
        """Stop tracking and remove session from server."""
        self._stop_heartbeat.set()
        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            self._heartbeat_thread.join(timeout=1)
        try:
            self._client.delete(f"{self.server_url}/sessions/{self.session_id}")
        except Exception:
            pass
        try:
            self._client.close()
        except Exception:
            pass
        with SessionClient._lock:
            SessionClient._instances.pop(self._panel_session_id, None)

    def set_status(self, status: str, task: Optional[str] = None) -> None:
        """Update the session status.

        Args:
            status: Status string ('idle', 'running', etc.)
            task: Optional task description
        """
        try:
            self._client.put(
                f"{self.server_url}/sessions/{self.session_id}/status",
                json={"status": status, "current_task": task},
            )
        except Exception as e:
            logger.error(f"Failed to update status: {e}")

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
