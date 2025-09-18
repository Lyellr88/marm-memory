@echo off
REM MARM MCP Server - Windows Docker Run Script

echo 🐳 Starting MARM Universal MCP Server...

REM Create data directory if it doesn't exist
if not exist "data" mkdir data

REM Start with Docker Compose
echo 📦 Starting containers with Docker Compose...
docker-compose up -d

REM Wait a moment for startup
timeout /t 5 /nobreak >nul

REM Check if container is running
docker-compose ps

echo.
echo ✅ MARM MCP Server is running!
echo.
echo 📍 Server URL: http://localhost:8001/mcp
echo 🔗 Claude Code connection: 
echo    claude mcp add --transport http marm-memory http://localhost:8001/mcp
echo.
echo 📊 View logs: docker-compose logs -f marm-mcp-server
echo 🛑 Stop server: docker-compose down
echo.

pause