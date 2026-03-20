from __future__ import annotations

import argparse
import asyncio
import json

from draftclaw.app import DraftClawApp
from draftclaw._core.enums import ModeName
from draftclaw._core.exceptions import DraftClawError


class CLIConfigurationError(ValueError):
    pass


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="draftclaw", description="DraftClaw academic review CLI")
    parser.add_argument("--config", help="Path to yaml config. Defaults to the packaged config.")
    parser.add_argument("--working-dir", help="Override the working directory used for runs and cache output")
    parser.add_argument("--api-key", help="Override the LLM API key")
    parser.add_argument("--base-url", help="Override the LLM base URL")
    parser.add_argument("--model", help="Override the LLM model name")

    sub = parser.add_subparsers(dest="command", required=True)

    review = sub.add_parser("review", help="Run academic document review")
    review.add_argument("--input", help="Override the input file path from config")
    review.add_argument("--mode", choices=["fast", "standard"], help="Override the review mode from config")
    review.add_argument("--run-name", required=False, help="Optional run name")

    validate = sub.add_parser("validate", help="Validate a mode_result JSON")
    validate.add_argument("--result", required=True)

    capabilities = sub.add_parser("capabilities", help="Show local parsing capability report")
    capabilities.add_argument("--json", action="store_true", help="Print raw JSON only")

    return parser


async def _run_async(args: argparse.Namespace) -> int:
    llm_override = {
        key: value
        for key, value in {
            "api_key": args.api_key,
            "base_url": args.base_url,
            "model": args.model,
        }.items()
        if value
    }
    app = DraftClawApp(args.config, llm_override=llm_override or None, working_dir=args.working_dir)

    if args.command == "validate":
        result = app.validate_result(args.result)
        print(
            json.dumps(
                {
                    "valid": True,
                    "mode": result.mode.value,
                    "errors": len(result.errorlist),
                    "checks": len(result.checklist),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if args.command == "capabilities":
        report = app.capability_report()
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    if args.command == "review":
        input_path = args.input or app.config.run.input_file
        if not str(input_path).strip():
            raise CLIConfigurationError("Review input is not configured. Set run.input_file in default.yaml or pass --input.")

        configured_mode = args.mode or app.config.run.mode
        if configured_mode is None:
            raise CLIConfigurationError("Review mode is not configured. Set run.mode in default.yaml or pass --mode.")
        try:
            mode = configured_mode if isinstance(configured_mode, ModeName) else ModeName(str(configured_mode).strip().lower())
        except ValueError as exc:
            raise CLIConfigurationError("Review mode must be either 'fast' or 'standard'.") from exc

        run_name = args.run_name if args.run_name is not None else app.config.run.run_name
        result, run_root = await app.review(input_path=str(input_path), mode=mode, run_name=run_name)
        print(
            json.dumps(
                {
                    "run_root": str(run_root.resolve()),
                    "mode": result.mode.value,
                    "errors": len(result.errorlist),
                    "checks": len(result.checklist),
                    "latency_ms": result.stats.latency_ms,
                    "parser_backend": result.stats.parser_backend,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    return 1


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    try:
        raise SystemExit(asyncio.run(_run_async(args)))
    except CLIConfigurationError as exc:
        parser.error(str(exc))
    except DraftClawError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
