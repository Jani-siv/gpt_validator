import json
import pathlib
import importlib.util
import sys


def _load_module():
    root = pathlib.Path(__file__).resolve().parents[1]
    mod_path = root / "gpt_validator.py"
    spec = importlib.util.spec_from_file_location("gpt_validator", str(mod_path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_list_files_with_extension_basic(tmp_path):
    repo = tmp_path / "repo"
    src = repo / "src"
    ignore = src / "ignore"
    src.mkdir(parents=True)
    ignore.mkdir()

    (src / "a.py").write_text("# a")
    (src / "b.py").write_text("# b")
    (ignore / "c.py").write_text("# c")

    mod = _load_module()
    files = mod.list_files_with_extension("py", exclude_paths=[str(ignore)], repo_root=str(src))
    # Should list only a.py and b.py (relative to repo_root which is src)
    assert sorted(files) == sorted(["a.py", "b.py"])


def test_check_files_tested_detects_untested(tmp_path):
    repo = tmp_path / "repo2"
    repo.mkdir()
    tests = repo / "tests"
    tests.mkdir()

    # create two source files
    (repo / "alpha.py").write_text("# alpha")
    (repo / "beta.py").write_text("# beta")

    # create a test that mentions only alpha
    (tests / "test_alpha.py").write_text("def test_alpha():\n    assert 'alpha'\n")

    mod = _load_module()
    # files passed relative to repo_root
    missing = mod.check_files_tested(["alpha.py", "beta.py"], str(tests), repo_root=str(repo))
    assert missing == "beta.py"


def test_main_with_bad_rules_json(tmp_path, capsys):
    repo = tmp_path / "rrepo"
    repo.mkdir()
    bad = repo / "bad_rules.json"
    bad.write_text("{ this is not: json }")
    mod = _load_module()
    rc = mod.main(["--rules", str(bad)])
    assert rc == 1


def test_main_with_rules_missing_keys(tmp_path):
    repo = tmp_path / "r2"
    repo.mkdir()
    rules = repo / "rules.json"
    rules.write_text(json.dumps({}))
    mod = _load_module()
    rc = mod.main(["--rules", str(rules)])
    assert rc == 1


def test_main_run_tests_non_python_language(tmp_path):
    repo = tmp_path / "r3"
    repo.mkdir()
    rules = repo / "rules.json"
    rules.write_text(json.dumps({"language": "javascript", "test_path": "tests"}))
    mod = _load_module()
    rc = mod.main(["--rules", str(rules), "--run-tests"])
    assert rc == 1


def test_main_run_tests_missing_test_path(tmp_path):
    repo = tmp_path / "r4"
    repo.mkdir()
    rules = repo / "rules.json"
    rules.write_text(json.dumps({"language": "python", "test_path": "no_such_tests"}))
    mod = _load_module()
    rc = mod.main(["--rules", str(rules), "--run-tests"])
    assert rc == 1


