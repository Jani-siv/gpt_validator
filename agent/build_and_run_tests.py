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
        # Use subprocess.run so test monkeypatches that replace subprocess.run
        # (and which may not accept a `timeout` kwarg) are compatible.
        proc = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        if proc.returncode != 0:
            return None
        out = proc.stdout.strip()
        return Path(out).resolve()
    except subprocess.CalledProcessError:
        return None

class TestRunner:
    def __init__(self, use_host_compiler: bool = True):
        self.script_dir = Path(__file__).parent
        self.repo_root = git_repo_root(self.script_dir) or Path.cwd()
        self.use_gcc_builder = False
        self.builder = { "command": "", "execute_path": Path, "build_path": Path , "gcc_builder": True, "compiler_flags": [] }
        self.runner = { "command": "", "execute_path": Path, "build_path": Path }
        self.env = build_env(use_host_compiler)
        self.cores = self.get_cores(8)
        self._failed = False
        self.custom_cmd_output = ""

    def make_framework_entry(self, is_builder: bool, command: str, execute_path: str, build_path: str, compiler_flags: list[str] | None = None, use_gcc_builder: bool = True) -> dict:
        # Validate inputs
        if not isinstance(is_builder, bool):
            raise TypeError("is_builder must be a boolean")
        # use_gcc_builder is controlled by the `use_gcc_builder` argument
        # (do not infer it from an empty command)

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
                "gcc_builder": use_gcc_builder,
                "compiler_flags": compiler_flags or []}
            # reflect configured builder choice on the instance attribute
            self.use_gcc_builder = bool(self.builder.get("gcc_builder"))
        else:
            self.runner = {
                "command": command,
                "execute_path": self.repo_root / execute_path,
                "build_path": self.repo_root / build_path}
    
    def get_custom_cmd_output(self) -> str:
        return self.custom_cmd_output
    
    def clean_build_dirs(self, build_dir: Path):
        if build_dir.exists():
            shutil.rmtree(build_dir)
        build_dir.mkdir(parents=True, exist_ok=True)


    def gcc_builder(self):
        try:
            # Use only the configured compiler flags from self.builder
            cfg_flags = self.builder.get("compiler_flags", [])
            if isinstance(cfg_flags, (list, tuple)):
                flags = [str(f) for f in cfg_flags]
            elif cfg_flags:
                flags = [str(cfg_flags)]
            else:
                flags = []

            src = str(self.builder["execute_path"])
            build = str(self.builder["build_path"])
            cmake_cmd = ["cmake", "-S", src, "-B", build, "-DCMAKE_CXX_COMPILER=g++"] + flags
            self.run(cmake_cmd, cwd=self.builder["execute_path"])
            self.run(["make", f"-j{self.cores}"], cwd=self.builder["build_path"])
            print("OK: build success")
        except subprocess.CalledProcessError as e:
            print(f"FAIL: build failed ({e})")
            # Mark the TestRunner as failed so higher-level callers can react.
            self._failed = True


    def make_build(self):
        self.clean_build_dirs(self.builder["build_path"])
        if self.use_gcc_builder:
            # call gcc_builder which uses configured flags from self.builder
            self.gcc_builder()
        else:
            print("Running custom command for build: " + self.builder["command"])
            self.custom_cmd_output = self.run(self.builder["command"].split(), cwd=self.builder["execute_path"], capture_output=True)


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
        else:
            print("Running custom command to run tests: " + self.runner["command"])
            self.custom_cmd_output = self.run(self.runner["command"].split(), cwd=self.runner["execute_path"], capture_output=True)


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
