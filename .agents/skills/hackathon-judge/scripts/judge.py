#!/usr/bin/env python3
"""Run a local engineering gate without inventing hackathon scores.

Static file presence cannot establish impact, live inference, or demo quality.
Use the dated evidence review for subjective rubric scoring.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--format", choices=["text", "json"], default="text")
    parser.add_argument("--run-checks", action="store_true", help="Execute make check now")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[4]
    exit_code = None
    if args.run_checks:
        result = subprocess.run(["make", "check"], cwd=root, capture_output=True, text=True)
        exit_code = result.returncode
        if args.format == "text":
            print(result.stdout, end="")
            print(result.stderr, end="")
    report = {
        "timestamp": datetime.now(UTC).isoformat(),
        "check_exit_code": exit_code,
        "check_status": "not_run" if exit_code is None else "passed" if exit_code == 0 else "failed",
        "hackathon_score": None,
        "evidence_review": "docs/QUALITY_REVIEW.md",
        "limitations": [
            "This command does not assign an official or simulated judging score.",
            "make check does not establish live Meta inference or customer impact.",
            "Run contained integration and inspect the matching artifacts separately.",
        ],
    }
    print(json.dumps(report, indent=2) if args.format == "json" else "\n".join(f"{key}: {value}" for key, value in report.items()))
    return exit_code or 0


if __name__ == "__main__":
    raise SystemExit(main())
