import importlib.util
import pathlib


def _load_module():
    root = pathlib.Path(__file__).resolve().parents[2]
    mod_path = root / "agent" / "build_and_run_tests.py"
    spec = importlib.util.spec_from_file_location("build_and_run_tests", str(mod_path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_testrunner_run_mode_with_framework_class():
    mod = _load_module()
    # create framework as a class instance
    test_runner = {
        "name": "ztester",
        "command": "python run_tests.py --run_test",
        "execute_path": "zephyr_main_app/ztests/",
    }
    test_builder = {
        "name": "zbuilder",
        "command": "python run_tests.py --build",
        "execute_path": "zephyr_main_app/ztests/",
    }
    framework_obj = mod.TestFramework(test_runner=test_runner, test_builder=test_builder)

    tr = mod.TestRunner("run", framework_obj)
    assert tr.mode == "run"
    assert tr.framework is framework_obj
    assert tr.runner_command == "python run_tests.py --run_test"
    assert tr.runner_execute_path == "zephyr_main_app/ztests/"
    assert tr.builder_command == "python run_tests.py --build"
    assert tr.builder_execute_path == "zephyr_main_app/ztests/"
    # selected values for run
    assert tr.command == tr.runner_command
    assert tr.execute_path == tr.runner_execute_path


def test_testrunner_build_mode_accepts_dict():
    mod = _load_module()
    framework = {
        "test_runner": {"command": "runcmd", "execute_path": "rpath"},
        "test_builder": {"command": "buildcmd", "execute_path": "bpath"},
    }
    tr = mod.TestRunner("build", framework)
    assert tr.mode == "build"
    assert tr.command == "buildcmd"
    assert tr.execute_path == "bpath"
    assert tr.runner_command == "runcmd"
    assert tr.builder_command == "buildcmd"
