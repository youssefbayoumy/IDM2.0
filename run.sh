#!/bin/bash

# Define the virtual environment directory
VENV_DIR=".venv"

# Check if the virtual environment exists
if [ ! -d "$VENV_DIR" ]; then
    echo "Virtual environment not found. Please run ./install.sh first."
    exit 1
fi

# Activate the virtual environment
source "$VENV_DIR/bin/activate"

# Run the application
python -m ui.tui
