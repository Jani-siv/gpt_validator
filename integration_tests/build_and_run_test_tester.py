# This test suite test how two or more classes behaves together. All configurations mimic real-world use cases
# Current classes unde test are:
# gpt_validator/agent/build_and_run_tests.py and this uses rules_parser.py to parse rules and build the builder and runner configurations
# The test scenarios are defined in the main function and include:

import sys
import traceback
from pathlib import Path

# Ensure repository root is on sys.path so sibling package imports work
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.build_and_run_tests import TestRunner




_SCENARIO_CONFIGS = {
    "build": {
        "version": "0.1",
        "project_configurations": [
            {
                "scenario": "build",
                "language": "C/C++",
                "build_system": "cmake",
                "testframework": {
                    "test_runner": {
                        "name": "ctest",
                        "command": "",
                        "execute_path": "gcc_tester/build",
                        "build_path": "gcc_tester/build",
                    },
                    "test_builder": {
                        "name": "gcc_builder",
                        "gcc_builder": True,
                        "command": "",
                        "compiler_flags": ["-DUNIT_TESTS=ON"],
                        "execute_path": "gcc_tester",
                        "build_path": "gcc_tester/build",
                    },
                },
            }
        ],
    },
    "test": {
        "version": "0.1",
        "project_configurations": [
            {
                "scenario": "test",
                "language": "C/C++",
                "build_system": "cmake",
                "testframework": {
                    "test_runner": {
                        "name": "ctest",
                        "command": "",
                        "execute_path": "gcc_tester/build",
                        "build_path": "gcc_tester/build",
                    },
                    "test_builder": {
                        "name": "gcc_builder",
                        "gcc_builder": True,
                        "command": "",
                        "compiler_flags": ["-DUNIT_TESTS=ON"],
                        "execute_path": "gcc_tester",
                        "build_path": "gcc_tester/build",
                    },
                },
            }
        ],
    },
    "fail-test": {
        "version": "0.1",
        "project_configurations": [
            {
                "scenario": "fail-test",
                "language": "C/C++",
                "build_system": "cmake",
                "testframework": {
                    "test_runner": {
                        "name": "ctest",
                        "command": "",
                        "execute_path": "gcc_tester/build",
                        "build_path": "gcc_tester/build",
                    },
                    "test_builder": {
                        "name": "gcc_builder",
                        "gcc_builder": True,
                        "command": "",
                        "compiler_flags": ["-DUNIT_TESTS=ON", "-DFAIL_TEST=ON"],
                        "execute_path": "gcc_tester",
                        "build_path": "gcc_tester/build",
                    },
                },
            }
        ],
    },
    "fail-build": {
        "version": "0.1",
        "project_configurations": [
            {
                "scenario": "fail-build",
                "language": "C/C++",
                "build_system": "cmake",
                "testframework": {
                    "test_runner": {
                        "name": "ctest",
                        "command": "",
                        "execute_path": "gcc_tester",
                        "build_path": "gcc_tester/build",
                    },
                    "test_builder": {
                        "name": "gcc_builder",
                        "gcc_builder": True,
                        "command": "",
                        "compiler_flags": ["-DUNIT_TESTS=ON", "-DFAIL_BUILD=ON"],
                        "execute_path": "gcc_tester/build",
                        "build_path": "gcc_tester/build",
                    },
                },
            }
        ],
    },
    "pass-custom-build": {
        "version": "0.1",
        "project_configurations": [
            {
                "scenario": "pass-custom-build",
                "language": "python",
                "build_system": "custom",
                "testframework": {
                    "test_runner": {
                        "name": "ctest",
                        "command": "",
                        "execute_path": "custom_builder",
                        "build_path": "custom_builder/build",
                    },
                    "test_builder": {
                        "name": "py-builder",
                        "gcc_builder": False,
                        "command": "python3 current_dir_builder.py",
                        "compiler_flags": [],
                        "execute_path": "custom_builder",
                        "build_path": "custom_builder/build",
                    },
                },
            }
        ],
    },
    "fail-custom-build": {
        "version": "0.1",
        "project_configurations": [
            {
                "scenario": "fail-custom-build",
                "language": "python",
                "build_system": "custom",
                "testframework": {
                    "test_runner": {
                        "name": "ctest",
                        "command": "",
                        "execute_path": "custom_builder",
                        "build_path": "custom_builder/build",
                    },
                    "test_builder": {
                        "name": "py-builder",
                        "gcc_builder": False,
                        "command": "python3 custom_builder/current_dir_builder.py",
                        "compiler_flags": [],
                        "execute_path": ".",
                        "build_path": "custom_builder/build",
                    },
                },
            }
        ],
    },
}


def get_test_runner_instance(scenario: str) -> TestRunner:
    """Create a `TestRunner` for the named scenario.

    The function looks up the scenario configuration from `_SCENARIO_CONFIGS`
    and mirrors the previous behaviour when constructing the `TestRunner`.
    """
    rules = _SCENARIO_CONFIGS.get(scenario)
    if not rules:
        raise KeyError(f"Unknown scenario: {scenario}")

    # use rules to configure builder and runner for gcc_tester (paths are relative to repo root)
    pc = rules.get("project_configurations", [])[0].get("testframework", {})
    builder_build_path = pc.get("test_builder", {}).get("build_path", "")
    builder_exec_path = pc.get("test_builder", {}).get("execute_path", "")
    builder_command = pc.get("test_builder", {}).get("command", "")
    tester_command = pc.get("test_runner", {}).get("command", "")
    tester_build_path = pc.get("test_runner", {}).get("build_path", "")
    tester_exec_path = pc.get("test_runner", {}).get("execute_path", "")
    use_gcc_builder = pc.get("test_builder", {}).get("gcc_builder", False)
    compiler_flags = pc.get("test_builder", {}).get("compiler_flags", [])

    tr = TestRunner(use_gcc_builder)
    tr.make_framework_entry(True, builder_command, builder_exec_path, builder_build_path, compiler_flags, use_gcc_builder)
    tr.make_framework_entry(False, tester_command, tester_exec_path, tester_build_path)
    return tr

def main():

    # Define scenarios
    class BuildScenario:
        name = "build"

        def __init__(self):
            self.tr = get_test_runner_instance("build")

        def run(self):
            # Prefer TestRunner.make_build if present
            if hasattr(self.tr, "make_build"):
                try:
                    self.tr.make_build()
                except Exception:
                    traceback.print_exc()
            if hasattr(self.tr, "_failed"):
                if self.tr._failed == False:
                    print("TestRunner reports success as expected")
                    return False
                else:
                    print("TestRunner did not report success when expected")
                    return True
            return True  # if we can't determine failure, return True to indicate failure by default


    class TestScenario:
        name = "test"

        def __init__(self):
            self.tr = get_test_runner_instance("test")

        def run(self) -> bool:
            # Prefer TestRunner.make_testrun it handle build and ctest automatically
            try:
                if hasattr(self.tr, "make_testrun"):
                    self.tr.make_testrun()
            except Exception:
                traceback.print_exc()

            if hasattr(self.tr, "_failed"):
                if self.tr._failed == False:
                    print("TestRunner reports success as expected")
                    return False
                else:
                    print("TestRunner did not report success when expected")
                    return True
            return True  # if we can't determine failure, return True to indicate failure by default



    class FailBuildScenario:
        name = "fail-build"

        def __init__(self):
            self.tr = get_test_runner_instance("fail-build")

        def run(self) -> bool:
            # Prefer TestRunner.make_build if present
            if hasattr(self.tr, "make_build"):
                try:
                    self.tr.make_build()
                except Exception:
                    traceback.print_exc()
                    # try to mark failure if available
            if hasattr(self.tr, "_failed"):
                if self.tr._failed == True:
                    print("TestRunner reports failure as expected")
                    return False
                else:
                    print("TestRunner did not report failure when expected")
                    return True
            return True  # if we can't determine failure, return True to indicate failure by default



    class FailTestScenario:
        name = "fail-test"

        def __init__(self):
            self.tr = get_test_runner_instance("fail-test")

        def run(self) -> bool:
            # Prefer TestRunner.make_testrun it handle build and ctest automatically
            try:
                if hasattr(self.tr, "make_testrun"):
                    self.tr.make_testrun()
            except Exception:
                traceback.print_exc()
            if hasattr(self.tr, "_failed"):
                if self.tr._failed == True:
                    print("TestRunner reports failure as expected")
                    return False
                else:
                    print("TestRunner did not report failure when expected")
                    return True
            return True  # if we can't determine failure, return True to indicate failure by default


    class PassCustomBuildScenario:
        name = "pass-custom-build"

        def __init__(self):
            self.tr = get_test_runner_instance("pass-custom-build")

        def run(self) -> bool:
            # Prefer TestRunner.make_build if present
            if hasattr(self.tr, "make_build"):
                try:
                    self.tr.make_build()
                except Exception:
                    traceback.print_exc()
            if hasattr(self.tr, "_failed"):
                if self.tr._failed == False:
                    print("TestRunner reports success as expected")
                    return False
                else:
                    print("TestRunner did not report success when expected")
                    return True
            return True  # if we can't determine failure, return True to indicate failure by default


    class FailCustomBuildScenario:
        name = "fail-custom-build"

        def __init__(self):
            self.tr = get_test_runner_instance("fail-custom-build")

        def run(self) -> bool:
            # Prefer TestRunner.make_build if present
            if hasattr(self.tr, "make_build"):
                try:
                    self.tr.make_build()
                except Exception:
                    traceback.print_exc()
            if hasattr(self.tr, "_failed"):
                if self.tr._failed == True:
                    print("TestRunner reports failure as expected")
                    return False
                else:
                    print("TestRunner did not report failure when expected")
                    return True
            return True  # if we can't determine failure, return True to indicate failure by default

    scenarios = {
        "build": BuildScenario(),
        "test": TestScenario(),
        "fail-build": FailBuildScenario(),
        "fail-test": FailTestScenario(),
        "pass-custom-build": PassCustomBuildScenario(),
        "fail-custom-build": FailCustomBuildScenario(),
    }

    import argparse
    import io
    import contextlib

    parser = argparse.ArgumentParser(description="Run integration test scenarios")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--builder-tests", action="store_true", help="Run all build-only scenarios")
    group.add_argument("--test-runner-tests", action="store_true", help="Run all test-runner scenarios")
    group.add_argument("--all", action="store_true", help="Run all scenarios")
    args = parser.parse_args()

    builder_keys = ["build", "fail-build", "pass-custom-build", "fail-custom-build"]
    test_keys = ["test", "fail-test"]

    if not (args.builder_tests or args.test_runner_tests or args.all):
        print("Usage: python3 integration_tests/build_and_run_test_tester.py [--builder-tests | --test-runner-tests | --all]")
        print("Examples:")
        print("  --builder-tests       Run building scenarios only and print PASS/FAIL")
        print("  --test-runner-tests   Run test-runner scenarios only and print PASS/FAIL")
        print("  --all                Run all scenarios")
        return

    to_run = []
    if args.all:
        to_run = list(scenarios.values())
    elif args.builder_tests:
        to_run = [scenarios[k] for k in builder_keys if k in scenarios]
    elif args.test_runner_tests:
        to_run = [scenarios[k] for k in test_keys if k in scenarios]

    # Run each scenario but suppress internal output; only print PASS/FAIL per scenario.
    for s in to_run:
        # capture stdout/stderr emitted by scenario and its TestRunner calls
        buf_out = io.StringIO()
        buf_err = io.StringIO()
        print(f"Running scenario: {s.name}")
        with contextlib.redirect_stdout(buf_out), contextlib.redirect_stderr(buf_err):
            # Monkeypatch TestRunner.run on the instance to force subprocess output capture
            tr_run_orig = None
            try:
                if hasattr(s, "tr") and hasattr(s.tr, "run"):
                    tr_run_orig = s.tr.run

                    def _run_capture(cmd, cwd=None, capture_output=False):
                        # Force capture_output=True so subprocess output doesn't leak to terminal
                        return tr_run_orig(cmd, cwd=cwd, capture_output=True)

                    s.tr.run = _run_capture

                try:
                    result = s.run()
                except SystemExit:
                    raise
                except Exception:
                    traceback.print_exc()
                    result = True
            finally:
                # Restore original run method if we replaced it
                if tr_run_orig is not None:
                    s.tr.run = tr_run_orig

        # result == False means success (keeps previous semantics), True means failure
        if result:
            print(f"FAIL: {s.name}")
            # Print captured stderr and stdout to aid debugging
            err_text = buf_err.getvalue().strip()
            out_text = buf_out.getvalue().strip()
            if err_text:
                print("--- stderr ---")
                print(err_text)
                print("--- end stderr ---")
            if out_text:
                print("--- stdout ---")
                print(out_text)
                print("--- end stdout ---")
            sys.exit(1)
        else:
            print(f"PASS: {s.name}")

if __name__ == "__main__":
    main()
