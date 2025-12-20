# IDM 2.0 (Intelligent Download Manager)

A powerful, terminal-based download manager written in Python, featuring a modern TUI (Terminal User Interface) built with Textual and Rich.

## Features

- **Modern TUI**: Interactive dashboard with real-time statistics.
- **Visual Progress**: Rich, color-coded progress bars and status indicators.
- **Management**: Pause, Resume, and Queue downloads.
- **Detailed Info**: View real-time speed, ETA, and file details.
- **Chunk Progress**: Visualize individual download parts with dedicated progress bars.
- **Cross-Platform**: Runs on Windows, Linux, and macOS (Python required).

## Installation

1.  **Clone the repository** (or extract the source).
2.  **Create a virtual environment**:
    ```bash
    python -m venv .venv
    ```
3.  **Activate the environment**:
    - Windows: `.venv\Scripts\activate`
    - Unix: `source .venv/bin/activate`
4.  **Install dependencies**:
    ```bash
    pip install -r requirements.txt
    ```

## Usage

### Running the Application
You can start the application using the provided batch file (Windows) or directly via Python:

**Linux (Debian/Ubuntu)**:
1.  Make the scripts executable:
    ```bash
    chmod +x install.sh run.sh
    ```
2.  Run the installer (creates venv and installs deps):
    ```bash
    ./install.sh
    ```
3.  Start the app:
    ```bash
    ./run.sh
    ```

**Windows**:
```batch
run.bat
```

**Manual Python command**:
```bash
python -m ui.tui
```

### Keyboard Shortcuts

| Key | Action |
| :--- | :--- |
| `a` | Add URL (Focus input) |
| `p` | Pause Selected Download |
| `r` | Resume Selected Download |
| `d` | Stop/Delete Selected |
| `q` | Quit Application |

## Development

- **UI Framework**: [Textual](https://textual.textualize.io/)
- **Engine**: Asyncio-based custom download manager.

## Browser Extension Integration

IDM 2.0 comes with a browser extension to capture downloads automatically.

### Installation (Chrome/Edge/Brave)

1.  Open your browser and navigate to `chrome://extensions`.
2.  Enable **Developer mode** (toggle in top right).
3.  Click **Load unpacked**.
4.  Select the `extension` folder in this repository.
5.  The IDM 2.0 extension should now be active.

**Note**: Ensure the IDM 2.0 application is running for the extension to capture downloads.

## License

MIT
