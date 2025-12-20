from textual.app import App, ComposeResult
from textual.containers import Container, Vertical, Horizontal, Grid
from textual.widgets import Header, Footer, DataTable, Input, Static, Button, Label, Digits
from textual.screen import ModalScreen
from textual.binding import Binding
from textual.reactive import reactive
import sys
import os
# Add project root to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.manager import DownloadManager
from engine.models import DownloadStatus
import asyncio
from rich.progress import BarColumn, Progress, TextColumn, SpinnerColumn, DownloadColumn, TransferSpeedColumn, TimeRemainingColumn
from rich.text import Text
from rich.style import Style
import time
import traceback
from textual.containers import VerticalScroll

class ErrorScreen(ModalScreen):
    CSS = """
    ErrorScreen {
        align: center middle;
        background: rgba(0,0,0,0.5);
    }
    #dialog {
        grid-size: 2;
        grid-gutter: 1 2;
        grid-rows: 1fr 3;
        padding: 1 2;
        width: 60;
        height: 14;
        border: thick $error 80%;
        background: $surface;
    }
    #message {
        column-span: 2;
        height: 1fr;
        content-align: center middle;
        text-style: bold;
    }
    """

    def __init__(self, item):
        super().__init__()
        self.item = item

    def compose(self) -> ComposeResult:
        yield Container(
            Label(f"[bold red]Download Failed![/]\n\n{self.item.error_message}", id="message"),
            Button("Retry", variant="success", id="retry"),
            Button("Cancel", variant="error", id="cancel"),
            id="dialog"
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "retry":
            self.dismiss(True)
        else:
            self.dismiss(False)

class DetailedDownloadScreen(ModalScreen):
    CSS = """
    DetailedDownloadScreen {
        align: center middle;
        background: rgba(0,0,0,0.8);
    }
    #detail_dialog {
        width: 80%;
        height: 80%;
        border: thick $secondary;
        background: $surface;
        layout: vertical;
        padding: 1 2;
    }
    .chunk-grid {
        layout: grid;
        grid-size: 2;
        grid-gutter: 1;
        height: 1fr;
        overflow-y: auto;
        margin-top: 1;
    }
    .chunk-box {
        height: auto;
        border: solid $accent;
        padding: 0 1;
        margin-bottom: 1;
    }
    .chunk-label {
        color: $text-muted;
    }
    .chunk-bar {
        width: 100%;
    }
    #close_btn {
        dock: bottom;
        width: 100%;
        margin-top: 1;
    }
    """
    
    def __init__(self, item, manager):
        super().__init__()
        self.item = item
        self.manager = manager
        self.update_timer = None

    def compose(self) -> ComposeResult:
        with Container(id="detail_dialog"):
            yield Label(f"[bold]Downloading:[/] {self.item.filename}", id="title")
            yield Label(f"[dim]{self.item.url}[/]")
            yield Label("", id="stats")
            # Using VerticalScroll instead of Grid for stability
            yield VerticalScroll(id="chunks")
            yield Button("Minimize (Close)", id="close_btn", variant="primary")

    def on_mount(self) -> None:
        self.update_ui()
        self.update_timer = self.set_interval(0.1, self.update_ui)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "close_btn":
            self.dismiss()

    async def update_ui(self) -> None:
        if getattr(self, "is_updating", False):
            return
        self.is_updating = True
        
        try:
            # Update Stats
            stats = f"Speed: {self.item.speed / 1024 / 1024:.2f} MB/s | Progress: {self.item.progress:.1f}% | Size: {self.format_size(self.item.downloaded_size)} / {self.format_size(self.item.total_size)}"
            self.query_one("#stats", Label).update(stats)
            
            # Update Chunks
            chunks_container = self.query_one("#chunks", VerticalScroll)
            
            # Get current chunk progress
            chunk_data = self.item.chunk_progress
            if not chunk_data:
                return

            sorted_chunks = sorted(chunk_data.items())
            
            # Log for debug
            # with open("ui_debug_run.log", "a") as f:
            #     f.write(f"Updating UI with {len(sorted_chunks)} chunks. Children: {len(chunks_container.children)}\n")

            # Check if we need to rebuild (if counts differ)
            if len(chunks_container.children) != len(sorted_chunks):
                # Rebuild
                await chunks_container.remove_children()
                
                widgets_to_mount = []
                for c_id, pct in sorted_chunks:
                    widgets_to_mount.append(
                        Container(
                            Label(f"Part {c_id+1}", classes="chunk-label"),
                            Label(self.make_bar(pct), classes="chunk-bar", id=f"bar_{c_id}"),
                            classes="chunk-box"
                        )
                    )
                await chunks_container.mount(*widgets_to_mount)
            else:
                # Update existing
                for c_id, pct in sorted_chunks:
                    try:
                        bar_label = chunks_container.query_one(f"#bar_{c_id}", Label)
                        bar_text = self.make_bar(pct)
                        bar_label.renderable = bar_text # Force update renderable directly if update() fails usually
                        bar_label.update(bar_text)
                        
                        # Debug log for first bar only to avoid spam
                        if c_id == 0 and self.item.total_size > 0:
                             with open("ui_bar_debug.log", "a") as f:
                                 f.write(f"Bar 0 text: {bar_text}\n")
                    except: 
                        pass
        except Exception as e:
            with open("ui_error.log", "a") as f:
                f.write(traceback.format_exc() + "\n")
        finally:
            self.is_updating = False

    def make_bar(self, pct):
        width = 40
        # Ensure pct is float
        if isinstance(pct, str):
            try: pct = float(pct.strip('% '))
            except: pct = 0.0
            
        filled = int(width * (pct / 100))
        # Clamp filled
        filled = max(0, min(width, filled))
        
        # Use ASCII for safety
        bar = "#" * filled + "-" * (width - filled)
        return f"[{'green' if pct >= 100 else 'cyan'}]{bar}[/] {pct:.1f}%"

    def format_size(self, size_bytes: int) -> str:
        if size_bytes == 0: return "0 B"
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size_bytes < 1024.0:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.1f} PB"

class Dashboard(Static):
    """Top dashboard showing aggregate stats."""
    
    DEFAULT_CSS = """
    Dashboard {
        layout: grid;
        grid-size: 3;
        grid-gutter: 1;
        height: 7;
        margin: 0 0 1 0;
        padding: 0 1;
    }
    .metric-card {
        background: $boost;
        border: tab $primary;
        padding: 0 1;
        height: 100%;
        content-align: center middle;
    }
    .metric-title {
        text-style: bold;
        color: $text-muted;
    }
    .metric-value {
        text-style: bold;
        color: $secondary;
    }
    """

    active_downloads = reactive(0)
    total_speed = reactive(0.0)
    completed_count = reactive(0)

    def compose(self) -> ComposeResult:
        yield Container(
            Label("Active Downloads", classes="metric-title"),
            Digits("0", id="active_val", classes="metric-value"),
            classes="metric-card"
        )
        yield Container(
            Label("Total Speed", classes="metric-title"),
            Static("0.0 MB/s", id="speed_val", classes="metric-value"),
            classes="metric-card"
        )
        yield Container(
            Label("Completed", classes="metric-title"),
            Digits("0", id="completed_val", classes="metric-value"),
            classes="metric-card"
        )

    def watch_active_downloads(self, value: int) -> None:
        try:
            self.query_one("#active_val", Digits).update(str(value))
        except: pass

    def watch_total_speed(self, value: float) -> None:
        try:
            val_mb = value / 1024 / 1024
            self.query_one("#speed_val", Static).update(f"{val_mb:.1f} MB/s")
        except: pass

    def watch_completed_count(self, value: int) -> None:
        try:
            self.query_one("#completed_val", Digits).update(str(value))
        except: pass

class DownloadApp(App):
    CSS = """
    Screen {
        layout: vertical;
        padding: 0;
    }
    DataTable {
        height: 1fr;
        border: solid $accent;
    }
    Input {
        dock: bottom;
        margin: 1 0;
        border: tall $primary;
    }
    .details-box {
        dock: bottom;
        height: 6;
        border: heavy $secondary;
        padding: 0 1;
        background: $surface-darken-1;
    }
    Header {
        dock: top;
        height: 1;
        background: $primary;
        color: white;
        text-style: bold;
    }
    """
    
    BINDINGS = [
        ("q", "quit", "Quit"),
        ("a", "add", "Add URL"),
        ("p", "pause", "Pause Selected"),
        ("r", "resume", "Resume Selected"),
        ("d", "delete", "Stop/Delete")
    ]

    def __init__(self):
        super().__init__()
        self.manager = DownloadManager("downloads")

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Dashboard()
        yield DataTable(cursor_type="cell", zebra_stripes=True)
        yield Static(id="details", classes="details-box")
        yield Input(placeholder="Paste URL to download and press Enter (Ctrl+V to paste)", id="url_input")
        yield Footer()

    async def on_mount(self) -> None:
        asyncio.create_task(self.manager.start_server())
        table = self.query_one(DataTable)
        # Add columns with Rich content support
        table.add_column("ID", key="ID", width=8)
        table.add_column("Actions", key="Actions", width=10) # New Column
        table.add_column("Filename", key="Filename", width=30)
        table.add_column("Status", key="Status", width=15)
        table.add_column("Progress", key="Progress", width=20)
        table.add_column("Size", key="Size", width=15)
        table.add_column("Speed", key="Speed", width=15)
        table.add_column("ETA", key="ETA", width=10)
        
        self.set_interval(0.2, self.update_ui)
        self.query_one(Input).focus()

    async def action_resume(self) -> None:
        table = self.query_one(DataTable)
        if table.cursor_row is not None:
            try:
                row_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
                await self.manager.start_download(row_key)
            except: pass

    async def action_pause(self) -> None:
        table = self.query_one(DataTable)
        if table.cursor_row is not None:
            try:
                row_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
                self.manager.pause_download(row_key)
            except: pass
    
    async def action_delete(self) -> None:
         # TODO: Implement delete logic in manager first
         pass

    def on_data_table_row_selected(self, message: DataTable.RowSelected) -> None:
        # Default behavior: show error log if error
        row_key = message.row_key.value
        if row_key in self.manager.downloads:
            item = self.manager.downloads[row_key]
            if item.status == DownloadStatus.ERROR:
                self.push_screen(ErrorScreen(item), self.on_error_action)

    def on_data_table_cell_selected(self, message: DataTable.CellSelected) -> None:
        row_key = message.cell_key.row_key.value
        if message.cell_key.column_key.value == "Actions":
            # Open details
            if row_key in self.manager.downloads:
                item = self.manager.downloads[row_key]
                self.push_screen(DetailedDownloadScreen(item, self.manager))
        else:
            # Fallback to default row behavior (e.g. error screen)
            if row_key in self.manager.downloads:
                item = self.manager.downloads[row_key]
                if item.status == DownloadStatus.ERROR:
                    self.push_screen(ErrorScreen(item), self.on_error_action)

    def on_error_action(self, retry: bool) -> None:
        if retry:
            self.call_after_refresh(self.action_resume)

    def on_data_table_row_highlighted(self, message: DataTable.RowHighlighted) -> None:
        self.update_details(message.row_key.value)

    def update_details(self, row_id: str) -> None:
        if row_id in self.manager.downloads:
            item = self.manager.downloads[row_id]
            import os
            path = os.path.join(item.save_path, item.filename) if item.filename else "Unknown"
            
            # Rich styling for details
            status_color = "green" if item.status == DownloadStatus.COMPLETED else "yellow"
            if item.status == DownloadStatus.ERROR: status_color = "red"
            
            details = (
                f"[bold]URL:[/] {item.url}\n"
                f"[bold]File:[/] {path}\n"
                f"[bold]Status:[/] [{status_color}]{item.status.value}[/]\n"
            )
            
            if item.status == DownloadStatus.ERROR:
                details += f"[bold red]Error Details:[/] {item.error_message}"
            
            self.query_one("#details", Static).update(details)

    async def on_input_submitted(self, message: Input.Submitted) -> None:
        url = message.value
        if url:
             # Basic URL validation could go here
            self.manager.add_download(url)
            # Auto-start for now
            dl_id = list(self.manager.downloads.keys())[-1]
            await self.manager.start_download(dl_id)
            self.query_one(Input).value = ""

    def format_size(self, size_bytes: int) -> str:
        if size_bytes == 0: return "0 B"
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size_bytes < 1024.0:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.1f} PB"

    def update_ui(self) -> None:
        table = self.query_one(DataTable)
        dashboard = self.query_one(Dashboard)
        downloads = self.manager.get_downloads()
        
        # Calculate Dashboard stats
        active = sum(1 for d in downloads if d.status in [DownloadStatus.DOWNLOADING, DownloadStatus.QUEUED])
        total_speed = sum(d.speed for d in downloads if d.status == DownloadStatus.DOWNLOADING)
        completed = sum(1 for d in downloads if d.status == DownloadStatus.COMPLETED)
        
        dashboard.active_downloads = active
        dashboard.total_speed = total_speed
        dashboard.completed_count = completed

        # Update Table
        for item in downloads:
            try:
                table.get_row(item.id)
                row_exists = True
            except:
                row_exists = False

            # --- Construct Rich Renderables ---
            
            # 1. Status with Icon and Color
            status_map = {
                DownloadStatus.DOWNLOADING: ("⬇️ Downloading", "blue"),
                DownloadStatus.COMPLETED: ("✅ Completed", "green"),
                DownloadStatus.ERROR: ("❌ Error", "red"),
                DownloadStatus.PAUSED: ("⏸️ Paused", "yellow"),
                DownloadStatus.QUEUED: ("⏳ Queued", "dim"),
                DownloadStatus.STOPPED: ("⏹️ Stopped", "red"),
                DownloadStatus.RETRYING: ("🔄 Retrying", "orange1"),
            }
            s_text, s_style = status_map.get(item.status, (item.status.value, "white"))
            status_render = Text(s_text, style=s_style)

            # 2. Progress Bar
            # We use a trick: create a Progress object for just this item and render it.
            # Or simpler: explicit BarColumn render.
            # A rich BarColumn needs a task, but we can simulate it with a simple Progress call or just use custom Text for now 
            # if we don't want to instantiate a heavy Progress object per row.
            # Actually, Textual's standard trick is using `Bar` from proper library or just styled text.
            # Let's use `BarColumn` from `rich.progress`.
            # To render just the bar, we need `BarColumn().render(...)`. 
            # But `render` takes a task. 
            # Easier approach: Use `f"{item.progress:.1f}%"` with a backing visual bar if possible, 
            # or just a styled text for now to ensure stability, or use `ProgressBar` widget from Textual if valid. 
            # But we are in a DataTable.
            
            # Let's simple Text implementation for now, but with color.
            pct = item.progress
            if pct >= 100:
                bar_color = "green"
                bar_char = "━"
            else:
                bar_color = "blue"
                bar_char = "━"
            
            # Create a manual text bar
            width = 15
            filled = int(width * (pct / 100))
            bar_str = bar_char * filled + " " * (width - filled)
            progress_render = Text(f"{bar_str} {pct:.1f}%", style=bar_color)


            # 3. Speed & Size
            speed_val = item.speed / 1024 / 1024 # MB/s
            speed_render = Text(f"{speed_val:.1f} MB/s", style="bold cyan")
            
            size_done = self.format_size(item.downloaded_size)
            size_total = self.format_size(item.total_size)
            size_render = Text(f"{size_done}/{size_total}", style="magenta")

            # 4. ETA
            # Simple calc
            eta_str = "--:--"
            if item.status == DownloadStatus.DOWNLOADING and item.speed > 0:
                remaining = item.total_size - item.downloaded_size
                if remaining > 0:
                    secs = remaining / item.speed
                    import datetime
                    eta_str = str(datetime.timedelta(seconds=int(secs)))
            
            eta_render = Text(eta_str, style="yellow")

            # 5. Filename
            fname = item.filename or item.url
            if len(fname) > 25:
                fname = fname[:10] + "..." + fname[-12:]
            name_render = Text(fname, style="white")

            # Actions renderable
            details_btn = Text("[Details]", style="bold cyan underline")

            if row_exists:
                table.update_cell(item.id, "Status", status_render)
                table.update_cell(item.id, "Progress", progress_render)
                table.update_cell(item.id, "Size", size_render)
                table.update_cell(item.id, "Speed", speed_render)
                table.update_cell(item.id, "ETA", eta_render)
                table.update_cell(item.id, "Filename", name_render)
                table.update_cell(item.id, "Actions", details_btn) # Update Actions
            else:
                table.add_row(
                    item.id[:8], 
                    details_btn, # Actions
                    name_render, 
                    status_render, 
                    progress_render, 
                    size_render, 
                    speed_render,
                    eta_render,
                    key=item.id
                ) 

        
        # Highlight update
        if table.cursor_row is not None and table.row_count > 0:
             # Just ensures details are fresh if selection hasn't changed but data has
             try:
                 row_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
                 self.update_details(row_key)
             except: pass

if __name__ == "__main__":
    app = DownloadApp()
    app.run()
