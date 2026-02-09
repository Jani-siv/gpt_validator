import importlib.util
import pathlib
import types
import unittest.mock


def _load_verify_agent_module():
    root = pathlib.Path(__file__).resolve().parents[2]
    mod_path = root / "agent" / "verify_agent.py"
    spec = importlib.util.spec_from_file_location("verify_agent", str(mod_path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_run_script_prints_and_returns_code(capsys):
    mod = _load_verify_agent_module()

    fake_proc = types.SimpleNamespace(returncode=3, stdout='out\n')
    with unittest.mock.patch.object(mod.subprocess, 'run', return_value=fake_proc):
        rc = mod.run_script('/irrelevant')
        captured = capsys.readouterr()
        assert rc == 3
        assert 'out' in captured.out


def test_configure_test_runner_calls_make_framework_entry():
    mod = _load_verify_agent_module()

    class FakeRP:
        def get_test_runner(self, project_type):
            return {
                'command': 'run-cmd',
                'execute_path': 'exec/path',
                'build_path': 'run-build',
            }

        def get_test_builder(self, project_type):
            return {
                'command': 'build-cmd',
                'execute_path': 'build/exec',
                'build_path': 'build/build',
                'compiler_flags': ['-O3'],
                'gcc_builder': False,
            }

    fake_rp = FakeRP()
    fake_tr = unittest.mock.Mock()

    mod.configure_test_runner(fake_rp, fake_tr, 'proj')

    assert fake_tr.make_framework_entry.call_count == 2

    first_call = fake_tr.make_framework_entry.call_args_list[0][0]
    second_call = fake_tr.make_framework_entry.call_args_list[1][0]

    assert first_call == (False, 'run-cmd', 'exec/path', 'run-build')
    assert second_call == (True, 'build-cmd', 'build/exec', 'build/build', ['-O3'], False)
