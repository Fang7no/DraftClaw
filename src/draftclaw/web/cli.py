from __future__ import annotations

import argparse
import os
from pathlib import Path

from draftclaw.web.app import create_app


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="draftclaw-web", description="DraftClaw local web console")
    parser.add_argument("--host", default=os.getenv("DRAFTCLAW_WEB_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("DRAFTCLAW_WEB_PORT", "5000")))
    parser.add_argument("--web-root", default=os.getenv("DRAFTCLAW_WEB_ROOT", "output_web"))
    parser.add_argument("--settings-path", default=os.getenv("DRAFTCLAW_WEB_SETTINGS_PATH"))
    parser.add_argument(
        "--debug",
        action=argparse.BooleanOptionalAction,
        default=_env_flag("DRAFTCLAW_WEB_DEBUG"),
        help="Enable Flask debug mode.",
    )
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    web_root = Path(args.web_root).expanduser()
    app = create_app(
        web_root=web_root,
        settings_path=args.settings_path,
        testing=False,
        auto_start_manager=True,
    )
    print(f"DraftClaw Web running at http://{args.host}:{args.port}")
    print(f"Web root: {web_root.resolve()}")
    app.run(host=args.host, port=args.port, debug=args.debug, use_reloader=False)


if __name__ == "__main__":
    main()
