# Use Miniconda as the base image to support Conda installations
FROM continuumio/miniconda3:latest

# Set the working directory inside the container
WORKDIR /app

# Install system dependencies if needed (build-essential for any compilations)
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    wget \
    && rm -rf /var/lib/apt/lists/*

# Copy environment files first to leverage Docker layer caching
COPY environment.yml requirements.txt ./

# Create the conda environment from environment.yml
RUN conda env create -f environment.yml && \
    conda clean --all -f -y

# Make RUN commands use the new environment
SHELL ["conda", "run", "-n", "automated_trading_system_env", "/bin/bash", "-c"]

# Copy the rest of the application code
COPY . /app

# Install additional dependencies that might be missing
RUN conda run -n automated_trading_system_env pip install --no-cache-dir \
    beautifulsoup4 \
    lxml \
    html5lib \
    && conda run -n automated_trading_system_env pip install --no-cache-dir -r requirements.txt

# Verify the environment is working and all packages are installed
RUN conda run -n automated_trading_system_env python -c "import sys; print(f'Python version: {sys.version}'); print('Checking critical packages...'); import fastapi; print('✅ FastAPI imported successfully'); import aiohttp; print('✅ aiohttp imported successfully'); import pandas; print('✅ pandas imported successfully'); import requests; print('✅ requests imported successfully'); from bs4 import BeautifulSoup; print('✅ BeautifulSoup imported successfully'); print('✅ All critical packages imported successfully')"

# Verify the environment is working
RUN conda info --envs && \
    conda run -n automated_trading_system_env python --version && \
    conda run -n automated_trading_system_env pip list

# Expose the port
EXPOSE $PORT

# Set environment variables for better logging in Docker
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONIOENCODING=utf-8

# Create a wrapper script that ensures proper logging to stdout/stderr
RUN echo '#!/bin/bash' > /usr/local/bin/heroku-start.sh && \
    echo 'set -e' >> /usr/local/bin/heroku-start.sh && \
    echo 'echo "🚀 HEROKU WRAPPER: Starting Automated Trading System Service" >&1' >> /usr/local/bin/heroku-start.sh && \
    echo 'echo "🚀 HEROKU WRAPPER: Starting Automated Trading System Service" >&2' >> /usr/local/bin/heroku-start.sh && \
    echo 'exec conda run --no-capture-output -n automated_trading_system_env python -u start-heroku.py' >> /usr/local/bin/heroku-start.sh && \
    chmod +x /usr/local/bin/heroku-start.sh

# Command to run the application with proper logging wrapper
CMD ["/usr/local/bin/heroku-start.sh"]
