#!/usr/bin/env python3
import sys
from pathlib import Path

EXPECTED_DIR = "custom_builder"

def main() -> int:
    if Path.cwd().name != EXPECTED_DIR:
        print(f"ERROR: this script must be run from the '{EXPECTED_DIR}' directory.", file=sys.stderr)
        return 1
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
