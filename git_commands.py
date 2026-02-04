"""Small helper to list git changes for a repository path.

Provides a single function `get_git_changes(path)` which returns a dict with
three lists: 'modified', 'created', and 'staged'. Paths are returned relative
to the given repository path.

This file is intentionally dependency-free and easy to import from other
modules (e.g. `from git_commands import get_git_changes`).
"""
from __future__ import annotations

import os
import subprocess
from typing import Dict, List


def _parse_porcelain_line(line: str) -> str:
    """Return the file path part from a porcelain status line.

    Handles rename lines like `R  old -> new` by returning the new path.
    """
    # porcelain format: XY SP <path> [-> <path>]
    # untracked lines start with '?? '
    if line.startswith("?? "):
        return line[3:]
    # normal case: first 3 chars are status and a space
    tail = line[3:]
    if " -> " in tail:
        return tail.split(" -> ", 1)[1]
    return tail


def get_git_changes(repo_path: str) -> Dict[str, List[str]]:
    """Return git changed files under `repo_path`.

    Returns a dict with keys:
      - 'modified': files modified in working tree or index
      - 'created': newly created files (untracked or staged additions)
      - 'staged': files staged in the index

    Each value is a list of file paths (strings) relative to `repo_path`.

    If `repo_path` is not a git repository or git fails, this raises
    `subprocess.CalledProcessError`.
    """
    # Ensure path exists
    repo_path = os.fspath(repo_path)
    if not os.path.exists(repo_path):
        raise FileNotFoundError(repo_path)

    # Use porcelain format for stable parsing
    completed = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo_path,
        capture_output=True,
        text=True,
        check=True,
    )

    modified = set()
    created = set()
    staged = set()

    for raw in completed.stdout.splitlines():
        if not raw:
            continue

        path = _parse_porcelain_line(raw).strip()

        # status characters
        if raw.startswith("?? "):
            # untracked -> created
            created.add(path)
            continue

        status = raw[:2]
        x, y = status[0], status[1]

        # staged if index status (X) is not space
        if x != " ":
            staged.add(path)

        # modified: either staged as modified or modified in working tree
        if x == "M" or y == "M":
            modified.add(path)

        # created: staged additions (A)
        if x == "A":
            created.add(path)

    # Return sorted lists for deterministic order
    return {
        "modified": sorted(modified),
        "created": sorted(created),
        "staged": sorted(staged),
    }


__all__ = ["get_git_changes"]
