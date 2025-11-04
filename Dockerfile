# Use the official lightweight Python image
FROM python:3.11-slim

# --- NEW SECTION ---
# Install WeasyPrint's system dependencies
# This is the fix for the 'libgobject-2.0-0' error
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libgobject-2.0-0 \
    libharfbuzz0b \
    libfontconfig1 \
    libffi-dev && \
    rm -rf /var/lib/apt/lists/*
# --- END NEW SECTION ---

# Set the working directory in the container
WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

# Set the command to run the application using Gunicorn
CMD exec gunicorn --bind :$PORT --workers 1 --threads 8 --timeout 0 app:app