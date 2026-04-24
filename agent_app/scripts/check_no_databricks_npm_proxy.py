#!/usr/bin/env python3
"""Fail if the frontend lockfile pins tarballs to the Databricks npm proxy."""

from __future__ import annotations

from pathlib import Path
import sys


PROXY_HOST = "npm-proxy.dev.databricks.com"
LOCKFILE = (
    Path(__file__).resolve().parents[1] / "e2e-chatbot-app-next" / "package-lock.json"
)


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(Path.cwd()))
    except ValueError:
        return str(path)


def main() -> int:
    if not LOCKFILE.exists():
        print(f"Lockfile not found: {LOCKFILE}", file=sys.stderr)
        return 1

    violations = [
        (line_number, line.rstrip())
        for line_number, line in enumerate(
            LOCKFILE.read_text(encoding="utf-8").splitlines(), start=1
        )
        if PROXY_HOST in line
    ]

    if not violations:
        return 0

    print(
        f"Found {PROXY_HOST} in {display_path(LOCKFILE)}. "
        "Use https://registry.npmjs.org tarball URLs so Databricks workspace deploys "
        "can install dependencies.",
        file=sys.stderr,
    )
    for line_number, line in violations:
        print(f"{line_number}: {line}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
