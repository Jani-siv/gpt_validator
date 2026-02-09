import json

import pytest

from agent.rules_parser import RulesParser
from agent.verify_files import VerifyFiles


def _make_rules_parser(tmp_path):
    data = {"project_configurations": [{"project_type": "myproj"}]}
    f = tmp_path / "rules.json"
    f.write_text(json.dumps(data))
    rp = RulesParser(f)

    # VerifyFiles currently expects the RulesParser instance to provide
    # `get_allowed_path()` and `get_allowed_extensions()` methods. Add
    # them dynamically on the instance for tests.
    rp.get_allowed_path = lambda: ["src/"]
    rp.get_allowed_extensions = lambda: [".c", ".h"]
    return rp


def test_verify_passes_when_files_allowed(monkeypatch, tmp_path):
    rp = _make_rules_parser(tmp_path)

    monkeypatch.setattr("agent.git_file_handler.get_created_files", lambda p: ["src/main.c"])
    monkeypatch.setattr("agent.git_file_handler.get_added_files", lambda p: [])
    monkeypatch.setattr("agent.git_file_handler.get_modified_files", lambda p: [])

    vf = VerifyFiles(rp, "myproj")
    assert vf.is_passed() is True


def test_verify_fails_on_disallowed_path(monkeypatch, tmp_path):
    rp = _make_rules_parser(tmp_path)

    monkeypatch.setattr("agent.git_file_handler.get_created_files", lambda p: ["other/file.c"])
    monkeypatch.setattr("agent.git_file_handler.get_added_files", lambda p: [])
    monkeypatch.setattr("agent.git_file_handler.get_modified_files", lambda p: [])

    vf = VerifyFiles(rp, "myproj")
    assert vf.is_passed() is False


def test_delegate_get_methods(monkeypatch, tmp_path):
    rp = _make_rules_parser(tmp_path)

    monkeypatch.setattr("agent.git_file_handler.get_created_files", lambda p: ["src/a.c"])
    monkeypatch.setattr("agent.git_file_handler.get_added_files", lambda p: ["src/b.h"])
    monkeypatch.setattr("agent.git_file_handler.get_modified_files", lambda p: ["src/c.c"])

    vf = VerifyFiles(rp, "myproj")
    assert vf.get_created_files() == ["src/a.c"]
    assert vf.get_added_files() == ["src/b.h"]
    assert vf.get_modified_files() == ["src/c.c"]
