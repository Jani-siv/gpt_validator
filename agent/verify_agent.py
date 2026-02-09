
#!/usr/bin/env python3
"""Run verification steps in order.

This script runs the following, in sequence, stopping on the first failure:
 - verify_files.py
 - zephyr_unittest_allowed_includes.py

Both scripts are located in the same directory as this driver and are executed
with the same Python interpreter. If a step fails (non-zero exit code) the
driver prints the script's stdout/stderr and exits with that script's exit
code.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from rules_parser import RulesParser
from build_and_run_tests import TestRunner
from verify_files import VerifyFiles


def run_script(path: str) -> int:
	cmd = [sys.executable, path]
	proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
	if proc.stdout:
		print(proc.stdout, end='')
	return proc.returncode



def configure_test_runner(rp: RulesParser, tr: TestRunner, project_type: str) -> None:
	"""Configure a TestRunner instance `tr` using `rp` for `project_type`.

	This extracts the runner and builder configurations and calls
	`tr.make_framework_entry` for both.
	"""
	runner_cfg = rp.get_test_runner(project_type)
	builder_cfg = rp.get_test_builder(project_type)

	tr.make_framework_entry(
		False,
		runner_cfg.get("command", ""),
		runner_cfg.get("execute_path", ""),
		runner_cfg.get("build_path", runner_cfg.get("execute_path", "")),
	)

	tr.make_framework_entry(
		True,
		builder_cfg.get("command", ""),
		builder_cfg.get("execute_path", ""),
		builder_cfg.get("build_path", builder_cfg.get("execute_path", "")),
		builder_cfg.get("compiler_flags", []),
		builder_cfg.get("gcc_builder", True),
	)


def main() -> int:
	here = os.path.dirname(os.path.abspath(__file__))
	parser = argparse.ArgumentParser(description='Run verification steps and optionally build a unit test')
	parser.add_argument('--build', nargs='?', const='', metavar='PATH', help='Path (from zephyr_main_app) to unit test to build, e.g. unit_tests/parest')
	parser.add_argument('--run_test', nargs='?', const='', metavar='PATH', help='Path (from zephyr_main_app) to unit test to run, e.g. unit_tests/parest')
	parser.add_argument('--run_tests', dest='run_test', nargs='?', const='', metavar='PATH', help='Alias for --run_test')
	parser.add_argument('--project', metavar='NAME', help='Project type from .agent_rules.json (case-insensitive)')
	parser.add_argument('--rule_set', metavar='PATH', help='Path to .agent_rules.json (defaults to script directory)')
	args = parser.parse_args()
	
	# Verify args
	if args.project is None:
		print("Error: --project is required", file=sys.stderr)
		return 2
	else:
		args.project = args.project.strip().lower()
	
	# loading project specific configs
	rp = None
	if args.rule_set is None:
		try:
			rp = RulesParser(os.path.join(here, '.agent_rules.json'))
		except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
			print(f"Error: {exc}", file=sys.stderr)
			return 2
	else:
		try:
			rp = RulesParser(args.rule_set)
		except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
			print(f"Error: {exc}", file=sys.stderr)
			return 2

	# configure test runner with project-specific command and path
	tr = TestRunner()
	configure_test_runner(rp, tr, args.project)

	# Running verify_files class
	vf = VerifyFiles(rp, args.project).verify()
	if not vf.is_passed():
		print("File verification failed", file=sys.stderr)
		return 1
	# os.path.join(here, 'verify_files.py'),
	steps = [
		os.path.join(here, 'zephyr_cmakelists_checker.py'),
		os.path.join(here, 'zephyr_mock_link_audit.py'),
		os.path.join(here, 'zephyr_unittest_file_checker.py'),
	]

	#running scripts
	for script in steps:
		if not os.path.isfile(script):
			print(f"Error: script not found: {script}", file=sys.stderr)
			return 2

		code = run_script(script)
		if code != 0:
			print(f"Stopped: {os.path.basename(script)} exited with code {code}", file=sys.stderr)
			return code

	# If requested, run build step after successful checks
	if args.build is not None:
		tr.make_build()
		if tr._failed:
			# Build failed no reason to attempt running tests
			sys.exit(1)
		
	if args.run_test is not None:
		tr.make_testrun()
		if tr._failed:
			# Test run failed no reason to attempt coverage check
			sys.exit(1)

	print('All checks passed')
	return 0


if __name__ == '__main__':
	main()
