"""
Panel Session Monitor Dashboard

Displays all active sessions across Panel applications.
Run with: panel serve monitor.py --port 5000
"""

import httpx
import pandas as pd
import panel as pn

pn.extension("perspective")

SERVER_URL = "http://localhost:8000"


def load_sessions_data() -> pd.DataFrame:
    """Load and format session data from the API server."""
    try:
        with httpx.Client(timeout=10.0) as client:
            # Get sessions
            response = client.get(f"{SERVER_URL}/sessions")
            response.raise_for_status()
            sessions = response.json()["sessions"]

            # Cleanup stale sessions
            client.delete(f"{SERVER_URL}/sessions/stale", params={"older_than_minutes": 10})
    except Exception:
        sessions = []

    if not sessions:
        return pd.DataFrame({
            "Session ID": [],
            "App": [],
            "Started": [],
            "Duration (s)": [],
            "Status": [],
            "Task": [],
        })

    formatted = []
    for s in sessions:
        # Parse ISO datetime string
        start_time = s["start_time"]
        if "T" in start_time:
            time_part = start_time.split("T")[1][:8]
        else:
            time_part = start_time

        formatted.append({
            "Session ID": s["session_id"],
            "App": s["app_name"],
            "Started": time_part,
            "Duration (s)": s["duration_seconds"],
            "Status": s["status"],
            "Task": s["current_task"] or "",
        })

    return pd.DataFrame(formatted)


def request_kill(session_id: str) -> None:
    """Request a session to be killed via the API."""
    try:
        with httpx.Client(timeout=10.0) as client:
            client.post(f"{SERVER_URL}/sessions/{session_id}/kill")
    except Exception:
        pass


class MonitorDashboard(pn.viewable.Viewer):
    """Main monitoring dashboard component."""

    def __init__(self):
        super().__init__()
        self._perspective = None
        self._selected_session_id = None
        self._kill_btn = None
        self._status_text = None

    def _create_perspective(self) -> pn.pane.Perspective:
        """Create the sessions Perspective pane."""
        data = load_sessions_data()

        perspective = pn.pane.Perspective(
            data,
            height=400,
            sizing_mode="stretch_width",
            selectable=True,
            plugin="datagrid",
        )
        perspective.on_click(self._handle_click)
        return perspective

    def _handle_click(self, event) -> None:
        """Handle click events on the Perspective pane."""
        session_id = None
        if hasattr(event, "row") and event.row:
            row_data = event.row
            if isinstance(row_data, dict) and "Session ID" in row_data:
                session_id = row_data["Session ID"]
        elif hasattr(event, "config") and event.config:
            if isinstance(event.config, dict) and "Session ID" in event.config:
                session_id = event.config["Session ID"]

        if session_id:
            self._selected_session_id = session_id
            if self._kill_btn:
                self._kill_btn.disabled = False
            if self._status_text:
                self._status_text.object = f"Selected: {self._selected_session_id[:8]}..."

    def _kill_selected(self, event) -> None:
        """Kill the selected session."""
        if self._selected_session_id:
            request_kill(self._selected_session_id)
            if self._status_text:
                self._status_text.object = f"Kill requested for {self._selected_session_id[:8]}..."
            self._selected_session_id = None
            if self._kill_btn:
                self._kill_btn.disabled = True
            self._refresh()

    def _refresh(self) -> None:
        """Refresh the data without rebuilding the Perspective pane."""
        if self._perspective:
            self._perspective.object = load_sessions_data()
        # Reset status if no session is selected
        if self._selected_session_id is None and self._status_text:
            self._status_text.object = "*Click a row to select a session*"

    def __panel__(self):
        self._perspective = self._create_perspective()

        # Auto-refresh every 10 seconds
        refresh_callback = pn.state.add_periodic_callback(
            self._refresh,
            period=10000,
        )

        # Clean up callback when session disconnects
        def cleanup(session_context):
            refresh_callback.stop()

        pn.state.on_session_destroyed(cleanup)

        refresh_btn = pn.widgets.Button(
            name="Refresh Now",
            button_type="primary",
            width=100,
        )
        refresh_btn.on_click(lambda e: self._refresh())

        self._kill_btn = pn.widgets.Button(
            name="Kill Selected",
            button_type="danger",
            width=100,
            disabled=True,
        )
        self._kill_btn.on_click(self._kill_selected)

        self._status_text = pn.pane.Markdown("*Click a row to select a session*")

        header = pn.Row(
            pn.pane.Markdown("## Active Sessions"),
            pn.Spacer(),
            self._status_text,
            self._kill_btn,
            refresh_btn,
            sizing_mode="stretch_width",
        )

        return pn.Column(
            header,
            self._perspective,
            sizing_mode="stretch_width",
        )


# Create and serve the dashboard
dashboard = MonitorDashboard()
template = pn.template.BootstrapTemplate(
    title="Session Monitor",
    main=[dashboard],
)
template.servable()
