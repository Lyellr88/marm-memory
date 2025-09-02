#!/bin/bash

# MARM MCP Server Installation Script
# Version: 2.0.1
# Author: MARM Systems

set -e

echo "🚀 MARM MCP Server v2.0.1 Installation"
echo "======================================"

# Check if Python 3.8+ is available
echo "📋 Checking Python version..."
PYTHON_CMD=""
if command -v python3 &> /dev/null; then
    PYTHON_VERSION=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
    if [[ $(echo "$PYTHON_VERSION >= 3.8" | bc -l) -eq 1 ]]; then
        PYTHON_CMD="python3"
        echo "✅ Found Python $PYTHON_VERSION"
    fi
elif command -v python &> /dev/null; then
    PYTHON_VERSION=$(python -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
    if [[ $(echo "$PYTHON_VERSION >= 3.8" | bc -l) -eq 1 ]]; then
        PYTHON_CMD="python"
        echo "✅ Found Python $PYTHON_VERSION"
    fi
fi

if [ -z "$PYTHON_CMD" ]; then
    echo "❌ Python 3.8+ is required but not found"
    echo "Please install Python 3.8 or later and try again"
    exit 1
fi

# Install Python dependencies
echo "📦 Installing Python dependencies..."
if command -v pip3 &> /dev/null; then
    pip3 install -r requirements.txt
elif command -v pip &> /dev/null; then
    pip install -r requirements.txt
else
    echo "❌ pip is not available. Please install pip and try again"
    exit 1
fi

# Test server startup
echo "🧪 Testing server startup..."
if $PYTHON_CMD server.py --debug &
then
    SERVER_PID=$!
    sleep 3
    if ps -p $SERVER_PID > /dev/null; then
        echo "✅ Server started successfully (PID: $SERVER_PID)"
        kill $SERVER_PID
        wait $SERVER_PID 2>/dev/null || true
    else
        echo "❌ Server failed to start"
        exit 1
    fi
else
    echo "❌ Failed to start server"
    exit 1
fi

# Create data directory
echo "📁 Creating data directory..."
DATA_DIR="$HOME/.marm-mcp"
mkdir -p "$DATA_DIR"
echo "✅ Data directory created: $DATA_DIR"

# Check for Claude Desktop config
CLAUDE_CONFIG=""
if [[ "$OSTYPE" == "darwin"* ]]; then
    CLAUDE_CONFIG="$HOME/Library/Application Support/Claude/claude_desktop_config.json"
elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
    CLAUDE_CONFIG="$HOME/.config/claude-desktop/claude_desktop_config.json"
fi

if [ -n "$CLAUDE_CONFIG" ]; then
    echo "🔧 Claude Desktop configuration:"
    echo "   File: $CLAUDE_CONFIG"
    
    if [ ! -f "$CLAUDE_CONFIG" ]; then
        echo "   Status: ⚠️  Configuration file not found"
        echo "   You'll need to create it manually"
    else
        echo "   Status: ✅ Configuration file exists"
        echo "   Please add the MARM server configuration manually"
    fi
    
    echo ""
    echo "📋 Configuration to add:"
    echo '{'
    echo '  "mcp": {'
    echo '    "servers": {'
    echo '      "marm-memory": {'
    echo "        \"command\": \"$PYTHON_CMD\","
    echo "        \"args\": [\"$(pwd)/server.py\"],"
    echo '        "env": {'
    echo "          \"PYTHONPATH\": \"$(pwd)\""
    echo '        }'
    echo '      }'
    echo '    }'
    echo '  }'
    echo '}'
else
    echo "⚠️  Could not determine Claude Desktop config location"
    echo "Please refer to the README.md for manual configuration"
fi

echo ""
echo "🎉 Installation Complete!"
echo ""
echo "📚 Available MCP Tools:"
echo "   • marm_start - Activate MARM protocol"
echo "   • marm_log_entry - Add structured log entries"
echo "   • marm_notebook_add - Store key information"
echo "   • marm_notebook_show - Display notebook entries"
echo "   • marm_notebook_use - Activate notebook entries"
echo "   • marm_session_summary - Generate session summaries"
echo "   • marm_show_context - View current session status"
echo "   • marm_list_sessions - List all sessions"
echo ""
echo "🚀 Next Steps:"
echo "   1. Restart Claude Desktop if running"
echo "   2. Use 'marm_start' to begin your first session"
echo "   3. Check the README.md for usage examples"
echo ""
echo "📁 Data stored in: $DATA_DIR"
echo "🐛 Debug mode: $PYTHON_CMD server.py --debug"