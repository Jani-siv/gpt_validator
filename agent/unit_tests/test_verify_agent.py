import os
import sys
import subprocess
import json

import agent.verify_agent as va


class DummyProc:
    def __init__(self, stdout='', returncode=0):
        self.stdout = stdout
        self.returncode = returncode


def test_run_script_prints_and_returns(monkeypatch, capsys):
    monkeypatch.setattr(va.subprocess, 'run', lambda *a, **k: DummyProc('out\n', 2))
    code = va.run_script('/fake/script.py')
    captured = capsys.readouterr()
    assert 'out' in captured.out
    assert code == 2


def test_normalize_keys_and_read_framework():
    mapping = {' TestFramework ': {'builder': 1}, 'Other': 2}
    nk = va.normalize_keys(mapping)
    assert 'testframework' in nk
    rf = va.read_test_framework(mapping)
    assert isinstance(rf, dict)


def test_extract_command_and_path_variants():
    c, p = va.extract_command_and_path({'command': 'echo hi', 'execute_path': 'here'}, 'pref')
    assert c == 'echo hi'
    assert p == 'here'
    c2, p2 = va.extract_command_and_path({'pref_command': 'cmd', 'pref_execute-path': 'p'}, 'pref')
    assert c2 == 'cmd' and p2 == 'p'


def test_normalize_zephyr_command():
    cmd = 'python run_tests.py --run_test --build --other'
    out_run = va.normalize_zephyr_command(cmd, 'run', 'zephyr')
    assert '--run_test' not in out_run
    out_build = va.normalize_zephyr_command(cmd, 'build', 'zephyr')
    assert '--build-only' in out_build
    # non-zephyr unchanged
    assert va.normalize_zephyr_command(cmd, 'run', 'notzephyr') == cmd


def test_build_command_variants(tmp_path, monkeypatch):
    here = str(tmp_path)
    # create a fake script in cwd
    cwd = tmp_path / 'cwd'
    cwd.mkdir()
    script = cwd / 'script.py'
    script.write_text('print(1)')
    # python command form
    cmd = va.build_command('python script.py', ['arg'], here, str(cwd))
    assert cmd[0] == sys.executable
    assert script.name in cmd[1]

    # script path as .py first token
    cmd2 = va.build_command('myscript.py -x', ['a'], here, str(cwd))
    assert cmd2[0] == sys.executable

    # other command
    cmd3 = va.build_command('make all', [], here, str(cwd))
    assert cmd3[0] == 'make'


def test_build_command_empty_raises():
    try:
        va.build_command('', [], '.', '.')
        assert False, 'Expected ValueError'
    except ValueError:
        pass


def test_load_project_config_and_errors(tmp_path):
    here = str(tmp_path)
    rules = tmp_path / '.agent_rules.json'
    # missing file
    try:
        va.load_project_config(here, None)
        assert False
    except FileNotFoundError:
        pass

    # write invalid json structure
    rules.write_text(json.dumps({'project_configurations': []}))
    try:
        va.load_project_config(here, None)
        assert False
    except ValueError:
        pass

    # single project in list -> returns it
    rules.write_text(json.dumps({'project_configurations': [{'project_type': 'X', 'a': 1}]}))
    proj = va.load_project_config(here, None)
    assert proj.get('project_type').lower() == 'x'

    # unknown project type
    rules.write_text(json.dumps({'project_configurations': [{'project_type': 'a'},{'project_type':'b'}]}))
    try:
        va.load_project_config(here, 'c')
        assert False
    except ValueError:
        pass


def test_load_project_config_dict_variants(tmp_path):
    here = str(tmp_path)
    rules = tmp_path / '.agent_rules.json'
    # dict with multiple named projects -> should raise when project_type None
    rules.write_text(json.dumps({'project_configurations': {'a': {'x': 1}, 'b': {'y': 2}}}))
    try:
        va.load_project_config(here, None)
        assert False
    except ValueError:
        pass

    # dict with top-level project_type -> should return it
    rules.write_text(json.dumps({'project_configurations': {'project_type': 'Z', 'k': 1}}))
    proj = va.load_project_config(here, None)
    assert proj.get('project_type').lower() == 'z'


def test_main_scripts_missing_and_run_failure(monkeypatch, capsys):
    # script not found
    monkeypatch.setattr(va.os.path, 'isfile', lambda p: False)
    monkeypatch.setattr(sys, 'argv', ['verify_agent.py'])
    rc = va.main()
    assert rc == 2

    # scripts present but first script returns non-zero
    monkeypatch.setattr(va.os.path, 'isfile', lambda p: True)
    monkeypatch.setattr(va, 'run_script', lambda p: 5)
    monkeypatch.setattr(sys, 'argv', ['verify_agent.py'])
    rc = va.main()
    assert rc == 5


def test_main_build_and_run_flow(monkeypatch, tmp_path, capsys):
    # make scripts exist and initial run_script succeed
    monkeypatch.setattr(va.os.path, 'isfile', lambda p: True)
    monkeypatch.setattr(va, 'run_script', lambda p: 0)

    # prepare project config returned by load_project_config
    proj = {'project_type': 'zephyr', 'testframework': {'test_builder': {'command': 'python build.py', 'execute_path': 'execpath'}, 'test_runner': {'command': 'python run_tests.py --run_test', 'execute_path': 'execpath'}}}
    monkeypatch.setattr(va, 'load_project_config', lambda here, pt: proj)

    # ensure subprocess.run for build and run returns success
    def fake_run(cmd, cwd, stdout, stderr, text):
        return DummyProc('ok\n', 0)
    monkeypatch.setattr(va.subprocess, 'run', fake_run)

    # run main with build and run_test args
    monkeypatch.setattr(sys, 'argv', ['verify_agent.py', '--build', 'unit_tests/foo', '--run_test', 'unit_tests/foo', '--project', 'zephyr'])
    rc = va.main()
    out = capsys.readouterr().out
    assert rc == 0
    assert 'Running build:' in out
    assert 'Running tests:' in out


def test_build_command_uses_base_dir_when_candidate_missing(tmp_path):
    base = str(tmp_path)
    cwd = str(tmp_path / 'cwd')
    os.makedirs(cwd, exist_ok=True)
    # create script in base dir only
    script = tmp_path / 'build.py'
    script.write_text('x')
    cmd = va.build_command('python build.py', [], base, cwd)
    # second element should reference base dir build.py
    assert str(tmp_path / 'build.py').endswith('build.py')


def test_main_build_missing_builder_config(monkeypatch):
    monkeypatch.setattr(va.os.path, 'isfile', lambda p: True)
    monkeypatch.setattr(va, 'run_script', lambda p: 0)
    # project config missing builder/execute_path
    monkeypatch.setattr(va, 'load_project_config', lambda here, pt: {'project_type': 'p'})
    monkeypatch.setattr(sys, 'argv', ['verify_agent.py', '--build', 'unit_tests/x'])
    rc = va.main()
    assert rc == 2


def test_main_build_subprocess_failure(monkeypatch):
    monkeypatch.setattr(va.os.path, 'isfile', lambda p: True)
    monkeypatch.setattr(va, 'run_script', lambda p: 0)
    proj = {'project_type': 'p', 'testframework': {'test_builder': {'command': 'python build.py', 'execute_path': 'execpath'}}}
    monkeypatch.setattr(va, 'load_project_config', lambda here, pt: proj)
    # subprocess.run returns failure
    def fake_run_fail(cmd, cwd, stdout, stderr, text):
        return DummyProc('err', 2)
    monkeypatch.setattr(va.subprocess, 'run', fake_run_fail)
    monkeypatch.setattr(sys, 'argv', ['verify_agent.py', '--build', 'unit_tests/x'])
    rc = va.main()
    assert rc == 1


def test_main_run_missing_runner_config(monkeypatch):
    monkeypatch.setattr(va.os.path, 'isfile', lambda p: True)
    monkeypatch.setattr(va, 'run_script', lambda p: 0)
    monkeypatch.setattr(va, 'load_project_config', lambda here, pt: {'project_type': 'p'})
    monkeypatch.setattr(sys, 'argv', ['verify_agent.py', '--run_test', 'unit_tests/x'])
    rc = va.main()
    assert rc == 2


def test_main_run_subprocess_failure(monkeypatch):
    monkeypatch.setattr(va.os.path, 'isfile', lambda p: True)
    monkeypatch.setattr(va, 'run_script', lambda p: 0)
    proj = {'project_type': 'p', 'testframework': {'test_runner': {'command': 'python run.py', 'execute_path': 'execpath'}}}
    monkeypatch.setattr(va, 'load_project_config', lambda here, pt: proj)
    def fake_run_fail(cmd, cwd, stdout, stderr, text):
        return DummyProc('', 3)
    monkeypatch.setattr(va.subprocess, 'run', fake_run_fail)
    monkeypatch.setattr(sys, 'argv', ['verify_agent.py', '--run_test', 'unit_tests/x'])
    rc = va.main()
    assert rc == 1
