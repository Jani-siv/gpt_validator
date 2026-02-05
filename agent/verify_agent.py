
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
import os
import subprocess
import sys


def run_script(path: str) -> int:
	cmd = [sys.executable, path]
	proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
	if proc.stdout:
		print(proc.stdout, end='')
	return proc.returncode


def main() -> int:
	here = os.path.dirname(os.path.abspath(__file__))
	parser = argparse.ArgumentParser(description='Run verification steps and optionally build a unit test')
	parser.add_argument('--build', metavar='PATH', help='Path (from zephyr_main_app) to unit test to build, e.g. unit_tests/parest')
	parser.add_argument('--run_tests', metavar='PATH', help='Path (from zephyr_main_app) to unit test to build, e.g. unit_tests/parest')
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

	# If requested, run build step after successful checks
	if args.build:
		# run_tests.py is located in the parent directory of this script (ztests)
		ztests_dir = os.path.abspath(os.path.join(here, '..'))
		build_path = args.build
		cmd = [sys.executable, 'run_tests.py', build_path, '-b']
		print(f"Running build: cd {ztests_dir} && {sys.executable} run_tests.py {build_path} -b")
		proc = subprocess.run(cmd, cwd=ztests_dir, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
		# check from output that it contains following line: Build succeeded.
		if "Build succeeded." not in proc.stdout:
			print(proc.stdout, end='')
			return 1
		else:
			print("OK: Build succeeded.")
		

	# If requested, run test step after successful checks
	if args.run_tests:
		# run_tests.py is located in the parent directory of this script (ztests)
		ztests_dir = os.path.abspath(os.path.join(here, '..'))
		test_path = args.run_tests
		cmd = [sys.executable, 'run_tests.py', test_path]
		print(f"Running tests: cd {ztests_dir} && {sys.executable} run_tests.py {test_path}")
		proc = subprocess.run(cmd, cwd=ztests_dir, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
		# check that output do not contain any Status: FAIL
		if "All builds succeeded." not in proc.stdout:
			print(proc.stdout, end='')
			print("FAIL: Tests could not be run due to build failure.")
			print("hint: Use --build to build the test first.")
			print("zephyr_main_app/ztests/reports/runtime_error.log may contain more details.")
			return 1
		if "Status: FAIL" in proc.stdout:
			print(proc.stdout, end='')
			print("FAIL:Some tests failed.")
			return 1
		else:
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
