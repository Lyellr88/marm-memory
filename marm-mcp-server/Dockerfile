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
RUN pip install --no-cache-dir --upgrade wheel>=0.46.2 && \
    pip install --no-cache-dir --user -r requirements.txt

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

# Expose MCP server port
EXPOSE 8001

# Health check to verify server is running
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8001/health || exit 1

# MCP Registry Labels for Docker Hub discovery
LABEL org.opencontainers.image.title="MARM Universal MCP Server"
LABEL org.opencontainers.image.description="Production-ready Universal MCP Server with advanced AI memory capabilities, semantic search, and professional-grade architecture"
LABEL org.opencontainers.image.version="2.9.1"
LABEL org.opencontainers.image.authors="Ryan Lyell - MARM Systems"
LABEL org.opencontainers.image.url="https://marmsystems.com"
LABEL org.opencontainers.image.source="https://github.com/Lyellr88/MARM-Systems"
LABEL org.opencontainers.image.licenses="MIT"
LABEL mcp.server="true"
LABEL mcp.name="marm-mcp-server"
LABEL mcp.tools="9"
LABEL io.modelcontextprotocol.server.name="io.github.Lyellr88/marm-mcp-server"

# Set environment variables
ENV PYTHONPATH=/app
ENV MARM_LOG_LEVEL=INFO
# Bind to all interfaces inside the container so host port mapping (-p) works.
# External access is controlled by the -p flag on the host side.
ENV SERVER_HOST=0.0.0.0

# Default: HTTP server mode (long-running, multi-client, API key required).
# CLI flags such as --swarm append cleanly after the image name.
ENTRYPOINT ["python", "-m", "marm_mcp_server"]
CMD []

# ============================================================================
# Build
# ============================================================================
# docker build -t lyellr88/marm-mcp-server:latest .
#
# ============================================================================
# MODE 1: HTTP Server (shared / always-on)
# ============================================================================
# Bridge networking means the host always appears as 172.x.x.x inside Docker,
# never 127.0.0.1. MARM_API_KEY is required for all HTTP deployments.
#
# Generate a key first:
#   python -m marm_mcp_server --generate-key
#
# Local (host-only):
#   docker run -d \
#     --name marm-mcp-server \
#     -p 127.0.0.1:8001:8001 \
#     -e MARM_API_KEY=your-generated-key \
#     -v ~/.marm:/home/marm/.marm \
#     lyellr88/marm-mcp-server:latest
#
# Local swarm mode:
#   docker run -d \
#     --name marm-mcp-server \
#     -p 127.0.0.1:8001:8001 \
#     -e MARM_API_KEY=your-generated-key \
#     -v ~/.marm:/home/marm/.marm \
#     lyellr88/marm-mcp-server:latest --swarm
#
# Remote:
#   docker run -d \
#     --name marm-mcp-server \
#     -p 8001:8001 \
#     -e MARM_API_KEY=your-generated-key \
#     -v ~/.marm:/home/marm/.marm \
#     lyellr88/marm-mcp-server:latest
#
# MCP client config (HTTP):
#   claude mcp add --transport http marm-memory http://localhost:8001/mcp
#   claude mcp add --transport http --header "Authorization: Bearer YOUR_KEY" marm-memory http://localhost:8001/mcp
#
# ============================================================================
# MODE 2: STDIO (local private, no port, no API key)
# ============================================================================
# The MCP client launches Docker as the server command. No port binding needed.
# Use -i (interactive stdin) — never -d (detached).
#
# Direct run:
#   docker run -i --rm \
#     -v ~/.marm:/home/marm/.marm \
#     --entrypoint python \
#     lyellr88/marm-mcp-server:latest \
#     -m marm_mcp_server.server_stdio
#
# MCP client config (STDIO / Claude Desktop, Claude Code, Cursor, VS Code):
#
#   IMPORTANT: JSON args arrays are not processed by a shell, so ~ is NOT
#   expanded. Use an absolute path for the volume mount.
#
#   macOS / Linux — replace /Users/you with your actual home directory:
#   {
#     "mcpServers": {
#       "marm-memory": {
#         "command": "docker",
#         "args": [
#           "run", "-i", "--rm",
#           "-v", "/Users/you/.marm:/home/marm/.marm",
#           "--entrypoint", "python",
#           "lyellr88/marm-mcp-server:latest",
#           "-m", "marm_mcp_server.server_stdio"
#         ]
#       }
#     }
#   }
#
#   Windows — replace C:\Users\you with your actual home directory:
#   {
#     "mcpServers": {
#       "marm-memory": {
#         "command": "docker",
#         "args": [
#           "run", "-i", "--rm",
#           "-v", "C:\\Users\\you\\.marm:/home/marm/.marm",
#           "--entrypoint", "python",
#           "lyellr88/marm-mcp-server:latest",
#           "-m", "marm_mcp_server.server_stdio"
#         ]
#       }
#     }
#   }
#
# Note: STDIO mode has no HTTP healthcheck. The image healthcheck applies to
# HTTP mode only and is irrelevant for client-launched STDIO containers.
#
# What gets packaged:
# ✅ Python 3.11 (specific version, no "install Python" needed)
# ✅ All pip dependencies (sentence-transformers, fastapi, etc.)
# ✅ System libraries (gcc, build tools for numpy/scipy)
# ✅ SQLite (built into Python, no external DB needed)
# ✅ Complete MARM MCP server (all refactored modules)
# ✅ Configuration files and defaults
# ✅ Data directory setup and permissions
# ✅ Health check endpoints for monitoring
# ✅ Proper working directory setup
# ✅ Port configuration (8001 exposed)
# ✅ Volume mounts for persistent data
# ✅ Log management and output handling
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
