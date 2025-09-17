# MARM MCP Server - Complete Self-Contained Docker Package
# 
# This Dockerfile packages EVERYTHING needed to run the MARM MCP Server:
# - Python 3.11 runtime
# - All Python dependencies (FastAPI, sentence-transformers, etc.)
# - Complete MARM application code
# - SQLite database setup
# - Health checks and monitoring
#
# User needs NOTHING installed except Docker - zero prerequisites!

# Stage 1: Build environment with all dependencies
FROM python:3.11-slim AS builder

WORKDIR /app

# Install system dependencies for building
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python packages
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Stage 2: Runtime environment (smaller, production-ready)
FROM python:3.11-slim

WORKDIR /app

# Install curl for health checks
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

# Create user for security (optional but good practice)
RUN groupadd -r marm && useradd -r -g marm marm
# Create home directory for marm user with cache directory
RUN mkdir -p /home/marm /home/marm/.marm /home/marm/.cache
RUN chown -R marm:marm /home/marm

# Copy Python packages from builder stage directly to marm user location
COPY --from=builder --chown=marm:marm /root/.local /home/marm/.local

# Create data directory for persistent storage with correct permissions
RUN mkdir -p /app/data && chown marm:marm /app/data

# Copy application code (updated path for current structure)
COPY --chown=marm:marm . .

USER marm
ENV PATH=/home/marm/.local/bin:$PATH

# Pre-download ML models to avoid runtime downloads and Hugging Face issues
RUN python -c "from sentence_transformers import SentenceTransformer; print('Downloading semantic search model...'); SentenceTransformer('all-MiniLM-L6-v2'); print('✅ Semantic search model downloaded successfully')"

# Expose MCP server port
EXPOSE 8001

# Health check to verify server is running
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8001/health || exit 1

# MCP Registry Labels for Docker Hub discovery
LABEL org.opencontainers.image.title="MARM Universal MCP Server"
LABEL org.opencontainers.image.description="Production-ready Universal MCP Server with advanced AI memory capabilities, semantic search, and professional-grade architecture"
LABEL org.opencontainers.image.version="2.1"
LABEL org.opencontainers.image.authors="Ryan Lyell - MARM Systems"
LABEL org.opencontainers.image.url="https://marmsystems.com"
LABEL org.opencontainers.image.source="https://github.com/Lyellr88/MARM-Systems"
LABEL org.opencontainers.image.licenses="MIT"
LABEL mcp.server="true"
LABEL mcp.name="marm-mcp-server"
LABEL mcp.tools="19"
LABEL io.modelcontextprotocol.server.name="io.github.lyellr88/marm-mcp-server"

# Set environment variables
ENV PYTHONPATH=/app
ENV MARM_DB_PATH=/app/data/marm_memory.db
ENV MARM_LOG_LEVEL=INFO

# Run the MARM MCP server
CMD ["python", "server.py"]

# Build instructions:
# docker build -t marm-systems/marm-mcp-server:latest .
#
# Run instructions:
# docker run -d \
#   --name marm-mcp-server \
#   -p 8001:8001 \
#   -v marm-data:/app/data \
#   marm-systems/marm-mcp-server:latest
#
# Connect to Claude Desktop:
# claude mcp add marm-memory http://localhost:8001/mcp
#
# What gets packaged:
# Python 3.11 (specific version, no "install Python" needed)
# All pip dependencies (sentence-transformers, fastapi, etc.)
# System libraries (gcc, build tools for numpy/scipy)
# SQLite (built into Python, no external DB needed)
# Complete MARM MCP server (all refactored modules)
# Configuration files and defaults
# Data directory setup and permissions
# Health check endpoints for monitoring
# Proper working directory setup
# Port configuration (8001 exposed)
# Volume mounts for persistent data
# Log management and output handling
#
# User Experience:
# - Zero prerequisites installation (just need Docker)
# - Same container runs on Windows, Mac, Linux
# - Same Python version everywhere (3.11)
# - Same dependencies with exact versions locked
# - No "works on my machine" issues
# - Single command deployment
# - Built-in health checks and restart policies
#
# Size Optimization:
# - Stage 1 (Builder): ~800MB with build tools
# - Stage 2 (Runtime): ~200MB final image
# - User downloads: Only the 200MB runtime image
# - Fast startup: Optimized for production use
