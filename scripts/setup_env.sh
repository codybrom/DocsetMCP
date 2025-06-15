#!/bin/bash
set -e

echo "Setting up Python virtual environment..."

# Remove existing venv if it exists
if [ -d ".venv" ]; then
    echo "Removing existing .venv directory..."
    rm -rf .venv
fi

# Create new virtual environment
echo "Creating new virtual environment..."
python3 -m venv .venv

# Activate virtual environment
echo "Activating virtual environment..."
source .venv/bin/activate

# Upgrade pip
echo "Upgrading pip..."
pip install --upgrade pip

# Install production dependencies
echo "Installing production dependencies..."
pip install -r requirements.txt

# Install development dependencies
echo "Installing development dependencies..."
pip install -r requirements-dev.txt

# Install pre-commit hooks
echo "Installing pre-commit hooks..."
pre-commit install

# Install cspell globally for spell checking
echo "Installing cspell for spell checking..."
if command -v npm &> /dev/null; then
    npm install -g cspell@latest
    echo "cspell installed successfully"
else
    echo "Warning: npm not found. Install Node.js to use spell checking."
    echo "You can install cspell later with: npm install -g cspell@latest"
fi

echo "Setup complete! Virtual environment created at .venv"
echo "To activate it, run: source .venv/bin/activate"
