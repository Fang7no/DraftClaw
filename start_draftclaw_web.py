from __future__ import annotations

import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from draftclaw.web.app import create_app


HOST = os.getenv("DRAFTCLAW_WEB_HOST", "127.0.0.1")
PORT = int(os.getenv("DRAFTCLAW_WEB_PORT", "5000"))
WEB_ROOT = ROOT / os.getenv("DRAFTCLAW_WEB_ROOT", "output_web")
SETTINGS_PATH = os.getenv("DRAFTCLAW_WEB_SETTINGS_PATH")
DEBUG = os.getenv("DRAFTCLAW_WEB_DEBUG", "").strip().lower() in {"1", "true", "yes", "on"}


def main() -> None:
    app = create_app(
        web_root=WEB_ROOT,
        settings_path=SETTINGS_PATH,
        testing=False,
        auto_start_manager=True,
    )
    print(f"DraftClaw Web running at http://{HOST}:{PORT}")
    print(f"Web root: {WEB_ROOT}")
    app.run(host=HOST, port=PORT, debug=DEBUG, use_reloader=False)


if __name__ == "__main__":
    main()
