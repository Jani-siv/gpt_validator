import json
import os
from pathlib import Path

import pytest

import agent.verify_files as vf


def test_verify_paths(tmp_path):
    a = tmp_path / "exists.txt"
    a.write_text("x")
    missing = vf.verify_paths([str(a), str(tmp_path / "nope.txt")])
    assert str(a) not in missing
    assert str(tmp_path / "nope.txt") in missing


def test_load_agent_rules_success(tmp_path):
    p = tmp_path / "rules.json"
    data = {"project_configurations": [{"project_type": "x"}]}
    p.write_text(json.dumps(data))
    loaded = vf.load_agent_rules(str(p))
    assert loaded == data


def test_load_agent_rules_errors(tmp_path):
    # missing file
    with pytest.raises(FileNotFoundError):
        vf.load_agent_rules(str(tmp_path / "missing.json"))

    # invalid json
    p = tmp_path / "bad.json"
    p.write_text("not json")
    with pytest.raises(json.JSONDecodeError):
        vf.load_agent_rules(str(p))


def test_select_project_rules_variants():
    # non-dict returns empty mapping
    assert vf.select_project_rules([1, 2, 3]) == {}

    # list of project dicts -> returns first dict
    rules = {"project_configurations": [{"project_type": "a", "x": 1}, {"project_type": "b"}]}
    assert vf.select_project_rules(rules) == {"project_type": "a", "x": 1}

    # dict with project_type
    rules = {"project_configurations": {"project_type": "z", "y": 2}}
    assert vf.select_project_rules(rules)["project_type"] == "z"

    # dict mapping key->dict should inject project_type
    rules = {"project_configurations": {"foo": {"a": 1}}}
    out = vf.select_project_rules(rules)
    assert out.get("project_type") == "foo"


def test_git_modified_and_untracked_files(monkeypatch):
    monkeypatch.setattr(vf, "get_changed_files", lambda repo: {"modified": ["m1"], "added": ["a1"], "deleted": ["d1"], "created": ["c1"]})
    assert vf.git_modified_files("r") == ["m1", "a1", "d1"]
    # untracked should be created - added == []
    monkeypatch.setattr(vf, "get_changed_files", lambda repo: {"created": ["x", "y"], "added": ["y"]})
    assert vf.git_untracked_files("r") == ["x"]


def test_git_modified_files_unavailable(monkeypatch):
    monkeypatch.setattr(vf, "get_changed_files", None)
    with pytest.raises(RuntimeError):
        vf.git_modified_files("r")


def test_is_file_modified(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    # modified list contains repo-relative path
    monkeypatch.setattr(vf, "git_modified_files", lambda r: [os.path.normpath("sub/file.txt")])
    target = repo / "sub" / "file.txt"
    target.parent.mkdir()
    target.write_text("x")
    assert vf.is_file_modified(str(repo), str(target)) is True

    # outside repo: still match by basename
    monkeypatch.setattr(vf, "git_modified_files", lambda r: ["other/path/thing.py"])
    outside = tmp_path / "thing.py"
    outside.write_text("x")
    assert vf.is_file_modified(str(repo), str(outside)) is True


def test_disallowed_modified_files_various(monkeypatch, tmp_path):
    # rules allow src/ and *.md
    rules = {"project_configurations": {"file_rules": {"allowed_to_modify": ["src/", "*.md"], "ignored_files": ["ignored.txt"]}}}
    p = tmp_path / "rules.json"
    p.write_text(json.dumps(rules))

    # modified files include allowed and disallowed
    monkeypatch.setattr(vf, "git_modified_files", lambda r: ["src/new.py", "README.md", "other.txt", "ignored.txt"])
    monkeypatch.setattr(vf, "git_untracked_files", lambda r: ["untracked.txt"])

    dis = vf.disallowed_modified_files(str(tmp_path), str(p))
    # should skip ignored.txt and allow src/new.py and README.md, so other.txt and untracked.txt remain
    assert "other.txt" in dis
    assert "untracked.txt" in dis
    assert "src/new.py" not in dis
    assert "README.md" not in dis


def test_main_cmds_and_errors(monkeypatch, capsys):
    # help command
    monkeypatch.setattr(vf, "load_agent_rules", lambda p: {})
    monkeypatch.setattr(vf, "disallowed_modified_files", lambda a, b: [])
    monkeypatch.setattr("sys.argv", ["verify_files.py", "-h"])
    assert vf.main() == 0

    # unknown command
    monkeypatch.setattr("sys.argv", ["verify_files.py", "unknowncmd"])
    res = vf.main()
    assert res == 2

    # allowed listing prints allowed entries
    monkeypatch.setattr(vf, "load_agent_rules", lambda p: {"project_configurations": {"allowed_to_modify": ["a", "b"]}})
    monkeypatch.setattr("sys.argv", ["verify_files.py", "allowed"])
    assert vf.main() == 0

    # ignored listing prints ignored entries
    monkeypatch.setattr(vf, "load_agent_rules", lambda p: {"project_configurations": {"ignored_files": ["i1"]}})
    monkeypatch.setattr("sys.argv", ["verify_files.py", "ignored"])
    assert vf.main() == 0

    # enforcement: disallowed present
    monkeypatch.setattr(vf, "disallowed_modified_files", lambda a, b: ["x"])
    monkeypatch.setattr("sys.argv", ["verify_files.py"])
    rv = vf.main()
    captured = capsys.readouterr()
    assert rv == 1
    assert "FAIL" in captured.out

    # enforcement: ok
    monkeypatch.setattr(vf, "disallowed_modified_files", lambda a, b: [])
    rv = vf.main()
    captured = capsys.readouterr()
    assert rv == 0
    assert "OK:" in captured.out


def test_disallowed_handles_untracked_runtimeerror(monkeypatch, tmp_path):
    # rules allow nothing (so modified are disallowed)
    rules = {"project_configurations": {"file_rules": {}}}
    p = tmp_path / "rules.json"
    p.write_text(json.dumps(rules))

    monkeypatch.setattr(vf, "git_modified_files", lambda r: ["somefile.txt"])
    monkeypatch.setattr(vf, "git_untracked_files", lambda r: (_ for _ in ()).throw(RuntimeError("no git")))

    dis = vf.disallowed_modified_files(str(tmp_path), str(p))
    assert "somefile.txt" in dis


def test_disallowed_ignored_fnmatch_exception(monkeypatch, tmp_path):
    # Trigger the fnmatch exception path and fallback to endswith
    rules = {"project_configurations": {"file_rules": {"ignored_files": ["ignore.me"]}}}
    p = tmp_path / "rules.json"
    p.write_text(json.dumps(rules))

    monkeypatch.setattr(vf, "git_modified_files", lambda r: ["path/ignore.me"])

    # make fnmatch.fnmatch raise to hit except branch
    def fake_fnmatch(a, b):
        raise Exception("boom")

    monkeypatch.setattr(vf.fnmatch, "fnmatch", fake_fnmatch)

    dis = vf.disallowed_modified_files(str(tmp_path), str(p))
    # file should be considered ignored and thus not disallowed
    assert dis == []


def test_main_enforcement_exceptions(monkeypatch, capsys):
    # disallowed_modified_files raises FileNotFoundError
    monkeypatch.setattr(vf, "disallowed_modified_files", lambda a, b: (_ for _ in ()).throw(FileNotFoundError()))
    monkeypatch.setattr("sys.argv", ["verify_files.py"])
    rv = vf.main()
    captured = capsys.readouterr()
    assert rv == 1
    assert "Agent rules file not found" in captured.out

    # disallowed_modified_files raises JSONDecodeError
    monkeypatch.setattr(vf, "disallowed_modified_files", lambda a, b: (_ for _ in ()).throw(json.JSONDecodeError("err", "doc", 0)))
    rv = vf.main()
    captured = capsys.readouterr()
    assert rv == 1
    assert "Failed to parse agent rules JSON" in captured.out
