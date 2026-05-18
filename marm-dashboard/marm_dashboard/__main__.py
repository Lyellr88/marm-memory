"""Run: python -m marm_dashboard"""

import argparse
import threading
import webbrowser

import uvicorn

from .config import DASHBOARD_HOST, DASHBOARD_PORT, MARM_API_KEY, get_db_path


def main() -> None:
    parser = argparse.ArgumentParser(description="MARM Dashboard — local memory browser")
    parser.add_argument("--host", default=DASHBOARD_HOST, help="Bind host (default 127.0.0.1)")
    parser.add_argument("--port", type=int, default=DASHBOARD_PORT, help="Bind port (default 8002)")
    parser.add_argument(
        "--open",
        action="store_true",
        help="Open the dashboard in your default browser after start",
    )
    args = parser.parse_args()

    url = f"http://{args.host}:{args.port}/"
    print("MARM Dashboard")
    print(f"  Database: {get_db_path()}")
    print(f"  URL:      {url}")
    print("  (MCP server can stay on :8001; this plugin reads the same SQLite file.)")
    if MARM_API_KEY:
        print("  Auth:     MARM_API_KEY set — unlock in browser with the same Bearer key as MCP.")
    else:
        print("  Auth:     loopback only (set MARM_API_KEY to match Docker/MCP).")

    if args.open:

        def _open_browser() -> None:
            webbrowser.open(url)

        threading.Timer(1.2, _open_browser).start()

    uvicorn.run(
        "marm_dashboard.server:app",
        host=args.host,
        port=args.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
