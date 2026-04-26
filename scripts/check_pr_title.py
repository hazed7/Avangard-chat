#!/usr/bin/env python3

from __future__ import annotations

import sys

from check_commit_msg import PATTERN


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: check_pr_title.py <pull-request-title>", file=sys.stderr)
        return 2

    pr_title = sys.argv[1].strip()
    if PATTERN.fullmatch(pr_title):
        print("PR title matches Conventional Commits pattern.")
        return 0

    print("Invalid PR title.", file=sys.stderr)
    print("Expected Conventional Commits format.", file=sys.stderr)
    print("Example: feat(auth): add token refresh endpoint", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
