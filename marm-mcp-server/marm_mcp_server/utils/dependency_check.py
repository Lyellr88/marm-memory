"""Reusable dependency checks for legacy and product CLI diagnostics."""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

from ..config.settings import CONCEPT_MODEL_AVAILABLE, DEFAULT_DB_PATH


def dependency_checks() -> list[dict]:
    checks = [
        {
            "name": "python",
            "ok": sys.version_info >= (3, 10),
            "detail": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            "required": True,
        }
    ]
    required_modules = (
        ("fastapi", "FastAPI"),
        ("fastapi_mcp", "FastAPI MCP"),
        ("uvicorn", "Uvicorn"),
        ("pydantic", "Pydantic"),
        ("sqlite3", "SQLite"),
        ("structlog", "structlog"),
        ("spacy", "spaCy concept extraction runtime"),
    )
    for module, label in required_modules:
        checks.append(
            {
                "name": module,
                "ok": importlib.util.find_spec(module) is not None,
                "detail": label,
                "required": True,
            }
        )
    checks.extend(
        [
            {
                "name": "fastembed",
                "ok": importlib.util.find_spec("fastembed") is not None,
                "detail": "Optional semantic search runtime",
                "required": False,
            },
            {
                "name": "apscheduler",
                "ok": importlib.util.find_spec("apscheduler") is not None,
                "detail": "Optional automation scheduler",
                "required": False,
            },
            {
                "name": "concept_model",
                "ok": CONCEPT_MODEL_AVAILABLE,
                "detail": "Bundled en_core_web_sm concept extraction model",
                "required": True,
            },
        ]
    )
    db_dir = Path(DEFAULT_DB_PATH).parent
    checks.append(
        {
            "name": "database_directory",
            "ok": db_dir.exists() and os.access(db_dir, os.W_OK),
            "detail": str(db_dir),
            "required": True,
        }
    )
    return checks


def check_dependencies() -> bool:
    """Print the compatibility dependency report and return required readiness."""
    checks = dependency_checks()
    print("MARM MCP Server - Dependency Check")
    print("=" * 40)
    for check in checks:
        label = "OK" if check["ok"] else "MISSING"
        optional = " (optional)" if not check["required"] else ""
        print(f"{label} {check['name']}{optional}: {check['detail']}")
    required_ok = all(check["ok"] for check in checks if check["required"])
    print("=" * 40)
    if required_ok:
        print("All dependencies satisfied!")
        print("Ready to start MARM MCP Server")
    else:
        print("Required dependencies are missing.")
        print("Repair with: python -m pip install -U --force-reinstall marm-mcp-server")
    return required_ok
