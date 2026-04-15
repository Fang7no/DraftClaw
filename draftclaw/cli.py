"""
Small command-line entrypoint for running DraftClaw locally.
"""

from __future__ import annotations

import argparse
import os
import sys
import threading
import webbrowser
from pathlib import Path


PACKAGE_DIR = Path(__file__).resolve().parent
if str(PACKAGE_DIR) not in sys.path:
    sys.path.insert(0, str(PACKAGE_DIR))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run DraftClaw Web UI.")
    parser.add_argument("--host", default=os.getenv("DRAFTCLAW_WEB_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.getenv("DRAFTCLAW_WEB_PORT", "5000")))
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(argv)

    from web.app import create_app

    url = f"http://127.0.0.1:{args.port}"
    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    create_app().run(
        host=args.host,
        port=args.port,
        debug=args.debug,
        use_reloader=False,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
