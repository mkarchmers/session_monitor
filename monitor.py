"""
Panel Session Monitor Dashboard

Displays all active sessions across Panel applications.
Run with: panel serve monitor.py --port 5000
"""

import pandas as pd
import panel as pn

import session_db

pn.extension("perspective")


def load_sessions_data() -> pd.DataFrame:
    """Load and format session data for display."""
    sessions = session_db.get_all_sessions()

    # Cleanup stale sessions older than 10 minutes
    session_db.cleanup_stale_sessions(older_than_minutes=10)

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
        formatted.append({
            "Session ID": s["session_id"],
            "App": s["app_name"],
            "Started": s["start_time"].strftime("%H:%M:%S"),
            "Duration (s)": int(s["duration"].total_seconds()),
            "Status": s["status"],
            "Task": s["current_task"] or "",
        })

    return pd.DataFrame(formatted)


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
            session_db.request_kill(self._selected_session_id)
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
