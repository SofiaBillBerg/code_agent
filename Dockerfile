# Multi-stage Dockerfile for Berg Agents
# Stage 1: Build the React frontend
FROM node:20-alpine AS frontend-builder

WORKDIR /app/webapp

# Copy package files
COPY webapp/package*.json ./
RUN npm ci

# Copy source and build
COPY webapp/ ./
RUN npm run build

# Stage 2: Python runtime
FROM python:3.13-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy Python project files
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Copy application code
COPY berg_agents/ ./berg_agents/
COPY config/ ./config/
COPY examples/ ./examples/

# Copy built frontend from stage 1
COPY --from=frontend-builder /app/webapp/dist ./berg_agents/ui/webapp/dist/

# Create directories for checkpoints and data
RUN mkdir -p /data/checkpoints /data/sandboxes

# Expose port
EXPOSE 2024

# Run the server
CMD ["uv", "run", "python", "-m", "berg_agents.cli", "serve", "--web", "--host", "0.0.0.0", "--port", "2024"]
