"""
Backward-compatibility entrypoint for MARM STDIO transport.
Run via: python server_stdio.py

Prefer the package form for Docker and pip installs:
  python -m marm_mcp_server.server_stdio
"""

from marm_mcp_server.server_stdio import main

if __name__ == "__main__":
    main()
