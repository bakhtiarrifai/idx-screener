FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    jq \
    cron \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Make scripts executable
RUN chmod +x run.py setup.sh run_screener.sh

# Expose dashboard port
EXPOSE 5000

# Default command runs the screener once
CMD ["python", "run.py"]
