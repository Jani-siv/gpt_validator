#!/usr/bin/env python3
"""Simple CLI to verify listed file paths exist.

Usage:
  python verify_files.py path1 path2 --exit-nonzero -v
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
import fnmatch
from typing import Iterable, List, Any
from pathlib import Path as _Path_for_import
# Ensure local tools directory is on sys.path so we can import git_file_handler
_SCRIPT_DIR = _Path_for_import(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
	sys.path.insert(0, str(_SCRIPT_DIR))
try:
	from git_file_handler import get_changed_files
except Exception:
	get_changed_files = None


def verify_paths(paths: Iterable[str]) -> List[str]:
	"""Return a list of paths that do not exist from the given iterable."""
	missing: List[str] = []
	for p in paths:
		if not os.path.exists(p):
			missing.append(p)
	return missing


def load_agent_rules(path: str) -> Any:
	"""Load JSON agent rules from `path` and return the parsed object.

	Raises FileNotFoundError or json.JSONDecodeError on failure.
	"""
	with open(path, "r", encoding="utf-8") as fh:
		return json.load(fh)


def select_project_rules(rules: Any) -> dict:
	if not isinstance(rules, dict):
		return {}
	projects = rules.get("project_configurations")
	if isinstance(projects, list):
		for project in projects:
			if isinstance(project, dict):
				return project
	if isinstance(projects, dict):
		if "project_type" in projects:
			return projects
		for key, value in projects.items():
			if isinstance(value, dict):
				entry = dict(value)
				entry.setdefault("project_type", key)
				return entry
	return rules


def git_modified_files(repo_dir: str) -> List[str]:
	"""Return a list of modified file paths (relative to repo_dir) according to `git status --porcelain`.

	Includes staged and unstaged changes. Raises CalledProcessError if git fails.
	"""
	if not get_changed_files:
		raise RuntimeError('git_file_handler.get_changed_files is unavailable')

	info = get_changed_files(repo_dir)
	# return staged/unstaged modifications and adds/deletes similar to original behavior
	res: List[str] = []
	for k in ("modified", "added", "deleted"):
		for p in info.get(k, []):
			if p not in res:
				res.append(p)
	return res


def git_untracked_files(repo_dir: str) -> List[str]:
	"""Return a list of untracked file paths (relative to repo_dir)."""
	if not get_changed_files:
		raise RuntimeError('git_file_handler.get_changed_files is unavailable')

	info = get_changed_files(repo_dir)
	created = set(info.get("created", []))
	added = set(info.get("added", []))
	return sorted(created - added)


def is_file_modified(repo_dir: str, target_path: str) -> bool:
	"""Return True if `target_path` (absolute or repo-relative) is listed as modified in the git repo."""
	repo = Path(repo_dir)
	modified = git_modified_files(str(repo))
	target = Path(target_path)
	try:
		# If target is inside repo, get repo-relative path
		rel = str(target.relative_to(repo))
	except Exception:
		# Not inside repo: compare by name fallback
		rel = str(target)

	# Normalize paths for comparison
	norm_modified = {os.path.normpath(m) for m in modified}
	return os.path.normpath(rel) in norm_modified or target.name in {Path(m).name for m in modified}


def disallowed_modified_files(repo_dir: str, agent_rules_path: str) -> List[str]:
	"""Return modified files that are NOT allowed by `allowed_to_modify` in the agent rules JSON.

	`agent_rules_path` may be absolute or repo-relative. Paths in `allowed_to_modify` are
	treated as repo-relative prefixes or glob patterns.
	"""
	# Load rules
	rules = load_agent_rules(agent_rules_path)
	project_rules = select_project_rules(rules)
	file_rules = project_rules.get("file_rules", {}) if isinstance(project_rules, dict) else {}
	if not isinstance(file_rules, dict):
		file_rules = {}
	allowed = file_rules.get("allowed_to_modify", project_rules.get("allowed_to_modify", []) if isinstance(project_rules, dict) else [])
	ignored = file_rules.get("ignored_files", project_rules.get("ignored_files", []) if isinstance(project_rules, dict) else [])

	modified = git_modified_files(repo_dir)
	# Also include untracked files explicitly
	try:
		untracked = git_untracked_files(repo_dir)
	except RuntimeError:
		untracked = []

	# Merge lists while normalizing paths for comparison
	seen = set()
	merged: List[str] = []
	for p in modified + untracked:
		if not p:
			continue
		# strip leading ./
		if p.startswith('./'):
			p = p[2:]
		norm = os.path.normpath(p)
		if norm not in seen:
			merged.append(norm)
			seen.add(norm)
	modified = merged
	disallowed: List[str] = []

	# Normalize allowed entries for matching
	norm_allowed = [a for a in allowed]

	for m in modified:
		m_basename = Path(m).name
		# If file matches any ignored pattern, skip checking it
		skip = False
		for pat in ignored:
			try:
				if fnmatch.fnmatch(m, pat) or fnmatch.fnmatch(m_basename, pat):
					skip = True
					break
			except Exception:
				if m.endswith(pat) or m_basename.endswith(pat):
					skip = True
					break
		if skip:
			continue

		m_norm = os.path.normpath(m)
		allowed_match = False
		for a in norm_allowed:
			a_norm = a
			if any(ch in a for ch in ["*", "?", "["]):
				if fnmatch.fnmatch(m_norm, a_norm):
					allowed_match = True
					break
			else:
				# Normalize allowed entry
				a_norm_p = os.path.normpath(a_norm)
				# directory-like allowed entries (ending with / or os.sep) should match prefix
				if a.endswith("/") or a.endswith(os.sep):
					prefix = a_norm_p
					if m_norm == prefix or m_norm.startswith(prefix + os.sep):
						allowed_match = True
						break
				else:
					# exact match or under directory
					if m_norm == a_norm_p or m_norm.startswith(a_norm_p + os.sep):
						allowed_match = True
						break

		if not allowed_match:
			disallowed.append(m_norm)

	return disallowed


def main() -> int:
	"""Run enforcement using paths relative to this script location. Returns exit code.

	Behavior:
	- Determine `script_dir` as this file's directory.
	- `repo_root` is three levels up from `script_dir` (project root).
	- `agent_rules_path` is `script_dir/.agent_rules.json`.
	- Enforce agent rules: print FAIL and list offending files (exit 1) or OK (exit 0).
	"""
	script_dir = Path(__file__).resolve().parent
	repo_root = script_dir.parent.parent.parent
	agent_rules_path = script_dir / ".agent_rules.json"

	# If any CLI args are provided, offer simple query commands instead of enforcement.
	extra_args = sys.argv[1:]
	if extra_args:
		cmd = extra_args[0].lower()
		if cmd in ("-h", "--help", "help"):
			print("Usage:\n  (no args)    Enforce agent rules using tools/.agent_rules.json\n  allowed      Print allowed_to_modify paths from agent rules\n  ignored      Print ignored_files patterns from agent rules")
			return 0
		if cmd in ("allowed", "--allowed"):
			try:
				rules = load_agent_rules(str(agent_rules_path))
			except FileNotFoundError:
				print(f"Agent rules file not found: {agent_rules_path}")
				return 1
			except json.JSONDecodeError as exc:
				print(f"Failed to parse agent rules JSON: {exc}")
				return 1
			project_rules = select_project_rules(rules)
			file_rules = project_rules.get("file_rules", {}) if isinstance(project_rules, dict) else {}
			if not isinstance(file_rules, dict):
				file_rules = {}
			allowed = file_rules.get("allowed_to_modify", project_rules.get("allowed_to_modify", []) if isinstance(project_rules, dict) else [])
			for a in allowed:
				print(a)
			return 0
		if cmd in ("ignored", "--ignored"):
			try:
				rules = load_agent_rules(str(agent_rules_path))
			except FileNotFoundError:
				print(f"Agent rules file not found: {agent_rules_path}")
				return 1
			except json.JSONDecodeError as exc:
				print(f"Failed to parse agent rules JSON: {exc}")
				return 1
			project_rules = select_project_rules(rules)
			file_rules = project_rules.get("file_rules", {}) if isinstance(project_rules, dict) else {}
			if not isinstance(file_rules, dict):
				file_rules = {}
			ignored = file_rules.get("ignored_files", project_rules.get("ignored_files", []) if isinstance(project_rules, dict) else [])
			for p in ignored:
				print(p)
			return 0
		print(f"Unknown command: {extra_args[0]}\nUse 'allowed' to list allowed paths or run without arguments to enforce rules.")
		return 2

	try:
		disallowed = disallowed_modified_files(str(repo_root), str(agent_rules_path))
	except FileNotFoundError:
		print(f"Agent rules file not found: {agent_rules_path}")
		return 1
	except json.JSONDecodeError as exc:
		print(f"Failed to parse agent rules JSON: {exc}")
		return 1

	if disallowed:
		print("FAIL: modified files outside allowed paths:")
		for f in disallowed:
			# Print repo-relative path and absolute path for clarity
			abs_path = str((repo_root / f).resolve())
			print(f"- {f}  ({abs_path})")
		return 1

	print("OK: all modified files are within allowed agent rules paths")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())

