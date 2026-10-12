# Multi-stage build for HotelRates app
FROM python:3.14-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    UV_SYSTEM_PYTHON=1 \
    UV_LINK_MODE=copy \
    TZ=Europe/Paris

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install the project (pyproject.toml is not a requirements file)
COPY pyproject.toml README.md ./
COPY src ./src
RUN uv pip install --system .

COPY . .

CMD ["python", "run.py"]
