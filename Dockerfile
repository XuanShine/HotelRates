# Multi-stage build for HotelRates app
FROM python:3.14-slim

# Set working directory
WORKDIR /app

# Set Python to run unbuffered
ENV PYTHONUNBUFFERED=1

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install uv
RUN pip install uv

# Copy pyproject.toml and install dependencies
COPY pyproject.toml .

# Install Python dependencies
RUN uv pip install -r pyproject.toml

# Copy the entire project
COPY . .

# Expose port if needed (adjust as per your app)
# EXPOSE 6001

# Run the application
CMD ["python", "run.py"]