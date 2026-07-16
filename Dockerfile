# Use the official Python slim image for a smaller footprint
FROM python:3.10-slim

# Set working directory inside the container
WORKDIR /app

# Prevent Python from writing pyc files to disc
ENV PYTHONDONTWRITEBYTECODE 1
# Prevent Python from buffering stdout and stderr
ENV PYTHONUNBUFFERED 1

# Install system dependencies (required for some Python packages like numpy/pandas)
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy only requirements first to leverage Docker cache
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

# Expose port for FastAPI
EXPOSE 8000

# We don't define CMD here because docker-compose will override it with --reload
# Default command fallback just in case
CMD ["uvicorn", "api.server:app", "--host", "0.0.0.0", "--port", "8000"]
