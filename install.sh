#!/bin/bash

# Define the virtual environment directory
VENV_DIR=".venv"

echo "Checking for Python 3..."
if ! command -v python3 &> /dev/null; then
    echo "Python 3 could not be found. Please install it (e.g., sudo apt install python3)."
    exit 1
fi

# Check for venv module
if ! python3 -c "import venv" &> /dev/null; then
    echo "Python 3 venv module is missing. Installing..."
    sudo apt-get update
    sudo apt-get install -y python3-venv python3-pip
fi

# Create virtual environment if it doesn't exist
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
else
    echo "Virtual environment already exists."
fi

# Activate virtual environment
source "$VENV_DIR/bin/activate"

# Install requirements
if [ -f "requirements.txt" ]; then
    echo "Installing requirements..."
    pip install -r requirements.txt
else
    echo "requirements.txt not found!"
    exit 1
fi

echo "Installation complete! You can now run the app using ./run.sh"
