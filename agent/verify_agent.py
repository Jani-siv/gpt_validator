
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


def run_script(path: str) -> int:
	cmd = [sys.executable, path]
	proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
	if proc.stdout:
		print(proc.stdout, end='')
	return proc.returncode


def load_project_config(here: str, project_type: str | None) -> dict:
	rules_path = os.path.join(here, '.agent_rules.json')
	if not os.path.isfile(rules_path):
		raise FileNotFoundError(f"Missing rules file: {rules_path}")

	with open(rules_path, 'r', encoding='utf-8') as handle:
		rules = json.load(handle)

	projects = rules.get('project_configurations', [])
	if not projects:
		raise ValueError('No project_configurations found in .agent_rules.json')

	if isinstance(projects, dict):
		if 'project_type' in projects:
			project_entries = [projects]
		else:
			project_entries = []
			for key, value in projects.items():
				if isinstance(value, dict):
					entry = dict(value)
					entry.setdefault('project_type', key)
					project_entries.append(entry)
	elif isinstance(projects, list):
		project_entries = [p for p in projects if isinstance(p, dict)]
	else:
		project_entries = []
	if not project_entries:
		raise ValueError('project_configurations must contain objects with project_type')

	if project_type is None:
		if len(project_entries) == 1:
			return project_entries[0]
		raise ValueError('Multiple project_configurations found; use --project to select one')

	project_key = project_type.lower()
	for project in project_entries:
		candidate = str(project.get('project_type', '')).lower()
		if candidate == project_key:
			return project

	available = ', '.join(sorted({str(p.get('project_type', '')).lower() for p in project_entries if p.get('project_type')}))
	raise ValueError(f"Unknown project type '{project_type}'. Available: {available}")


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


def main() -> int:
	here = os.path.dirname(os.path.abspath(__file__))
	parser = argparse.ArgumentParser(description='Run verification steps and optionally build a unit test')
	parser.add_argument('--build', nargs='?', const='', metavar='PATH', help='Path (from zephyr_main_app) to unit test to build, e.g. unit_tests/parest')
	parser.add_argument('--run_test', nargs='?', const='', metavar='PATH', help='Path (from zephyr_main_app) to unit test to run, e.g. unit_tests/parest')
	parser.add_argument('--run_tests', dest='run_test', nargs='?', const='', metavar='PATH', help='Alias for --run_test')
	parser.add_argument('--project', metavar='NAME', help='Project type from .agent_rules.json (case-insensitive)')
	args = parser.parse_args()

	steps = [
		os.path.join(here, 'verify_files.py'),
		os.path.join(here, 'zephyr_cmakelists_checker.py'),
		os.path.join(here, 'zephyr_mock_link_audit.py'),
		os.path.join(here, 'zephyr_unittest_file_checker.py'),
	]

	for script in steps:
		if not os.path.isfile(script):
			print(f"Error: script not found: {script}", file=sys.stderr)
			return 2

		code = run_script(script)
		if code != 0:
			print(f"Stopped: {os.path.basename(script)} exited with code {code}", file=sys.stderr)
			return code

	project_config = None
	if args.build is not None or args.run_test is not None:
		try:
			project_config = load_project_config(here, args.project)
		except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
			print(f"Error: {exc}", file=sys.stderr)
			return 2

	# If requested, run build step after successful checks
	if args.build is not None:
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
		build_path = args.build
		extra_args = [build_path] if build_path else []
		cmd = build_command(command, extra_args, here, cwd)
		print(f"Running build: cd {cwd} && {' '.join(cmd)}")
		proc = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
		if proc.stdout:
			print(proc.stdout, end='')
		if proc.returncode != 0:
			return 1
		print("OK: Build succeeded.")
		

	# If requested, run test step after successful checks
	if args.run_test is not None:
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
		test_path = args.run_test
		extra_args = [test_path] if test_path else []
		cmd = build_command(command, extra_args, here, cwd)
		print(f"Running tests: cd {cwd} && {' '.join(cmd)}")
		proc = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
		if proc.stdout:
			print(proc.stdout, end='')
		if proc.returncode != 0:
			return 1
		project_type = str(project_config.get('project_type', '')).lower() if project_config else ''
		if project_type == 'zephyr':
			# Tests passed - run coverage verifier script located next to this driver.
			verifier = os.path.join(here, 'zephyr_verify_coverage.py')
			print(f"Running coverage check: {verifier}")
			code = run_script(verifier)
			if code != 0:
				print(f"Stopped: {os.path.basename(verifier)} exited with code {code}", file=sys.stderr)
				return code
		print("OK: Build succeeded. All tests passed.")


	print('All checks passed')
	return 0


if __name__ == '__main__':
	raise SystemExit(main())
