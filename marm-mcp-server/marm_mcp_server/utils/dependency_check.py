"""Validates MARM MCP Server system dependencies at CLI time."""

import os
import sys
from pathlib import Path

from ..config.settings import (
    DEFAULT_DB_PATH,
    SCHEDULER_AVAILABLE,
    SEMANTIC_SEARCH_AVAILABLE,
)


def check_dependencies():
    """Validate all system dependencies and requirements"""
    print("MARM MCP Server - Dependency Check")
    print("=" * 40)

    issues = []

    python_version = (
        f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    )
    print(f"Python version: {python_version}")
    if sys.version_info < (3, 8):
        issues.append("Python 3.8+ required")
    else:
        print("Python version OK")

    required_modules = [
        ("fastapi", "FastAPI web framework"),
        ("fastapi_mcp", "MCP protocol implementation"),
        ("uvicorn", "ASGI web server"),
        ("pydantic", "Data validation"),
        ("sqlite3", "Database (built-in)"),
        ("structlog", "Structured logging"),
    ]

    for module, description in required_modules:
        try:
            __import__(module)
            print(f"OK {description}")
        except ImportError:
            issues.append(f"Missing: {module} ({description})")
            print(f"Missing: {module}")

    print("\nOptional Features:")
    if SEMANTIC_SEARCH_AVAILABLE:
        print("OK Semantic search (fastembed)")
    else:
        print("Semantic search disabled - install fastembed")

    if SCHEDULER_AVAILABLE:
        print("OK Automation scheduler (apscheduler)")
    else:
        print("Scheduler disabled - install apscheduler")

    print(f"\nDatabase location: {DEFAULT_DB_PATH}")
    db_dir = Path(DEFAULT_DB_PATH).parent
    if db_dir.exists() and os.access(db_dir, os.W_OK):
        print("OK Database directory writable")
    else:
        issues.append(f"Cannot write to database directory: {db_dir}")

    print("\n" + "=" * 40)
    if issues:
        print("Issues found:")
        for issue in issues:
            print(f"   • {issue}")
        print("\nRun: pip install -r requirements.txt")
        return False
    else:
        print("All dependencies satisfied!")
        print("Ready to start MARM MCP Server")
        return True
