#!/bin/bash

# MARM MCP Server Installation Script
# Version: 2.0.2
# Author: MARM Systems

set -e

echo "🚀 MARM MCP Server v2.0.2 Installation"
echo "======================================"

# Check if Python 3.8+ is available
echo "📋 Checking Python version..."

# Function to compare version numbers
version_compare() {
    local version1=$1
    local version2=$2
    
    # Split versions into major and minor parts
    IFS='.' read -ra VER1 <<< "$version1"
    IFS='.' read -ra VER2 <<< "$version2"
    
    local major1=${VER1[0]}
    local minor1=${VER1[1]:-0}
    local major2=${VER2[0]}
    local minor2=${VER2[1]:-0}
    
    # Compare major version first
    if [ "$major1" -gt "$major2" ]; then
        return 0  # version1 > version2
    elif [ "$major1" -lt "$major2" ]; then
        return 1  # version1 < version2
    fi
    
    # Major versions are equal, compare minor versions
    if [ "$minor1" -ge "$minor2" ]; then
        return 0  # version1 >= version2
    else
        return 1  # version1 < version2
    fi
}

PYTHON_CMD=""
if command -v python3 &> /dev/null; then
    PYTHON_VERSION=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
    if version_compare "$PYTHON_VERSION" "3.8"; then
        PYTHON_CMD="python3"
        echo "✅ Found Python $PYTHON_VERSION"
    else
        echo "⚠️  Found Python $PYTHON_VERSION (too old, need 3.8+)"
    fi
elif command -v python &> /dev/null; then
    PYTHON_VERSION=$(python -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
    if version_compare "$PYTHON_VERSION" "3.8"; then
        PYTHON_CMD="python"
        echo "✅ Found Python $PYTHON_VERSION"
    else
        echo "⚠️  Found Python $PYTHON_VERSION (too old, need 3.8+)"
    fi
fi

if [ -z "$PYTHON_CMD" ]; then
    echo "❌ Python 3.8+ is required but not found"
    echo ""
    echo "📥 Please install Python 3.8+ for your operating system:"
    echo ""
    if [[ "$OSTYPE" == "linux-gnu"* ]]; then
        echo "🐧 Linux:"
        echo "   Ubuntu/Debian: sudo apt update && sudo apt install python3 python3-pip"
        echo "   RHEL/CentOS:   sudo yum install python3 python3-pip"
        echo "   Arch:          sudo pacman -S python python-pip"
        echo "   Or download:   https://www.python.org/downloads/"
    elif [[ "$OSTYPE" == "darwin"* ]]; then
        echo "🍎 macOS:"
        echo "   Homebrew:      brew install python"
        echo "   MacPorts:      sudo port install python39 +universal"
        echo "   Or download:   https://www.python.org/downloads/macos/"
    elif [[ "$OSTYPE" == "msys" || "$OSTYPE" == "cygwin" ]]; then
        echo "🪟 Windows:"
        echo "   Microsoft Store: Search 'Python' in Microsoft Store"
        echo "   Direct download: https://www.python.org/downloads/windows/"
        echo "   Chocolatey:      choco install python"
        echo "   Scoop:           scoop install python"
    else
        echo "🌐 Generic:"
        echo "   Download from:   https://www.python.org/downloads/"
    fi
    echo ""
    echo "After installation, run this script again."
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
echo "🧪 Testing HTTP server startup..."
if timeout 5 $PYTHON_CMD server.py --http --debug < /dev/null 2>&1 | grep -q "Starting HTTP server"; then
    echo "✅ HTTP server starts successfully"
else
    echo "❌ HTTP server failed to start - checking basic import..."
    if $PYTHON_CMD -c "import sys; sys.path.insert(0, '.'); from server import mcp; print('✅ Server imports successfully')" 2>/dev/null; then
        echo "✅ Server imports successfully"
    else
        echo "❌ Server import failed - check dependencies"
        exit 1
    fi
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

# Check if systemd service is running
echo "🚀 Checking MARM MCP HTTP server..."
if systemctl is-active --quiet marm-mcp-server.service 2>/dev/null; then
    SERVER_PID=$(systemctl show --property MainPID --value marm-mcp-server.service)
    echo "✅ MARM MCP server already running (systemd service, PID: $SERVER_PID)"
    echo "📝 Logs: sudo journalctl -u marm-mcp-server.service -f"
    echo "🔧 Control: sudo systemctl {start|stop|restart} marm-mcp-server.service"
elif curl -s http://localhost:9999 >/dev/null 2>&1; then
    echo "✅ MARM MCP server already running on http://localhost:9999"
    echo "📝 Logs may be at /tmp/marm-mcp-server.log"
else
    echo "🚀 Starting MARM MCP HTTP server..."
    nohup $PYTHON_CMD server.py --http --debug > /tmp/marm-mcp-server.log 2>&1 &
    SERVER_PID=$!
    sleep 3
    
    # Check if server started successfully
    if ps -p $SERVER_PID > /dev/null 2>&1 && curl -s http://localhost:9999 >/dev/null 2>&1; then
        echo "✅ MARM MCP server started (PID: $SERVER_PID) on http://localhost:9999"
        echo "📝 Logs: tail -f /tmp/marm-mcp-server.log"
    else
        echo "❌ Failed to start MARM MCP server"
        echo "📝 Check logs: cat /tmp/marm-mcp-server.log"
        exit 1
    fi
fi

# Add to Claude Code
echo ""
echo "🔗 Adding to Claude Code..."
if command -v claude >/dev/null 2>&1; then
    if claude mcp add --transport http marm-memory http://localhost:9999; then
        echo "✅ Successfully added to Claude Code!"
        echo "🔍 Verify with: claude mcp list"
    else
        echo "⚠️  Failed to add automatically. Add manually with:"
        echo "   claude mcp add --transport http marm-memory http://localhost:9999"
    fi
else
    echo "⚠️  Claude Code CLI not found. Add manually with:"
    echo "   claude mcp add --transport http marm-memory http://localhost:9999"
fi

echo ""
echo "🎉 Installation Complete!"
echo ""
echo "🌐 Server Status:"
echo "   • URL: http://localhost:9999"
if systemctl is-active --quiet marm-mcp-server.service 2>/dev/null; then
    SERVER_PID=$(systemctl show --property MainPID --value marm-mcp-server.service)
    echo "   • Service: systemd (marm-mcp-server.service)"
    echo "   • PID: $SERVER_PID"
    echo "   • Logs: sudo journalctl -u marm-mcp-server.service -f"
else
    echo "   • PID: $SERVER_PID (manual process)"
    echo "   • Logs: /tmp/marm-mcp-server.log"
fi
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
echo "🚀 Ready to Use:"
echo "   1. Open Claude Code"
echo "   2. Use 'marm_start' to begin your first session"
echo "   3. Check CLAUDE_CODE_SETUP.md for usage examples"
echo ""
echo "📁 Data stored in: $DATA_DIR"
echo "🔧 Stop server: kill $SERVER_PID"