import importlib.util
import json
import os
import pathlib
import shutil
import subprocess
import sys

import pytest


def _load_module():
    root = pathlib.Path(__file__).resolve().parents[2]
    mod_path = root / "agent" / "build_and_run_tests.py"
    spec = importlib.util.spec_from_file_location("build_and_run_tests", str(mod_path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_load_rules_and_get_execute_path(tmp_path):
    mod = _load_module()
    data = {
        "project_configurations": [
            {
                "project_type": "myproj",
                "testframework": {"test_builder": {"execute_path": "path/to/proj", "command": "make"}},
            }
        ]
    }
    rules_file = tmp_path / "rules.json"
    rules_file.write_text(json.dumps(data))

    loaded = mod.load_rules(rules_file)
    assert loaded["project_configurations"][0]["project_type"] == "myproj"

    exec_path, cmd = mod.get_execute_path(loaded, "myproj")
    assert exec_path == "path/to/proj"
    assert cmd == "make"

    exec_path_none, cmd_none = mod.get_execute_path(loaded, "other")
    assert exec_path_none is None and cmd_none is None


def test_find_repo_root(tmp_path):
    mod = _load_module()
    root = tmp_path / "root"
    nested = root / "a" / "b" / "c"
    nested.mkdir(parents=True)
    # create CMakeLists.txt at root
    (root / "CMakeLists.txt").write_text("")

    res = mod.find_repo_root(nested)
    assert res.resolve() == root.resolve()


def test_parse_ctest_failures_and_no_failures():
    mod = _load_module()
    sample = """Start
The following tests FAILED:
  1 - FooTest (Failed)
  2 - BarTest (Failed)

"""
    failures = mod.parse_ctest_failures(sample)
    assert "FooTest" in failures and "BarTest" in failures

    empty = "All tests passed\n"
    assert mod.parse_ctest_failures(empty) == []


def test_clean_build_dirs(tmp_path):
    mod = _load_module()
    proj = tmp_path / "proj"
    proj.mkdir()
    # create an existing build dir with a file
    b = proj / "build"
    b.mkdir()
    (b / "old.txt").write_text("old")

    unit_dir, integration_dir = mod.clean_build_dirs(proj)
    assert unit_dir.exists() and integration_dir.exists()
    assert not (b / "old.txt").exists()


def test_build_env_removes_keys_and_sets_compilers(monkeypatch):
    mod = _load_module()
    fake_env = os.environ.copy()
    # add some OECORE variables
    fake_env["OECORE_TARGET_OS"] = "linux"
    monkeypatch.setenv("OECORE_TARGET_OS", "linux")
    # run
    env = mod.build_env(True)
    assert env is not None
    assert "OECORE_TARGET_OS" not in env
    assert env.get("CC") == "/usr/bin/gcc"


def test_run_capture_output_invokes_subprocess(monkeypatch):
    mod = _load_module()

    class Dummy:
        def __init__(self):
            self.returncode = 0
            self.stdout = "ok"

    def fake_run(cmd, cwd=None, env=None, text=None, capture_output=None):
        return Dummy()

    monkeypatch.setattr(subprocess, "run", fake_run)
    res = mod.run(["echo", "hi"], cwd=".", capture_output=True)
    assert res is not None
    assert res.stdout == "ok"


def test_main_build_and_test_success(tmp_path, monkeypatch, capsys):
    mod = _load_module()
    # prepare rules and project dir
    repo_root = tmp_path / "repo"
    proj = repo_root / "proj"
    proj.mkdir(parents=True)
    rules = {"project_configurations": [{"project_type": "dti_tools", "testframework": {"test_builder": {"execute_path": "proj", "command": "make"}}}]}
    rules_file = tmp_path / "rules.json"
    rules_file.write_text(json.dumps(rules))

    # monkeypatch find_repo_root to return our tmp repo
    monkeypatch.setattr(mod, "find_repo_root", lambda start: repo_root)

    # fake run: for build steps return None, for ctest capture_output return success
    class Result:
        def __init__(self, returncode=0, stdout=""):
            self.returncode = returncode
            self.stdout = stdout

    def fake_run(cmd, cwd=None, env=None, capture_output=False, text=None):
        if capture_output:
            return Result(returncode=0, stdout="All tests passed\n")
        return None

    monkeypatch.setattr(mod, "run", fake_run)

    monkeypatch.setenv("PYTHONWARNINGS", "ignore")

    # call main with our rules path
    monkeypatch.setattr(sys, "argv", ["prog", "--rules", str(rules_file)])
    # should not raise
    mod.main()
    captured = capsys.readouterr()
    assert "OK: tests success" in captured.out


def test_main_test_failure_reports(tmp_path, monkeypatch):
    mod = _load_module()
    repo_root = tmp_path / "repo"
    proj = repo_root / "proj"
    proj.mkdir(parents=True)
    rules = {"project_configurations": [{"project_type": "dti_tools", "testframework": {"test_builder": {"execute_path": "proj", "command": "make"}}}]}
    rules_file = tmp_path / "rules.json"
    rules_file.write_text(json.dumps(rules))

    monkeypatch.setattr(mod, "find_repo_root", lambda start: repo_root)

    class BadResult:
        def __init__(self):
            self.returncode = 1
            self.stdout = "The following tests FAILED:\n  1 - BadTest (Failed)\n"

    def fake_run_fail(cmd, cwd=None, env=None, capture_output=False, text=None):
        if capture_output:
            return BadResult()
        return None

    monkeypatch.setattr(mod, "run", fake_run_fail)
    monkeypatch.setattr(sys, "argv", ["prog", "--rules", str(rules_file)])

    with pytest.raises(SystemExit):
        mod.main()
