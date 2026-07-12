"""Run MARM Console's standalone localhost API host."""

import os

import uvicorn


def main() -> None:
    uvicorn.run(
        "server.app:app",
        host=os.environ.get("MARM_CONSOLE_HOST", "127.0.0.1"),
        port=int(os.environ.get("MARM_CONSOLE_PORT", "8002")),
        log_level="info",
    )


if __name__ == "__main__":
    main()
