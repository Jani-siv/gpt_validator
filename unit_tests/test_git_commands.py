import importlib.util
import pathlib
import subprocess
import sys
import tempfile


def _load_module(path_name: str):
    root = pathlib.Path(__file__).resolve().parents[1]
    mod_path = root / path_name
    spec = importlib.util.spec_from_file_location(path_name.stem if isinstance(path_name, pathlib.Path) else "git_commands", str(mod_path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(cmd, cwd):
    subprocess.run(cmd, cwd=cwd, check=True)


def test_get_git_changes_untracked_and_staged():
    git_commands = _load_module("git_commands.py")
    with tempfile.TemporaryDirectory() as td:
        # init repo
        _run(["git", "init"], cwd=td)
        # create an untracked file
        p = pathlib.Path(td) / "a.txt"
        p.write_text("hello")

        changes = git_commands.get_git_changes(td)
        assert "a.txt" in changes["created"]

        # stage the file
        _run(["git", "add", "a.txt"], cwd=td)

        changes = git_commands.get_git_changes(td)
        assert "a.txt" in changes["staged"]
        assert "a.txt" in changes["created"]


def test_get_git_changes_modified_after_commit():
    git_commands = _load_module("git_commands.py")
    with tempfile.TemporaryDirectory() as td:
        _run(["git", "init"], cwd=td)
        # configure user for commits
        _run(["git", "config", "user.email", "test@example.com"], cwd=td)
        _run(["git", "config", "user.name", "Tester"], cwd=td)

        p = pathlib.Path(td) / "b.txt"
        p.write_text("first")
        _run(["git", "add", "b.txt"], cwd=td)
        _run(["git", "commit", "-m", "init"], cwd=td)

        # modify file in working tree
        p.write_text("changed")

        changes = git_commands.get_git_changes(td)
        assert "b.txt" in changes["modified"]
