import json
from pathlib import Path

import pytest

from agent.rules_parser import RulesParser


def test_init_missing_file(tmp_path):
    missing = tmp_path / "nope.json"
    with pytest.raises(FileNotFoundError):
        RulesParser(missing)


def test_get_test_runner_and_builder_with_path_and_string(tmp_path):
    data = {
        "project_configurations": [
            {
                "project_type": "myproj",
                "testframework": {
                    "test_runner": {"execute_path": "exec", "command": "run"},
                    "test_builder": {"execute_path": "build", "command": "make"},
                },
            }
        ]
    }
    f = tmp_path / "rules.json"
    f.write_text(json.dumps(data))

    # Path input
    rp = RulesParser(f)
    tr = rp.get_test_runner("myproj")
    tb = rp.get_test_builder("myproj")
    assert tr == {"execute_path": "exec", "command": "run"}
    assert tb == {"execute_path": "build", "command": "make"}

    # String input
    rp2 = RulesParser(str(f))
    assert rp2.get_test_runner("myproj") == tr
    assert rp2.get_test_builder("myproj") == tb


def test_get_returns_none_when_missing(tmp_path):
    data = {"project_configurations": [{"project_type": "other"}]}
    f = tmp_path / "rules.json"
    f.write_text(json.dumps(data))

    rp = RulesParser(f)
    assert rp.get_test_runner("missing") is None
    assert rp.get_test_builder("missing") is None
    # entry exists but no testframework
    assert rp.get_test_runner("other") is None
    assert rp.get_test_builder("other") is None
