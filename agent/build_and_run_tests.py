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


def find_repo_root(start: Path) -> Path:
    p = start.resolve()
    last = None
    for parent in [p] + list(p.parents):
        if (parent / "CMakeLists.txt").exists():
            last = parent
    if last:
        return last
    return Path.cwd().resolve()


def load_rules(rules_path: Path):
    with rules_path.open() as f:
        return json.load(f)


def get_execute_path(rules, project_type: str):
    for pc in rules.get("project_configurations", []):
        if pc.get("project_type") == project_type:
            tb = pc.get("testframework", {}).get("test_builder", {})
            return tb.get("execute_path"), tb.get("command")
    return None, None


def run(cmd, cwd=None, env=None, capture_output=False):
    print(f"+ Running: {' '.join(cmd)} (cwd={cwd})")
    if capture_output:
        return subprocess.run(cmd, cwd=cwd, env=env, text=True, capture_output=True)
    subprocess.run(cmd, cwd=cwd, check=True, env=env)
    return None


def parse_ctest_failures(output: str):
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


def clean_build_dirs(project_dir: Path):
    build_dir = project_dir / "build"
    if build_dir.exists():
        shutil.rmtree(build_dir)
    build_dir.mkdir(parents=True, exist_ok=True)

    unit_dir = build_dir / "unitTest"
    integration_dir = build_dir / "integration"
    unit_dir.mkdir()
    integration_dir.mkdir()
    return unit_dir, integration_dir


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
    p.add_argument("--run_tests", action="store_true", help="only run tests (ctest)")
    compiler_group = p.add_mutually_exclusive_group()
    compiler_group.add_argument(
        "--host-compiler",
        action="store_true",
        help="force host compiler/toolchain and ignore SDK env (default)",
    )
    compiler_group.add_argument(
        "--sdk-compiler",
        action="store_true",
        help="use the current environment toolchain (SDK/Yocto)",
    )
    args = p.parse_args()

    script_dir = Path(__file__).parent
    rules_path = Path(args.rules) if args.rules else script_dir / ".agent_rules.json"
    if not rules_path.exists():
        print(f"ERROR: rules file not found: {rules_path}")
        sys.exit(2)

    rules = load_rules(rules_path)
    execute_path, builder_cmd = get_execute_path(rules, args.project_type)
    if not execute_path:
        print(f"ERROR: project_type '{args.project_type}' not found in {rules_path}")
        sys.exit(2)

    repo_root = find_repo_root(script_dir)
    project_dir = (repo_root / execute_path).resolve()
    if not project_dir.exists():
        print(f"ERROR: computed project_dir does not exist: {project_dir}")
        sys.exit(2)

    print(f"Repo root: {repo_root}")
    print(f"Project dir: {project_dir}")

    cores = multiprocessing.cpu_count()

    do_build = args.build or args.run_tests or (not args.build and not args.run_tests)
    do_test = args.run_tests or (not args.build and not args.run_tests)
    use_host_compiler = not args.sdk_compiler
    env = build_env(use_host_compiler)
    if env is not None:
        print("Info: using host compiler environment for this run only.")

    unit_dir = None
    if do_build:
        unit_dir, _ = clean_build_dirs(project_dir)
        # Some CMake scripts try to install Python deps like cxxheaderparser
        # Attempt to ensure it's available to avoid permission errors during CMake.
        try:
            import cxxheaderparser  # type: ignore
        except Exception:
            print("Info: Python package 'cxxheaderparser' not found. Attempting to install with --user...")
            try:
                run([sys.executable, "-m", "pip", "install", "--user", "cxxheaderparser"], env=env)
            except subprocess.CalledProcessError:
                print("Warning: automatic install of 'cxxheaderparser' failed. CMake may attempt to install it and require elevated permissions.")
        try:
            run(["cmake", "-DCMAKE_CXX_COMPILER=g++", "-DUNIT_TEST=ON", str(project_dir)], cwd=unit_dir, env=env)
            run(["make", f"-j{cores}"], cwd=unit_dir, env=env)
            print("OK: build success")
        except subprocess.CalledProcessError as e:
            print(f"FAIL: build failed ({e})")
            sys.exit(1)

    if do_test:
        if unit_dir is None:
            unit_dir = (project_dir / "build" / "unitTest").resolve()
        result = run(["ctest", "--output-on-failure"], cwd=unit_dir, env=env, capture_output=True)
        if result is None:
            print("FAIL: tests did not run")
            sys.exit(1)
        if result.returncode == 0:
            print("OK: tests success")
            return

        failures = parse_ctest_failures(result.stdout)
        log_path = (unit_dir / "Testing" / "Temporary" / "LastTest.log").resolve()
        if failures:
            print("FAIL: tests failed")
            print("Failed tests:")
            for name in failures:
                print(f"- {name}")
        else:
            print("FAIL: tests failed (unable to list failing tests from ctest output)")
        print(f"Logs: {log_path}")
        sys.exit(1)


if __name__ == "__main__":
    main()
