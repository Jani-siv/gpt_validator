
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

import codecs
import subprocess
import os
from typing import Dict, List, Set

__all__ = [
	"get_changed_files",
	"get_changed_lines_and_files",
	"get_created_files",
	"get_added_files",
	"get_modified_files",
	"get_repo_root",
]


def _run_git_status_porcelain(repo_dir: str) -> List[str]:
	"""Run `git status --porcelain=v1 -uall` and return list of entries.

	Each entry is a porcelain line. Lines are either
	- '?? <file>' for untracked files, or
	- 'XY <file>' where X is staged status and Y is unstaged status.
	"""
	try:
		proc = subprocess.run(
			["git", "-C", repo_dir, "status", "--porcelain=v1", "-uall"],
			check=True,
			capture_output=True,
			text=True,
		)
	except subprocess.CalledProcessError:
		return []

	return [ln for ln in proc.stdout.splitlines() if ln]


def _run_git_ls_files(repo_dir: str) -> List[str]:
	"""Run `git ls-files -o --exclude-standard` and return list of entries."""
	try:
		proc = subprocess.run(
			["git", "-C", repo_dir, "ls-files", "-o", "--exclude-standard"],
			check=True,
			capture_output=True,
			text=True,
		)
	except subprocess.CalledProcessError:
		return []

	return [ln for ln in proc.stdout.splitlines() if ln]


def get_repo_root(path: str) -> str | None:
	"""Return the repository root for a path, or None if not in a repo."""
	try:
		proc = subprocess.run(
			["git", "-C", path, "rev-parse", "--show-toplevel"],
			check=True,
			capture_output=True,
			text=True,
		)
	except subprocess.CalledProcessError:
		return None

	root = proc.stdout.strip()
	return root or None


def _normalize_filename_from_token(tok: str) -> tuple[str, str]:
	"""Return (status, filename) from a porcelain token.

	Handles the simple '?? <file>' case and the 'XY <file>' case. For
	rename tokens that may contain '->', the destination filename is
	returned.
	"""
	if tok.startswith("?? "):
		return "??", _unquote_git_path(tok[3:])

	if len(tok) >= 3 and tok[2] == " ":
		status = tok[:2]
		fname = tok[3:]
		# handle rename formatted as 'R100 from -> to'
		if " -> " in fname:
			fname = fname.split(" -> ")[-1]
		return status, _unquote_git_path(fname)

	# Fallback: return entire token as filename with empty status
	return "", _unquote_git_path(tok)


def _unquote_git_path(path: str) -> str:
	"""Return a git porcelain path with optional C-quoting unescaped."""
	if len(path) >= 2 and path[0] == '"' and path[-1] == '"':
		return codecs.decode(path[1:-1], "unicode_escape")
	return path


def get_changed_files(path: str) -> Dict[str, List[str]]:
	"""Return changed files under `path` grouped by kind.

	Returned dict has keys: `created`, `added`, `modified`, `deleted`.
	- `created` contains untracked files (git shows as '??') and staged adds.
	- `added` contains files staged as added (X == 'A').
	- `modified` contains files modified either staged or unstaged (X or Y == 'M').
	- `deleted` contains files deleted (X or Y == 'D').
	"""
	repo_root = get_repo_root(path)
	if not repo_root:
		return {
			"created": [],
			"added": [],
			"modified": [],
			"deleted": [],
		}

	lines = _run_git_status_porcelain(repo_root)

	created: Set[str] = set()
	added: Set[str] = set()
	modified: Set[str] = set()
	deleted: Set[str] = set()

	for line in lines:
		status, fname = _normalize_filename_from_token(line)

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

	for fname in _run_git_ls_files(repo_root):
		name = fname
		if name.startswith('./'):
			name = name[2:]
		if name:
			created.add(name)

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

def get_changed_lines_and_files(path: str) -> Dict[str, List[Dict[str, str]]]:
	"""Return changed files and the changed content.

	Returns a dict of the form:
	{
		"data": [
			{"file": "file.txt", "content": "changed content or file content"},
			...
		]
	}

	- For untracked/created files the current file content is returned.
	- For modified/deleted files a git diff (minimal context) vs HEAD is returned
	  where available. If no diff is available the current file content is
	  returned when possible.
	"""
	repo_root = get_repo_root(path)
	if not repo_root:
		return {"data": []}

	changed = get_changed_files(path)
	created = set(changed.get("created", []))
	added = set(changed.get("added", []))
	modified = set(changed.get("modified", []))
	deleted = set(changed.get("deleted", []))

	def _read_file(fname: str) -> str:
		abs_path = os.path.join(repo_root, fname)
		try:
			with codecs.open(abs_path, "r", "utf-8", "replace") as fh:
				return fh.read()
		except FileNotFoundError:
			return ""
		except Exception:
			return ""

	def _git_diff(fname: str) -> str:
		def _run(args: List[str]) -> str:
			try:
				proc = subprocess.run(
					["git", "-C", repo_root] + args,
					check=True,
					capture_output=True,
					text=True,
				)
			except subprocess.CalledProcessError:
				return ""
			return proc.stdout

		# Try working-tree vs HEAD (covers staged+unstaged), then staged only
		diff = _run(["diff", "--no-color", "-U0", "HEAD", "--", fname])
		if not diff:
			diff = _run(["diff", "--no-color", "-U0", "--cached", "--", fname])
		return diff

	def _parse_diff_changes(diff_text: str) -> tuple[str, str]:
		"""Parse a unified diff and return (added_text, deleted_text).

		- `added_text` is the concatenation of lines starting with '+' (excluding
		  diff headers like '+++').
		- `deleted_text` is the concatenation of lines starting with '-' (excluding
		  diff headers like '---').
		"""
		added_lines: List[str] = []
		deleted_lines: List[str] = []
		for ln in diff_text.splitlines():
			if ln.startswith('+++') or ln.startswith('---'):
				continue
			if ln.startswith('+') and not ln.startswith('+++'):
				added_lines.append(ln[1:])
			elif ln.startswith('-') and not ln.startswith('---'):
				deleted_lines.append(ln[1:])
		return ("\n".join(added_lines), "\n".join(deleted_lines))

	results: List[Dict[str, str]] = []
	all_files = sorted(created | added | modified | deleted)
	for fname in all_files:
		added_text = ""
		modified_text = ""
		deleted_text = ""

		if fname in created or fname in added:
			# New files: treat full file content as 'added'
			added_text = _read_file(fname)
		else:
			diff = _git_diff(fname)
			if diff:
				a, d = _parse_diff_changes(diff)
				# For modified files, consider the added portion as 'modified'.
				modified_text = a
				deleted_text = d
			else:
				# Fallback: if no diff available, return full file content
				# as 'modified' for visibility.
				modified_text = _read_file(fname)

		results.append({
			"file": fname,
			"added": added_text,
			"modified": modified_text,
			"deleted": deleted_text,
		})

	return {"data": results}

