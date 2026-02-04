#!/usr/bin/env bash
set -euo pipefail

# Create virtual environment in .venv and install requirements
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt

echo "Virtualenv created at .venv. Activate with: source .venv/bin/activate"
