#!/usr/bin/env python3
"""Integration test agent to build gcc_tester using TestRunner.

This script creates a temporary rules file (does not modify the repo's
.agent_rules.json), configures a TestRunner for the local `gcc_tester`
project, runs the build, prints the `_failed` state and exits non-zero
on failure.
"""
from pathlib import Path
import json
import sys
import traceback
import subprocess

# Ensure repository root is on sys.path so sibling package `agent` can be imported
repo_root = Path(__file__).resolve().parent.parent

# Import the TestRunner by loading the source file directly to avoid
# package-name conflicts with this script (which is named `agent.py`).
import importlib.util
import types

# Create a synthetic `agent` package in sys.modules so we can load the
# package modules by their full names (e.g. 'agent.rules_parser'). This
# avoids import-time confusion with this script being named `agent.py`.
agent_pkg = types.ModuleType("agent")
agent_pkg.__path__ = [str(repo_root / "agent")]
sys.modules["agent"] = agent_pkg

# Load agent.rules_parser
rules_mod_path = repo_root / "agent" / "rules_parser.py"
spec = importlib.util.spec_from_file_location("agent.rules_parser", str(rules_mod_path))
rules_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rules_mod)
sys.modules["agent.rules_parser"] = rules_mod

# Load agent.build_and_run_tests
build_mod_path = repo_root / "agent" / "build_and_run_tests.py"
spec = importlib.util.spec_from_file_location("agent.build_and_run_tests", str(build_mod_path))
build_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build_mod)
sys.modules["agent.build_and_run_tests"] = build_mod
TestRunner = build_mod.TestRunner

def get_gcc_tester_rules():
    return {
        "version": "0.1",
        "project_configurations": [
            {
                "project_type": "gcc_tester",
                "language": "C/C++",
                "build_system": "cmake",
                "testframework": {
                    "test_runner": {
                        "name": "ctest",
                        "command": "",
                        "execute_path": "gcc_tester",
                        "build_path": "gcc_tester/build"
                    },
                    "test_builder": {
                        "name": "gcc_builder",
                        "gcc_builder": True,
                        "command": "",
                        "compiler_flags": ["-DUNIT_TESTS=ON"],
                        "execute_path": "gcc_tester/build",
                        "build_path": "gcc_tester/build"
                    }
                }
            }
        ]
    }


def get_gcc_tester_test_failure_rules():
    return {
        "version": "0.1",
        "project_configurations": [
            {
                "project_type": "gcc_tester",
                "language": "C/C++",
                "build_system": "cmake",
                "testframework": {
                    "test_runner": {
                        "name": "ctest",
                        "command": "",
                        "execute_path": "gcc_tester/build",
                        "build_path": "gcc_tester/build"
                    },
                    "test_builder": {
                        "name": "gcc_builder",
                        "gcc_builder": True,
                        "command": "",
                        "compiler_flags": ["-DUNIT_TESTS=ON", "-DFAIL_TEST=ON"],
                        "execute_path": "gcc_tester",
                        "build_path": "gcc_tester/build"
                    }
                }
            }
        ]
    }

def get_gcc_tester_fail_build_rules():
    return {
        "version": "0.1",
        "project_configurations": [
            {
                "project_type": "gcc_tester",
                "language": "C/C++",
                "build_system": "cmake",
                "testframework": {
                    "test_runner": {
                        "name": "ctest",
                        "command": "",
                        "execute_path": "gcc_tester",
                        "build_path": "gcc_tester/build"
                    },
                    "test_builder": {
                        "name": "gcc_builder",
                        "gcc_builder": True,
                        "command": "",
                        "compiler_flags": ["-DUNIT_TESTS=ON", "-DFAIL_BUILD=ON"],
                        "execute_path": "gcc_tester/build",
                        "build_path": "gcc_tester/build"
                    }
                }
            }
        ]
    }

def get_test_runner_instance(rules: dict) -> TestRunner:
    #use rules to configure builder and runner for gcc_tester (paths are relative to repo root)
    builder_build_path = rules.get("project_configurations", [])[0].get("testframework", {}).get("test_builder", {}).get("build_path", "")
    builder_exec_path = rules.get("project_configurations", [])[0].get("testframework", {}).get("test_builder", {}).get("execute_path", "")
    builder_command = rules.get("project_configurations", [])[0].get("testframework", {}).get("test_builder", {}).get("command", "")
    tester_command = rules.get("project_configurations", [])[0].get("testframework", {}).get("test_runner", {}).get("command", "")
    tester_build_path = rules.get("project_configurations", [])[0].get("testframework", {}).get("test_runner", {}).get("build_path", "")
    tester_exec_path = rules.get("project_configurations", [])[0].get("testframework", {}).get("test_runner", {}).get("execute_path", "")
    use_gcc_builder = rules.get("project_configurations", [])[0].get("testframework", {}).get("test_builder", {}).get("gcc_builder", False)
    compiler_flags = rules.get("project_configurations", [])[0].get("testframework", {}).get("test_builder", {}).get("compiler_flags", [])
    tr = TestRunner(use_gcc_builder)
    tr.make_framework_entry(True, builder_command, builder_exec_path, builder_build_path, compiler_flags, use_gcc_builder)
    tr.make_framework_entry(False, tester_command, tester_exec_path, tester_build_path)
    return tr

def main():

    # Define scenarios
    class BuildScenario:
        name = "build"

        def __init__(self):
            self.rules = get_gcc_tester_rules()
            self.tr = get_test_runner_instance(self.rules)

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
            self.rules = get_gcc_tester_rules()
            self.tr = get_test_runner_instance(self.rules)

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
            self.rules = get_gcc_tester_fail_build_rules()
            self.tr = get_test_runner_instance(self.rules)

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
            self.rules = get_gcc_tester_test_failure_rules()
            self.tr = get_test_runner_instance(self.rules)

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

    scenarios = {
        "build": BuildScenario(),
        "test": TestScenario(),
        "fail-build": FailBuildScenario(),
        "fail-test": FailTestScenario(),
    }

    import argparse
    parser = argparse.ArgumentParser(description="Run integration test scenarios")
    parser.add_argument("--scenario", "-s", choices=list(scenarios.keys()) + ["all"], default="build", help="Scenario to run (default: build)")
    args = parser.parse_args()

    to_run = []
    failed = True
    if args.scenario == "all":
        to_run = list(scenarios.values())
    else:
        to_run = [scenarios[args.scenario]]

    for s in to_run:
        print(f"Running scenario: {s.name}")
        failed = s.run()

    if failed:
        print("Integration tests FAILED: TestRunner reports failure")
        sys.exit(2)
    else:
        print("Integration tests PASSED: TestRunner reports success")

if __name__ == "__main__":
    main()
