@echo off
if not exist .venv (
    echo Creating virtual environment...
    python -m venv .venv
    echo Installing dependencies...
    .venv\Scripts\pip install -r requirements.txt
)
echo Starting IDM MVP...
.venv\Scripts\python -m ui.tui
pause
