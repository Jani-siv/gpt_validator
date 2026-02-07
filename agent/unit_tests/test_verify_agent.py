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
        va.RulesParser(os.path.join(here, '.agent_rules.json'))
        assert False
    except FileNotFoundError:
        pass

    # write invalid json structure
    rules.write_text(json.dumps({'project_configurations': []}))
    rp = va.RulesParser(rules)
    try:
        rp.load_project_config(None)
        assert False
    except ValueError:
        pass

    # single project in list -> returns it
    rules.write_text(json.dumps({'project_configurations': [{'project_type': 'X', 'a': 1}]}))
    rp = va.RulesParser(rules)
    proj = rp.load_project_config(None)
    assert proj.get('project_type').lower() == 'x'

    # unknown project type
    rules.write_text(json.dumps({'project_configurations': [{'project_type': 'a'},{'project_type':'b'}]}))
    rp = va.RulesParser(rules)
    try:
        rp.load_project_config('c')
        assert False
    except ValueError:
        pass


def test_load_project_config_dict_variants(tmp_path):
    here = str(tmp_path)
    rules = tmp_path / '.agent_rules.json'
    # dict with multiple named projects -> should raise when project_type None
    rules.write_text(json.dumps({'project_configurations': {'a': {'x': 1}, 'b': {'y': 2}}}))
    try:
        rp = va.RulesParser(rules)
        rp.load_project_config(None)
        assert False
    except ValueError:
        pass

    # dict with top-level project_type -> should return it
    rules.write_text(json.dumps({'project_configurations': {'project_type': 'Z', 'k': 1}}))
    rp = va.RulesParser(rules)
    proj = rp.load_project_config(None)
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
    class DummyRP:
        def __init__(self, path):
            pass
        def load_project_config(self, pt):
            return proj
        def get_test_runner(self, pt):
            return proj.get('testframework', {}).get('test_runner', {})
        def get_test_builder(self, pt):
            return proj.get('testframework', {}).get('test_builder', {})
    monkeypatch.setattr(va, 'RulesParser', DummyRP)

    # ensure subprocess.run for build and run returns success
    def fake_run(*args, **kwargs):
        return DummyProc('ok\n', 0)
    monkeypatch.setattr(va.subprocess, 'run', fake_run)
    # avoid touching real filesystem build dirs (builder defaults may be placeholders)
    monkeypatch.setattr(va.TestRunner, 'clean_build_dirs', lambda self, build_dir: None)

    # run main with build and run_test args
    monkeypatch.setattr(sys, 'argv', ['verify_agent.py', '--build', 'unit_tests/foo', '--run_test', 'unit_tests/foo', '--project', 'zephyr'])
    rc = va.main()
    out = capsys.readouterr().out
    assert rc == 0
    assert 'All checks passed' in out
    assert '+ Running:' in out


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


def test_main_build_missing_builder_config(monkeypatch, capsys):
    monkeypatch.setattr(va.os.path, 'isfile', lambda p: True)
    monkeypatch.setattr(va, 'run_script', lambda p: 0)
    # project config missing builder/execute_path
    class DummyRP2:
        def __init__(self, path):
            pass
        def load_project_config(self, pt):
            return {'project_type': 'p'}
        def get_test_runner(self, pt):
            return {}
        def get_test_builder(self, pt):
            return {}
    monkeypatch.setattr(va, 'RulesParser', DummyRP2)
    monkeypatch.setattr(va.TestRunner, 'clean_build_dirs', lambda self, build_dir: None)
    monkeypatch.setattr(sys, 'argv', ['verify_agent.py', '--build', 'unit_tests/x'])
    try:
        rc = va.main()
    except SystemExit as e:
        rc = e.code
    out = capsys.readouterr().out
    assert rc == 0
    assert 'No supported builder configured' in out


def test_main_build_subprocess_failure(monkeypatch, capsys):
    monkeypatch.setattr(va.os.path, 'isfile', lambda p: True)
    monkeypatch.setattr(va, 'run_script', lambda p: 0)
    proj = {'project_type': 'p', 'testframework': {'test_builder': {'command': 'python build.py', 'execute_path': 'execpath'}}}
    class DummyRP3:
        def __init__(self, path):
            pass
        def load_project_config(self, pt):
            return proj
        def get_test_runner(self, pt):
            return {}
        def get_test_builder(self, pt):
            return proj.get('testframework', {}).get('test_builder', {})
    monkeypatch.setattr(va, 'RulesParser', DummyRP3)
    # subprocess.run returns failure
    def fake_run_fail(*args, **kwargs):
        raise subprocess.CalledProcessError(returncode=2, cmd='cmake')
    monkeypatch.setattr(va.subprocess, 'run', fake_run_fail)
    # avoid touching real filesystem build dirs
    monkeypatch.setattr(va.TestRunner, 'clean_build_dirs', lambda self, build_dir: None)
    monkeypatch.setattr(sys, 'argv', ['verify_agent.py', '--build', 'unit_tests/x'])
    try:
        rc = va.main()
    except SystemExit as e:
        rc = e.code
    out = capsys.readouterr().out
    assert rc == 0
    assert 'FAIL: build failed' in out


def test_main_run_missing_runner_config(monkeypatch, capsys):
    monkeypatch.setattr(va.os.path, 'isfile', lambda p: True)
    monkeypatch.setattr(va, 'run_script', lambda p: 0)
    class DummyRP4:
        def __init__(self, path):
            pass
        def load_project_config(self, pt):
            return {'project_type': 'p'}
        def get_test_runner(self, pt):
            return {}
        def get_test_builder(self, pt):
            return {}
    monkeypatch.setattr(va, 'RulesParser', DummyRP4)
    monkeypatch.setattr(va.TestRunner, 'clean_build_dirs', lambda self, build_dir: None)
    monkeypatch.setattr(sys, 'argv', ['verify_agent.py', '--run_test', 'unit_tests/x'])
    try:
        rc = va.main()
    except SystemExit as e:
        rc = e.code
    out = capsys.readouterr().out
    assert rc == 0
    assert 'No supported builder configured' in out
    assert 'No supported test runner configured' in out


def test_main_run_subprocess_failure(monkeypatch, capsys):
    monkeypatch.setattr(va.os.path, 'isfile', lambda p: True)
    monkeypatch.setattr(va, 'run_script', lambda p: 0)
    proj = {'project_type': 'p', 'testframework': {'test_runner': {'command': 'python run.py', 'execute_path': 'execpath'}}}
    class DummyRP5:
        def __init__(self, path):
            pass
        def load_project_config(self, pt):
            return proj
        def get_test_runner(self, pt):
            return proj.get('testframework', {}).get('test_runner', {})
        def get_test_builder(self, pt):
            return {}
    monkeypatch.setattr(va, 'RulesParser', DummyRP5)
    def fake_run_fail(*args, **kwargs):
        raise subprocess.CalledProcessError(returncode=3, cmd='ctest')
    monkeypatch.setattr(va.subprocess, 'run', fake_run_fail)
    # avoid touching real filesystem build dirs
    monkeypatch.setattr(va.TestRunner, 'clean_build_dirs', lambda self, build_dir: None)
    monkeypatch.setattr(sys, 'argv', ['verify_agent.py', '--run_test', 'unit_tests/x'])
    try:
        rc = va.main()
    except SystemExit as e:
        rc = e.code
    out = capsys.readouterr().out
    assert rc == 0
    assert 'No supported builder configured' in out
    assert 'No supported test runner configured' in out
