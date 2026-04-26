#!/usr/bin/env python3

from __future__ import annotations

import re
import sys
from pathlib import Path

PATTERN = re.compile(
    r"^(build|chore|ci|docs|feat|fix|perf|refactor|revert|style|test)"
    r"(\([a-z0-9][a-z0-9._/-]*\))?(!)?: [^\s].*$"
)


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: check_commit_msg.py <commit-msg-file>", file=sys.stderr)
        return 2

    commit_msg_file = Path(sys.argv[1])
    if not commit_msg_file.exists():
        print(f"Commit message file not found: {commit_msg_file}", file=sys.stderr)
        return 2

    first_line = commit_msg_file.read_text(encoding="utf-8").splitlines()
    message = first_line[0].strip() if first_line else ""

    if PATTERN.fullmatch(message):
        return 0

    print("Invalid commit message.", file=sys.stderr)
    print("Required pattern:", PATTERN.pattern, file=sys.stderr)
    print("Example: feat(auth): add token refresh endpoint", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
