
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
import shlex
import subprocess
import sys
from rules_parser import RulesParser
from build_and_run_tests import TestRunner


def run_script(path: str) -> int:
	cmd = [sys.executable, path]
	proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
	if proc.stdout:
		print(proc.stdout, end='')
	return proc.returncode


# project config loading is handled by RulesParser


def build_command(command: str, extra_args: list[str], base_dir: str, cwd: str) -> list[str]:
	cmd = shlex.split(command)
	if not cmd:
		raise ValueError('Empty command in project configuration')
	if cmd[0] in {'python', 'python3'}:
		cmd[0] = sys.executable
		if len(cmd) > 1 and not os.path.isabs(cmd[1]):
			candidate = os.path.normpath(os.path.join(cwd, cmd[1]))
			if os.path.isfile(candidate):
				cmd[1] = candidate
			else:
				cmd[1] = os.path.normpath(os.path.join(base_dir, cmd[1]))
		return cmd + extra_args
	if cmd[0].endswith('.py'):
		script_path = cmd[0]
		if not os.path.isabs(script_path):
			candidate = os.path.normpath(os.path.join(cwd, script_path))
			if os.path.isfile(candidate):
				script_path = candidate
			else:
				script_path = os.path.normpath(os.path.join(base_dir, script_path))
		return [sys.executable, script_path] + cmd[1:] + extra_args
	return cmd + extra_args


def normalize_keys(mapping: dict) -> dict:
	if not isinstance(mapping, dict):
		return {}
	return {str(key).strip().lower(): value for key, value in mapping.items()}


def read_test_framework(project_config: dict) -> dict:
	normalized = normalize_keys(project_config)
	for key in ('testframework', 'test_framework', 'testframeworks', 'test_frameworks'):
		value = normalized.get(key)
		if isinstance(value, dict):
			return value
	return {}


def extract_command_and_path(container: dict, prefix: str) -> tuple[str | None, str | None]:
	normalized = normalize_keys(container)
	command = normalized.get('command') or normalized.get(f'{prefix}_command')
	execute_path = (
		normalized.get('execute_path')
		or normalized.get('executepath')
		or normalized.get('execute-path')
		or normalized.get(f'{prefix}_execute_path')
		or normalized.get(f'{prefix}_execute-path')
	)
	return command, execute_path


def normalize_zephyr_command(command: str, mode: str, project_type: str) -> str:
	if project_type != 'zephyr':
		return command
	parts = shlex.split(command)
	if not any(part.endswith('run_tests.py') for part in parts):
		return command

	updated = []
	for part in parts:
		if mode == 'run' and part == '--run_test':
			continue
		if mode == 'build' and part == '--build':
			updated.append('--build-only')
			continue
		updated.append(part)

	return ' '.join(shlex.quote(part) for part in updated)


def perform_build(here: str, build_path: str | None, project_config: dict) -> int:
	project_type = str(project_config.get('project_type', '')).lower() if project_config else ''
	testframework = read_test_framework(project_config)
	builder = {}
	if isinstance(testframework, dict):
		normalized_framework = normalize_keys(testframework)
		builder = normalized_framework.get('test_builder') or normalized_framework.get('testbuilder') or normalized_framework.get('builder') or {}
	if not isinstance(builder, dict):
		builder = {}
	command, execute_path = extract_command_and_path(builder, 'test_builder')
	if not command or not execute_path:
		fallback_command, fallback_path = extract_command_and_path(testframework, 'test_builder')
		command = command or fallback_command
		execute_path = execute_path or fallback_path
	if not command or not execute_path:
		normalized_project = normalize_keys(project_config)
		top_level = normalized_project.get('test_builder') if isinstance(normalized_project.get('test_builder'), dict) else {}
		fallback_command, fallback_path = extract_command_and_path(top_level, 'test_builder')
		command = command or fallback_command
		execute_path = execute_path or fallback_path
	if not command or not execute_path:
		print("Error: test_builder configuration missing command or execute_path", file=sys.stderr)
		return 2

	repo_root = os.path.abspath(os.path.join(here, '..', '..', '..'))
	cwd = execute_path if os.path.isabs(execute_path) else os.path.join(repo_root, execute_path)
	command = normalize_zephyr_command(command, 'build', project_type)
	extra_args = [build_path] if build_path else []
	cmd = build_command(command, extra_args, here, cwd)
	print(f"Running build: cd {cwd} && {' '.join(cmd)}")
	proc = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
	if proc.stdout:
		print(proc.stdout, end='')
	if proc.returncode != 0:
		return 1
	print("OK: Build succeeded.")
	return 0


def perform_run_test(here: str, test_path: str | None, project_config: dict) -> int:
	project_type = str(project_config.get('project_type', '')).lower() if project_config else ''
	testframework = read_test_framework(project_config)
	runner = {}
	if isinstance(testframework, dict):
		normalized_framework = normalize_keys(testframework)
		runner = normalized_framework.get('test_runner') or normalized_framework.get('testrunner') or normalized_framework.get('runner') or {}
	if not isinstance(runner, dict):
		runner = {}
	command, execute_path = extract_command_and_path(runner, 'test_runner')
	if not command or not execute_path:
		fallback_command, fallback_path = extract_command_and_path(testframework, 'test_runner')
		command = command or fallback_command
		execute_path = execute_path or fallback_path
	if not command or not execute_path:
		normalized_project = normalize_keys(project_config)
		top_level = normalized_project.get('test_runner') if isinstance(normalized_project.get('test_runner'), dict) else {}
		fallback_command, fallback_path = extract_command_and_path(top_level, 'test_runner')
		command = command or fallback_command
		execute_path = execute_path or fallback_path
	if not command or not execute_path:
		print("Error: test_runner configuration missing command or execute_path", file=sys.stderr)
		return 2

	repo_root = os.path.abspath(os.path.join(here, '..', '..', '..'))
	cwd = execute_path if os.path.isabs(execute_path) else os.path.join(repo_root, execute_path)
	command = normalize_zephyr_command(command, 'run', project_type)
	extra_args = [test_path] if test_path else []
	cmd = build_command(command, extra_args, here, cwd)
	print(f"Running tests: cd {cwd} && {' '.join(cmd)}")
	proc = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
	if proc.stdout:
		print(proc.stdout, end='')
	if proc.returncode != 0:
		return 1
	if project_type == 'zephyr':
		verifier = os.path.join(here, 'zephyr_verify_coverage.py')
		print(f"Running coverage check: {verifier}")
		code = run_script(verifier)
		if code != 0:
			print(f"Stopped: {os.path.basename(verifier)} exited with code {code}", file=sys.stderr)
			return code
	print("OK: Build succeeded. All tests passed.")
	return 0


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
	project_config = None
	if args.rule_set is None:
		try:
			rp = RulesParser(os.path.join(here, '.agent_rules.json'))
			project_config = rp.load_project_config(args.project)
		except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
			print(f"Error: {exc}", file=sys.stderr)
			return 2
	else:
		try:
			rp = RulesParser(args.rule_set)
			project_config = rp.load_project_config(args.project)
		except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
			print(f"Error: {exc}", file=sys.stderr)
			return 2

	# configure test runner with project-specific command and path
	tr = TestRunner()
	configure_test_runner(rp, tr, args.project)
	
	steps = [
		os.path.join(here, 'verify_files.py'),
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
