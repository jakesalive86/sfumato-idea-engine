"""Call a hosted Sfumato Gradio Space and print its JSON seed packet."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--space",
        default=os.environ.get("SFUMATO_SPACE"),
        help="Hugging Face Space namespace/name (or SFUMATO_SPACE)",
    )
    parser.add_argument("--brief-file", required=True, type=Path)
    parser.add_argument("--candidate-count", choices=(33, 100), type=int, default=33)
    parser.add_argument("--max-selected-seeds", type=int, choices=range(1, 6), default=5)
    parser.add_argument("--trials-per-pass", type=int, choices=(8,), default=8)
    parser.add_argument("--word-range", type=int, nargs=2, default=(100, 180))
    parser.add_argument("--client-run-id", default="")
    args = parser.parse_args()
    if not args.space:
        parser.error("provide --space or set SFUMATO_SPACE")
    return args


def unwrap_result(result: Any) -> Any:
    if isinstance(result, (tuple, list)) and len(result) == 1:
        result = result[0]
    if isinstance(result, str):
        try:
            result = json.loads(result)
        except json.JSONDecodeError:
            pass
    return result


def main() -> int:
    args = parse_args()
    try:
        brief = args.brief_file.read_text(encoding="utf-8").strip()
    except OSError:
        print("Could not read the brief file.", file=sys.stderr)
        return 2
    if not brief:
        print("The brief file is empty.", file=sys.stderr)
        return 2

    try:
        from gradio_client import Client

        token = os.environ.get("HF_TOKEN") or None
        client = Client(args.space, hf_token=token, verbose=False)
        result = client.predict(
            brief,
            args.candidate_count,
            args.max_selected_seeds,
            args.trials_per_pass,
            list(args.word_range),
            args.client_run_id,
            api_name="/generate_seed_packet",
        )
    except Exception as exc:  # noqa: BLE001 - never print remote tracebacks or secrets
        print(f"Sfumato request failed ({type(exc).__name__}).", file=sys.stderr)
        return 1

    result = unwrap_result(result)
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
