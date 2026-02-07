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


def test_load_project_config_missing_file(tmp_path):
    # no .agent_rules.json present
    with pytest.raises(FileNotFoundError):
        RulesParser(str(tmp_path))


def test_load_project_config_single_and_select(tmp_path):
    data = {
        "project_configurations": {
            "myproj": {"project_type": "myproj", "testframework": {"test_runner": {"command": "run"}}}
        }
    }
    f = tmp_path / ".agent_rules.json"
    f.write_text(json.dumps(data))

    # single entry, project_type None should return the only entry
    rp = RulesParser(f)
    cfg = rp.load_project_config(None)
    assert cfg.get('project_type') == 'myproj'

    # selecting by name should also work (case-insensitive)
    cfg2 = rp.load_project_config('MYPROJ')
    assert cfg2.get('project_type') == 'myproj'


def test_load_project_config_multiple_requires_selection(tmp_path):
    data = {
        "project_configurations": [
            {"project_type": "one"},
            {"project_type": "two"}
        ]
    }
    f = tmp_path / ".agent_rules.json"
    f.write_text(json.dumps(data))

    rp = RulesParser(f)
    with pytest.raises(ValueError):
        rp.load_project_config(None)

    # unknown project raises ValueError listing available
    with pytest.raises(ValueError):
        rp.load_project_config('missing')
