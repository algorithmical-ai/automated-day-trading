#!/bin/bash
# Wrapper script to run start-heroku.py with the conda environment's Python

# Get the conda environment path
CONDA_ENV_PATH="${CONDA_PREFIX:-/opt/anaconda3/envs/automated_trading_system_env}"
CONDA_PYTHON="${CONDA_ENV_PATH}/bin/python"

# Check if conda Python exists
if [ ! -f "$CONDA_PYTHON" ]; then
    echo "❌ Conda Python not found at: $CONDA_PYTHON"
    echo "⚠️ Please activate the conda environment first:"
    echo "   conda activate automated_trading_system_env"
    exit 1
fi

# Run the script with conda Python
echo "🚀 Using conda Python: $CONDA_PYTHON"
exec "$CONDA_PYTHON" start-heroku.py "$@"

