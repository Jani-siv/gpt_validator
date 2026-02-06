
"""Helpers to determine git-created/added/modified files under a path.

This module provides a small, focused API used by multiple scripts in
the `ztests/tools` directory to discover which files under a given
path are untracked/added/modified according to the local git repository.

Functions:
- get_changed_files(path) -> dict with keys `created`, `added`, `modified`, `deleted`
- get_created_files(path) -> list
- get_added_files(path) -> list
- get_modified_files(path) -> list

The implementation uses `git status --porcelain -z` which is stable for
machine parsing and lists staged/unstaged changes as well as untracked files.
"""

from __future__ import annotations

import subprocess
from typing import Dict, List, Set

__all__ = [
	"get_changed_files",
	"get_created_files",
	"get_added_files",
	"get_modified_files",
]


def _run_git_status_porcelain(path: str) -> List[str]:
	"""Run `git status --porcelain -z -- <path>` and return list of entries.

	Each entry is a porcelain token separated by NUL. Tokens are either
	- '?? <file>' for untracked files, or
	- 'XY <file>' where X is staged status and Y is unstaged status.
	"""
	try:
		proc = subprocess.run(
			["git", "status", "--porcelain", "-z", "--", path],
			cwd=None,
			check=True,
			capture_output=True,
			text=True,
		)
	except subprocess.CalledProcessError:
		return []

	# Split on NUL and remove any empty tokens
	tokens = [tok for tok in proc.stdout.split("\0") if tok]
	return tokens


def _normalize_filename_from_token(tok: str) -> tuple[str, str]:
	"""Return (status, filename) from a porcelain token.

	Handles the simple '?? <file>' case and the 'XY <file>' case. For
	rename tokens that may contain '->', the destination filename is
	returned.
	"""
	if tok.startswith("?? "):
		return "??", tok[3:]

	if len(tok) >= 3 and tok[2] == " ":
		status = tok[:2]
		fname = tok[3:]
		# handle rename formatted as 'R100 from -> to'
		if " -> " in fname:
			fname = fname.split(" -> ")[-1]
		return status, fname

	# Fallback: return entire token as filename with empty status
	return "", tok


def get_changed_files(path: str) -> Dict[str, List[str]]:
	"""Return changed files under `path` grouped by kind.

	Returned dict has keys: `created`, `added`, `modified`, `deleted`.
	- `created` contains untracked files (git shows as '??') and staged adds.
	- `added` contains files staged as added (X == 'A').
	- `modified` contains files modified either staged or unstaged (X or Y == 'M').
	- `deleted` contains files deleted (X or Y == 'D').
	"""
	tokens = _run_git_status_porcelain(path)

	created: Set[str] = set()
	added: Set[str] = set()
	modified: Set[str] = set()
	deleted: Set[str] = set()

	for tok in tokens:
		status, fname = _normalize_filename_from_token(tok)

		if status == "??":
			created.add(fname)
			continue

		x = status[0] if len(status) >= 1 else " "
		y = status[1] if len(status) >= 2 else " "

		if x == "A":
			added.add(fname)
			created.add(fname)

		if x == "M" or y == "M":
			modified.add(fname)

		if x == "D" or y == "D":
			deleted.add(fname)

	return {
		"created": sorted(created),
		"added": sorted(added),
		"modified": sorted(modified),
		"deleted": sorted(deleted),
	}


def get_created_files(path: str) -> List[str]:
	"""Return files created under `path` (untracked + staged adds).

	This is a convenience wrapper around `get_changed_files`.
	"""
	return get_changed_files(path)["created"]


def get_added_files(path: str) -> List[str]:
	"""Return files staged as added under `path`.

	This does not include untracked files; use `get_created_files` to
	include untracked files as well.
	"""
	return get_changed_files(path)["added"]


def get_modified_files(path: str) -> List[str]:
	"""Return files modified (staged or unstaged) under `path`.
	"""
	return get_changed_files(path)["modified"]

