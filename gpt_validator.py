#!/usr/bin/env python3
"""gpt_validator CLI entrypoint.

Usage:
	python gpt_validator.py [--help|--run-tests|--rules <path>]

Supported params:
	--help       Show this help message (lists available params)
	--run-tests  Run the repository unit tests (invokes `python -m pytest`)
	--rules PATH Load validation rules from PATH (if omitted, attempts
							to load ./validation_rules.json)
"""

import sys
import os
import subprocess
from typing import List


AVAILABLE_PARAMS: List[str] = ["--help", "--run-tests", "--rules <path>"]


def print_help() -> None:
	"""Print the list of available command-line parameters."""
	print("Available params:")
	for p in AVAILABLE_PARAMS:
		print("  " + p)


def _run_pytest(repo_path: str) -> int:
	"""Run pytest using the current Python executable in `repo_path`.

	Returns the pytest process return code.
	"""
	cmd = [sys.executable, "-m", "pytest", "-q"]
	proc = subprocess.run(cmd, cwd=repo_path)
	return proc.returncode


def list_files_with_extension(extension: str, exclude_paths=None, repo_root: str | None = None):
	"""Return files under the repo root matching a single extension and not in exclude paths.

	Parameters
	- extension: file extension to match (with or without leading dot), e.g. 'py' or '.py'
	- exclude_paths: optional list of paths (files or directories). If a path
	  is absolute it is used directly; otherwise it is resolved relative to
	  the repository root. Any file that is equal to or is under one of the
	  exclude paths will be excluded.
	- repo_root: optional repository root. If not provided, the directory
	  containing this script is used.

	Returns a sorted list of file paths relative to `repo_root`.
	"""
	import fnmatch

	if repo_root is None:
		repo_root = os.path.dirname(__file__)
	repo_root = os.path.abspath(repo_root)

	if exclude_paths is None:
		exclude_paths = []

	# Normalize extension
	if not extension.startswith("."):
		ext = "." + extension
	else:
		ext = extension

	# Resolve exclude paths to absolute canonical form
	resolved_excludes = []
	for p in exclude_paths:
		if os.path.isabs(p):
			resolved = os.path.normpath(p)
		else:
			resolved = os.path.normpath(os.path.join(repo_root, p))
		resolved_excludes.append(resolved)

	matches = []
	for root, dirs, files in os.walk(repo_root, topdown=True):
		# allow pruning directories that are excluded
		abs_root = os.path.abspath(root)
		skip_dir = False
		for ex in resolved_excludes:
			if abs_root == ex or abs_root.startswith(ex + os.sep):
				skip_dir = True
				break
		if skip_dir:
			# mutate dirs in-place to avoid walking into them
			dirs.clear()
			continue

		for fname in files:
			if not fname.endswith(ext):
				continue
			abs_path = os.path.join(abs_root, fname)
			excluded = False
			for ex in resolved_excludes:
				if abs_path == ex or abs_path.startswith(ex + os.sep):
					excluded = True
					break
			if excluded:
				continue

			rel = os.path.relpath(abs_path, repo_root)
			matches.append(rel)

	return sorted(matches)


def check_files_tested(files, test_root, repo_root: str | None = None):
	"""Check whether each file in `files` is referenced by at least one test file under `test_root`.

	- `files`: iterable of file paths relative to `repo_root`.
	- `test_root`: absolute or repo-relative path to tests directory.
	- `repo_root`: repository root; defaults to this script's directory.

	Returns None if all files are tested, otherwise returns the first filename (relative to repo_root)
	that appears to be untested.
	"""
	if repo_root is None:
		repo_root = os.path.dirname(__file__)
	repo_root = os.path.abspath(repo_root)

	# Resolve test_root to absolute
	if os.path.isabs(test_root):
		tests_abs = test_root
	else:
		tests_abs = os.path.normpath(os.path.join(repo_root, test_root))

	# Collect all test file contents
	test_sources = []
	for root, _, fnames in os.walk(tests_abs):
		for fn in fnames:
			if not fn.endswith(".py"):
				continue
			path = os.path.join(root, fn)
			try:
				with open(path, "r", encoding="utf-8") as f:
					test_sources.append(f.read())
			except Exception:
				# ignore unreadable files
				continue

	def is_tested(relpath: str) -> bool:
		# Check by module name and by filename presence
		base = os.path.splitext(os.path.basename(relpath))[0]
		fname = os.path.basename(relpath)
		for src in test_sources:
			if base in src or fname in src:
				return True
		return False

	for f in files:
		if not is_tested(f):
			return f
	return None


def verify_coverage_for_files(files, threshold, test_root, repo_root: str | None = None):
	"""Verify per-file coverage using the `coverage` package.

	Returns None if all files meet the threshold, otherwise returns a
	string like "FAIL [file : current XX coverage under {threshold}%]" for
	the first failing file.
	"""
	if repo_root is None:
		repo_root = os.path.dirname(__file__)
	repo_root = os.path.abspath(repo_root)

	# Run tests under coverage
	if os.path.isabs(test_root):
		tests_abs = test_root
	else:
		tests_abs = os.path.normpath(os.path.join(repo_root, test_root))

	# Run coverage to execute tests
	run_cmd = [sys.executable, "-m", "coverage", "run", "-m", "pytest", tests_abs]
	subprocess.run(run_cmd, cwd=repo_root, check=False)

	# Run coverage report and capture output
	report = subprocess.run([sys.executable, "-m", "coverage", "report"], cwd=repo_root, capture_output=True, text=True)
	out = report.stdout

	# Parse report lines
	lines = out.splitlines()
	# Lines like: name                                   stmts   miss  cover
	for f in files:
		# default not found -> treat as 0
		found_pct = None
		for line in lines:
			line = line.strip()
			if not line or line.startswith("Name") or line.startswith("----") or line.startswith("TOTAL"):
				continue
			parts = line.split()
			if len(parts) < 4:
				continue
			fname = parts[0]
			pct_token = parts[-1]
			if pct_token.endswith('%'):
				try:
					pct = float(pct_token.rstrip('%'))
				except Exception:
					continue
			else:
				continue

			# match by normalized relative path
			norm_fname = os.path.normpath(fname)
			if norm_fname == os.path.normpath(f) or norm_fname.endswith(os.path.sep + os.path.normpath(f)) or norm_fname.endswith(f):
				found_pct = pct
				break

		if found_pct is None:
			# not found means 0% coverage
			return f"FAIL [{f} : current 0 coverage under {threshold}%]"
		if found_pct < threshold:
			return f"FAIL [{f} : current {int(found_pct)} coverage under {threshold}%]"

	return None


def main(argv=None) -> int:
	"""Main entry point for CLI.

	argv: list of arguments excluding program name. If None, uses sys.argv[1:].
	Returns an exit code (0 for success).
	"""
	if argv is None:
		argv = sys.argv[1:]

	if "--help" in argv:
		print_help()
		return 0
	# Parse --rules argument if present (support --rules=PATH or --rules PATH)
	rules_path = None
	for a in argv:
		if a.startswith("--rules="):
			rules_path = a.split("=", 1)[1]
			break
	if rules_path is None and "--rules" in argv:
		# value should be next arg
		try:
			idx = argv.index("--rules")
			rules_path = argv[idx + 1]
		except (ValueError, IndexError):
			print("--rules expects a path argument", file=sys.stderr)
			return 1

	# If no explicit rules path, try default location
	default = os.path.join(os.path.dirname(__file__), "validation_rules.json")
	if rules_path is None:
		if os.path.exists(default):
			rules_path = default
		else:
			print(
				f"Validation rules not provided and default {default} not found.",
				file=sys.stderr,
			)
			return 1

	# Try to open and parse the rules file
	import json

	try:
		with open(rules_path, "r", encoding="utf-8") as f:
			rules = json.load(f)
	except Exception as e:
		print(f"Failed to load rules from {rules_path}: {e}", file=sys.stderr)
		return 1

	# Validate rules structure
	language = rules.get("language")
	test_path = rules.get("test_path")
	if not language or not test_path:
		print(f"Rules file {rules_path} missing required keys 'language' or 'test_path'", file=sys.stderr)
		return 1

	# If user requested to run tests, ensure language is supported and run pytest
	# accept either --run-tests or --run_tests
	run_tests_flag = ("--run-tests" in argv) or ("--run_tests" in argv)

	if run_tests_flag:
		if language.lower() != "python":
			print(f"Only 'python' language supported for --run-tests (got '{language}')", file=sys.stderr)
			return 1

		# Resolve test path: absolute if starts with '/', else relative to repo root
		repo_root = os.path.dirname(__file__)
		if os.path.isabs(test_path):
			resolved = test_path
		else:
			resolved = os.path.normpath(os.path.join(repo_root, test_path))

		if not os.path.exists(resolved):
			print(f"Specified test path '{resolved}' does not exist", file=sys.stderr)
			return 1

		# Gather exclude paths from rules and list .py files while excluding them
		exclude_list = rules.get("exclude_paths_from_testing", []) or []
		files = list_files_with_extension("py", exclude_paths=exclude_list, repo_root=repo_root)

		# Print files (one per line)
		for f in files:
			print(f)

		# Check whether these files are covered by tests
		missing = check_files_tested(files, test_path, repo_root=repo_root)
		if missing is None:
			print("OK: all files appear to be tested")
			# If a coverage threshold is configured, verify per-file coverage
			threshold = rules.get("code_coverage_threshold")
			# Support per-file lower thresholds via 'low_treshold_files' (note: kept key name from rules)
			low_rules = rules.get("low_treshold_files") or {}
			low_filenames = set(low_rules.get("filenames") or [])
			low_threshold = low_rules.get("code_coverage_threshold")
			# Parse common threshold
			if threshold is not None:
				try:
					threshold_val = int(threshold)
				except Exception:
					threshold_val = None
			else:
				threshold_val = None

			# Split files into normal and low-threshold groups by basename match
			normal_files = []
			low_files = []
			for fpath in files:
				if os.path.basename(fpath) in low_filenames:
					low_files.append(fpath)
				else:
					normal_files.append(fpath)

			# Verify normal files against common threshold if configured
			if threshold_val is not None and normal_files:
				cov_fail = verify_coverage_for_files(normal_files, threshold_val, test_path, repo_root=repo_root)
				if cov_fail is not None:
					print(cov_fail, file=sys.stderr)
					return 1

			# Verify low-threshold files against their configured threshold
			if low_files and low_threshold is not None:
				try:
					low_threshold_val = int(low_threshold)
				except Exception:
					low_threshold_val = None
				if low_threshold_val is not None:
					cov_fail = verify_coverage_for_files(low_files, low_threshold_val, test_path, repo_root=repo_root)
					if cov_fail is not None:
						print(cov_fail, file=sys.stderr)
						return 1

			print(f"OK: all files meet coverage thresholds")
			return 0
			# no threshold configured or invalid -> success
			return 0
		else:
			print(f"FAIL: {missing} not tested", file=sys.stderr)
			return 1

	# No --run-tests: just report loaded rules
	print(f"Loaded rules from {rules_path}: language={language}, test_path={test_path}")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())

