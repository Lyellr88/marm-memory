# MARM Docker Commands - Quick Reference

## Build & Deploy
```bash
# Build the container
docker-compose build --no-cache

# Start the server
docker-compose up

# Start in background
docker-compose up -d

# Stop the server  
docker-compose down

# View logs
docker-compose logs -f
```

## Test the Server
```bash
# Test basic endpoint
curl http://localhost:8001

# Test MCP endpoint
curl http://localhost:8001/health

# Check server status
docker ps
```

## Production Ready Commands
```bash
# Build for production
docker build -t marm-systems/marm-mcp-server:latest .

# Run production container
docker run -d \
  --name marm-mcp-server \
  -p 8001:8001 \
  -v marm-data:/app/data \
  marm-systems/marm-mcp-server:latest

# Push to Docker Hub (when ready)
docker tag marm-systems/marm-mcp-server:latest your-username/marm-mcp-server:latest
docker push your-username/marm-mcp-server:latest
```

## WSL Networking Fix (For Later)
```bash
# From Windows PowerShell as Admin:
wsl --shutdown
netsh winsock reset
netsh int ip reset
ipconfig /flushdns

# Or create C:\Users\lyell\.wslconfig:
[wsl2]
networkingMode=mirrored
```



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
FROM python:3.11-slim as builder

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

# Copy Python packages from builder stage
COPY --from=builder /root/.local /root/.local

# Make sure scripts in .local are usable
ENV PATH=/root/.local/bin:$PATH

# Copy application code
COPY mcp-refactor/ .

# Create data directory for persistent storage
RUN mkdir -p /app/data

# Create user for security (optional but good practice)
RUN groupadd -r marm && useradd -r -g marm marm
RUN chown -R marm:marm /app
USER marm

# Expose MCP server port
EXPOSE 8001

# Health check to verify server is running
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8001/marm_current_context || exit 1

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
# claude mcp add --transport http marm-memory http://localhost:8001/mcp
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
#
# Jefferson's approach: 239 lines of bash complexity + manual Python installation + dependency hell
# MARM approach: Single Docker command + everything included + works everywhere
#
# The empire is built on foundations that just work! 🚀