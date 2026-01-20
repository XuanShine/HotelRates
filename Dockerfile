# Dockerfile for py4web server
FROM python:3.14-slim

# Set working directory
WORKDIR /app

# Set Python to run unbuffered
ENV PYTHONUNBUFFERED=1

# 1. Install uv by copying it from the official image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# 2. Set the working directory
WORKDIR /app

# 3. Enable bytecode compilation (faster startup)
ENV UV_COMPILE_BYTECODE=1

# 4. Copy configuration files first (to leverage Docker layer caching)
COPY pyproject.toml .

# 5. Install dependencies
# We use --no-install-project because we haven't copied the source code yet
RUN uv sync --no-install-project

# 6. Copy the rest of the application code
COPY . .

# 7. Final sync to install the project itself
RUN uv sync

# 8. Place the virtual environment in the PATH
ENV PATH="/app/.venv/bin:$PATH"
ENV TZ="Europe/Paris"

# Expose port
# EXPOSE 8000

# Run py4web server
# CMD ["py4web", "run", "apps", "--host", "0.0.0.0", "--port", "8000"]
CMD ["python", "run.py"]