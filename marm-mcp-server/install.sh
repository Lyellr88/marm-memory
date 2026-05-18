#!/bin/bash
set -e  # Exit on any error

echo "🚀 MARM MCP Server Installation"
echo "==============================================="

# Python version validation
check_python() {
    if ! command -v python3 &> /dev/null; then
        echo "❌ Python 3 not found. Please install Python 3.8+ first."
        exit 1
    fi
    
    PYTHON_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    echo "📍 Found Python $PYTHON_VERSION"
    
    if ! python3 -c "import sys; sys.exit(0 if sys.version_info >= (3,8) else 1)"; then
        echo "❌ Python 3.8+ required. Found: $PYTHON_VERSION"
        exit 1
    fi
}

# Virtual environment setup
setup_venv() {
    echo "📦 Creating isolated environment..."
    python3 -m venv marm-env
    source marm-env/bin/activate
    python3 -m pip install --upgrade pip
}

# Dependencies installation with progress
install_deps() {
    echo "⬇️  Installing MARM dependencies..."
    pip install -r requirements.txt
    
    echo "🧠 Pre-downloading AI models (this may take 2-3 minutes)..."
    python3 -c "
from sentence_transformers import SentenceTransformer
import sys
try:
    print('Downloading semantic model...')
    SentenceTransformer('all-MiniLM-L6-v2')
    print('✅ AI models ready!')
except Exception as e:
    print(f'⚠️  Model download failed: {e}')
    sys.exit(1)
"
}

# System validation
validate_install() {
    echo "🔍 Validating installation..."
    python3 -c "import marm_mcp_server; print('Import OK')"
}

# Main installation flow
main() {
    check_python
    setup_venv
    install_deps
    validate_install
    
    echo ""
    echo "✅ MARM MCP Server installed successfully!"
    echo ""
    echo "🔧 To start the server:"
    echo "   source marm-env/bin/activate"
    echo "   python3 -m marm_mcp_server"
    echo ""
    echo "🔗 Connect to Claude Desktop:"
    echo "   Add MCP server: http://localhost:8001"
}

main "$@"