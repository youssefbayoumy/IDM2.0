from textual.app import App, ComposeResult
from textual.containers import Container, Vertical, Horizontal
from textual.widgets import Header, Footer, DataTable, Input, Static, Button, Label
from textual.screen import ModalScreen
from textual.binding import Binding
from engine.manager import DownloadManager
from engine.models import DownloadStatus
import asyncio

class ErrorScreen(ModalScreen):
    CSS = """
    ErrorScreen {
        align: center middle;
    }
    #dialog {
        grid-size: 2;
        grid-gutter: 1 2;
        grid-rows: 1fr 3;
        padding: 0 1;
        width: 60;
        height: 11;
        border: thick $background 80%;
        background: $surface;
    }
    #message {
        column-span: 2;
        height: 1fr;
        content-align: center middle;
    }
    """

    def __init__(self, item):
        super().__init__()
        self.item = item

    def compose(self) -> ComposeResult:
        yield Container(
            Label(f"Download Failed!\n\n{self.item.error_message}", id="message"),
            Button("Retry", variant="success", id="retry"),
            Button("Cancel", variant="error", id="cancel"),
            id="dialog"
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "retry":
            self.dismiss(True)
        else:
            self.dismiss(False)

class DownloadApp(App):
    CSS = """
    DataTable {
        height: 1fr;
    }
    Input {
        dock: bottom;
    }
    .details-box {
        dock: bottom;
        height: 4;
        border: solid white;
        padding: 0 1;
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
        yield Header()
        yield DataTable()
        yield Static(id="details", classes="details-box")
        yield Input(placeholder="Paste URL to download and press Enter", id="url_input")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.cursor_type = "row"
        table.add_column("ID", key="ID")
        table.add_column("Filename", key="Filename")
        table.add_column("Status", key="Status")
        table.add_column("Progress", key="Progress")
        table.add_column("Size", key="Size")
        table.add_column("Speed", key="Speed")
        self.set_interval(0.5, self.update_table)
        self.query_one(Input).focus()

    async def action_resume(self) -> None:
        table = self.query_one(DataTable)
        if table.cursor_row is not None:
            row_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
            await self.manager.start_download(row_key)

    async def action_pause(self) -> None:
        table = self.query_one(DataTable)
        if table.cursor_row is not None:
            row_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
            self.manager.pause_download(row_key)

    def on_data_table_row_selected(self, message: DataTable.RowSelected) -> None:
        row_key = message.row_key.value
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
            details = f"URL: {item.url}\nFile: {path}\n"
            if item.status == DownloadStatus.ERROR:
                details += f"[bold red]Error: {item.error_message}[/]"
            else:
                details += f"Status: {item.status.value}"
            
            self.query_one("#details", Static).update(details)

    async def on_input_submitted(self, message: Input.Submitted) -> None:
        url = message.value
        if url:
            self.manager.add_download(url)
            # Auto-start for now
            dl_id = list(self.manager.downloads.keys())[-1]
            await self.manager.start_download(dl_id)
            self.query_one(Input).value = ""

    def format_size(self, size_bytes: int) -> str:
        if size_bytes == 0:
            return "0 B"
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size_bytes < 1024.0:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.1f} PB"

    def update_table(self) -> None:
        table = self.query_one(DataTable)
        downloads = self.manager.get_downloads()
        
        # If no row is highlighted/selected, looking at the last one or something?
        # Textual keeps selection.
        
        for item in downloads:
            # Check if row exists using isValidRow or similar not available?
            # get_row raises RowDoesNotExist
            try:
                table.get_row(item.id)
                row_exists = True
            except:
                row_exists = False

            progress_str = f"{item.progress:.1f}%"
            
            # Format sizes
            current_fmt = self.format_size(item.downloaded_size)
            total_fmt = self.format_size(item.total_size)
            size_str = f"{current_fmt} / {total_fmt}"
            
            speed_val = item.speed / 1024 / 1024 # MB/s
            speed_str = f"{speed_val:.1f} MB/s"

            status_display = item.status.value
            if item.status == DownloadStatus.ERROR:
                msg = item.error_message if item.error_message else "Unknown Error"
                if len(msg) > 20:
                    msg = msg[:17] + "..."
                status_display = f"Error: {msg}"
            
            # Truncate filename/url for display safely
            name_display = item.filename or item.url
            if len(name_display) > 30:
                name_display = name_display[:27] + "..."

            if row_exists:
                table.update_cell(item.id, "Status", status_display)
                table.update_cell(item.id, "Progress", progress_str)
                table.update_cell(item.id, "Size", size_str)
                table.update_cell(item.id, "Speed", speed_str)
                table.update_cell(item.id, "Filename", name_display)
            else:
                table.add_row(
                    item.id[:8], 
                    name_display, 
                    status_display, 
                    progress_str, 
                    size_str, 
                    speed_str, 
                    key=item.id
                )
        
        # Update details if selection exists
        if table.cursor_row is not None and len(table.rows) > 0:
             # This is a bit tricky since we need the row key not index.
             # But on_highlighted handles it mostly.
             pass

if __name__ == "__main__":
    app = DownloadApp()
    app.run()
