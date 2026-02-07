#!/usr/bin/env python3
"""
build_and_run_tests.py

Reads .agent_rules.json to determine where to start building and
performs a clean CMake build for unit and integration tests.

Usage: python build_and_run_tests.py [--project-type dti_tools] [--rules path/to/.agent_rules.json]
"""
import argparse
import json
import multiprocessing
import os
import shutil
import subprocess
from pathlib import Path
import sys
from agent.rules_parser import RulesParser


def git_repo_root(cwd: Path | str | None = None) -> Path | None:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=cwd,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        return Path(out).resolve()
    except subprocess.CalledProcessError:
        return None

class TestRunner:
    def __init__(self, use_host_compiler: bool = True):
        self.script_dir = Path(__file__).parent
        self.repo_root = git_repo_root(self.script_dir)
        self.use_gcc_builder = False
        self.builder = { "command": "", "execute_path": Path, "build_path": Path , "compiler_flags": [] }
        self.runner = { "command": "", "execute_path": Path, "build_path": Path }
        self.env = build_env(use_host_compiler)
        self.cores = self.get_cores(8)
        self._failed = False

    def make_framework_entry(self, is_builder: bool, command: str, execute_path: str, build_path: str, compiler_flags: list[str] | None = None) -> dict:
        # Validate inputs
        if not isinstance(is_builder, bool):
            raise TypeError("is_builder must be a boolean")
        if not command:
            self.use_gcc_builder = True
        if not execute_path:
            raise ValueError("execute_path must be provided and non-empty")
        # If build_path is not provided, fall back to execute_path only for runner
        if not build_path:
            if not is_builder:
                build_path = execute_path
            else:
                raise ValueError("build_path must be provided and non-empty")

        if is_builder:
            self.builder = {
                "command": command,
                "execute_path": self.repo_root / execute_path,
                "build_path": self.repo_root / build_path,
                "compiler_flags": compiler_flags or []}
        else:
            self.runner = {
                "command": command,
                "execute_path": self.repo_root / execute_path,
                "build_path": self.repo_root / build_path}
    
    def clean_build_dirs(self, build_dir: Path):
        if build_dir.exists():
            shutil.rmtree(build_dir)
        build_dir.mkdir(parents=True, exist_ok=True)

    def gcc_builder(self, compiling_flags: list[str]):
        try:
            self.run(["cmake", "-DCMAKE_CXX_COMPILER=g++", compiling_flags, str(self.builder["build_path"])], cwd=self.builder["execute_path"])
            self.run(["make", f"-j{self.cores}"], cwd=self.builder["build_path"])
            print("OK: build success")
        except subprocess.CalledProcessError as e:
            print(f"FAIL: build failed ({e})")

    def make_build(self):
        self.clean_build_dirs(self.builder["build_path"])
        if self.use_gcc_builder:
            self.gcc_builder([])

    def make_testrun(self):
        self.make_build()
        if self.use_gcc_builder:
            ret_code, result = self.run_ctest_tests()
            if ret_code != 0:
                failures = self.parse_ctest_failures(result)
                log_path = (self.runner["build_path"] / "Testing" / "Temporary" / "LastTest.log").resolve()
                if failures:
                    print("FAIL: tests failed")
                    print("Failed tests:")
                    for name in failures:
                        print(f"- {name}")
                else:
                    print("FAIL: tests failed (unable to list failing tests from ctest output)")
                print(f"Logs: {log_path}")
                # mark failure for higher-level caller to act on
                self._failed = True
            else:
                print("OK: tests success")

    def has_failed(self) -> bool:
        return bool(self._failed)
            

    def run_ctest_tests(self):
        result = self.run(["ctest", "--output-on-failure"], cwd=self.runner["execute_path"], capture_output=True)
        return result.returncode, result.stdout
    
    def run(self, cmd, cwd=None, capture_output=False):
        print(f"+ Running: {' '.join(cmd)} (cwd={cwd})")
        if capture_output:
            return subprocess.run(cmd, cwd=cwd, env=self.env, text=True, capture_output=True)
        subprocess.run(cmd, cwd=cwd, check=True, env=self.env)
        return None

    def parse_ctest_failures(self, output: str):
        failures = []
        capture = False
        for line in output.splitlines():
            if line.startswith("The following tests FAILED:"):
                capture = True
                continue
            if capture:
                stripped = line.strip()
                if not stripped:
                    break
                # Expected format: "<index> - <name> (<time>)"
                if "-" in stripped:
                    parts = stripped.split("-", 1)
                    if len(parts) == 2:
                        failures.append(parts[1].strip().split(" ")[0])
        return failures
    
    def get_cores(self, max_allowed: int | None) -> int:
        """Return number of CPU cores limited by max_allowed.

        If max_allowed is None or not a positive int, return detected cores.
        Otherwise return min(detected_cores, max_allowed).
        """
        detected = multiprocessing.cpu_count()
        if max_allowed is None:
            return detected
        try:
            allowed = int(max_allowed)
        except Exception:
            return detected
        if allowed <= 0:
            return detected
        return allowed if allowed < detected else detected


def build_env(use_host_compiler: bool):
    if not use_host_compiler:
        return None

    env = os.environ.copy()
    # Remove Yocto/SDK environment variables so CMake does not default to a target toolchain.
    for key in [
        "CMAKE_TOOLCHAIN_FILE",
        "OECORE_NATIVE_SYSROOT",
        "OECORE_TARGET_SYSROOT",
        "OECORE_BASELIB",
        "OECORE_TARGET_ARCH",
        "OECORE_TARGET_OS",
        "OECORE_TARGET_BITS",
        "OECORE_TARGET_ENDIANNESS",
        "OECORE_TARGET_FPU",
        "OECORE_SDK_VERSION",
        "OECORE_DISTRO_VERSION",
        "OECORE_ENV_VERSION",
        "SDKTARGETSYSROOT",
        "PKG_CONFIG_SYSROOT_DIR",
        "PKG_CONFIG_PATH",
        "PKG_CONFIG_LIBDIR",
    ]:
        env.pop(key, None)

    env.update(
        {
            "CC": "/usr/bin/gcc",
            "CXX": "/usr/bin/g++",
            "AR": "/usr/bin/ar",
            "RANLIB": "/usr/bin/ranlib",
            "STRIP": "/usr/bin/strip",
            "NM": "/usr/bin/nm",
            "OBJCOPY": "/usr/bin/objcopy",
            "OBJDUMP": "/usr/bin/objdump",
        }
    )
    return env

def main():
    p = argparse.ArgumentParser(description="Build and run tests using .agent_rules.json rules")
    p.add_argument("--project-type", default="dti_tools", help="project_type to use from .agent_rules.json")
    p.add_argument("--rules", default=None, help="path to .agent_rules.json (defaults to script dir)")
    p.add_argument("--build", action="store_true", help="only perform the build step")
    p.add_argument("--build-only", dest="build", action="store_true", help="alias for --build")
    p.add_argument("--run_tests", action="store_true", help="only run tests (ctest)")
    p.add_argument("--use_sdk", action="store_false", dest="sdk_compiler", help="use SDK toolchain instead of host compiler (default: use host compiler)")
    args = p.parse_args()
    script_dir = Path(__file__).parent
    rules_path = Path(args.rules) if args.rules else script_dir / ".agent_rules.json"
    if not rules_path.exists():
        print(f"ERROR: rules file not found: {rules_path}")
        sys.exit(2)
    # action selection running tests will build also tests, maybe optimize in the future
    do_build = args.build or args.run_tests or (not args.build and not args.run_tests)
    do_test = args.run_tests or (not args.build and not args.run_tests)
    # Compiler selection possible production build in the future?
    host_compiler = not args.sdk_compiler
    # Create test runner
    testRunner = TestRunner(host_compiler)
    # Get rule set
    rules_Parser = RulesParser(rules_path)
    runner_cfg = rules_Parser.get_test_runner(args.project_type)
    builder_cfg = rules_Parser.get_test_builder(args.project_type) or {}
    # If no configuration found fail with error
    if not runner_cfg or not builder_cfg:
        print(f"ERROR: project_type '{args.project_type}' not found in {rules_path}")
        sys.exit(2)

    testRunner.make_framework_entry(
        False,
        runner_cfg.get("command", ""),
        runner_cfg.get("execute_path", ""),
        runner_cfg.get("build_path", runner_cfg.get("execute_path", "")),
    )
    
    testRunner.make_framework_entry(
        True,
        builder_cfg.get("command", ""),
        builder_cfg.get("execute_path", ""),
        builder_cfg.get("build_path", builder_cfg.get("execute_path", "")),
        builder_cfg.get("compiler_flags", []),
    )

    # Setup compiler
    testRunner.use_gcc_builder = builder_cfg.get("gcc_builder", False)

    if do_build:
        testRunner.make_build()

    if do_test:
        testRunner.make_testrun()
    # if tests failed, exit non-zero at top-level only
    if testRunner.has_failed():
        sys.exit(1)

if __name__ == "__main__":
    main()
