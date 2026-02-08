import subprocess
import agent.git_file_handler as gfh
import pytest


def test_normalize_token_untracked():
    assert gfh._normalize_filename_from_token("?? foo.txt") == ("??", "foo.txt")


def test_normalize_token_added_and_rename():
    assert gfh._normalize_filename_from_token("A  new.txt") == ("A ", "new.txt")
    assert gfh._normalize_filename_from_token("R  old -> new.txt") == ("R ", "new.txt")


def test_normalize_token_fallback():
    assert gfh._normalize_filename_from_token("weird") == ("", "weird")


def test_run_git_status_porcelain_success(monkeypatch):
    class Proc:
        stdout = "?? a\nA  b\n"

    def fake_run(cmd, check, capture_output, text):
        return Proc()

    monkeypatch.setattr(gfh.subprocess, "run", fake_run)
    res = gfh._run_git_status_porcelain("/tmp")
    assert res == ["?? a", "A  b"]


def test_run_git_status_porcelain_failure(monkeypatch):
    def fake_run(cmd, check, capture_output, text):
        raise subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr(gfh.subprocess, "run", fake_run)
    assert gfh._run_git_status_porcelain("/tmp") == []


def test_run_git_ls_files(monkeypatch):
    class Proc:
        stdout = "./x.txt\ny.txt\n"

    def fake_run(cmd, check, capture_output, text):
        return Proc()

    monkeypatch.setattr(gfh.subprocess, "run", fake_run)
    res = gfh._run_git_ls_files("/tmp")
    assert res == ["./x.txt", "y.txt"]


def test_run_git_ls_files_failure(monkeypatch):
    def fake_run(cmd, check, capture_output, text):
        raise subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr(gfh.subprocess, "run", fake_run)
    assert gfh._run_git_ls_files("/tmp") == []


def test_get_changed_files(monkeypatch):
    monkeypatch.setattr(
        gfh,
        "_run_git_status_porcelain",
        lambda path: [
            "?? untracked.txt",
            "A  added.txt",
            " M mod_unstaged.txt",
            "D  deleted.txt",
            "R  old -> renamed.txt",
        ],
    )

    monkeypatch.setattr(gfh, "_run_git_ls_files", lambda path: ["./from_ls.txt", "file2.txt"])

    res = gfh.get_changed_files("/tmp")

    assert set(res["created"]) == set(["untracked.txt", "added.txt", "from_ls.txt", "file2.txt"])
    assert res["added"] == ["added.txt"]
    assert res["modified"] == ["mod_unstaged.txt"]
    assert res["deleted"] == ["deleted.txt"]


def test_wrappers(monkeypatch):
    monkeypatch.setattr(gfh, "get_changed_files", lambda path: {"created": [1], "added": [2], "modified": [3]})
    assert gfh.get_created_files("p") == [1]
    assert gfh.get_added_files("p") == [2]
    assert gfh.get_modified_files("p") == [3]
import subprocess
import types

import agent.git_file_handler as gfh


def test_normalize_untracked():
    status, name = gfh._normalize_filename_from_token("?? newfile.txt")
    assert status == "??"
    assert name == "newfile.txt"


def test_normalize_xy_and_rename():
    # staged add
    status, name = gfh._normalize_filename_from_token("A  added.txt")
    assert status == "A "
    assert name == "added.txt"

    # unstaged modified (space then M)
    status, name = gfh._normalize_filename_from_token(" M modified.txt")
    assert status == " M"
    assert name == "modified.txt"

    # rename: should return destination filename
    status, name = gfh._normalize_filename_from_token("R  oldname -> newname.txt")
    assert status == "R "
    assert name == "newname.txt"


def test_normalize_fallback():
    status, name = gfh._normalize_filename_from_token("weirdformat")
    assert status == ""
    assert name == "weirdformat"


def test_get_changed_files_monkeypatched(monkeypatch):
    # Prepare fake outputs for git status and git ls-files
    status_output = """
?? untracked.txt
A  staged_add.txt
 M modified_unstaged.txt
D  deleted.txt
R  old.txt -> renamed.txt
"""

    ls_files_output = "./extra.txt\nsub/another.txt\n"

    def fake_run(cmd, check, capture_output, text):
        class P:
            def __init__(self, out):
                self.stdout = out

        # detect which git command is being called
        if "status" in cmd:
            return P(status_output)
        if "ls-files" in cmd:
            return P(ls_files_output)
        raise subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr(subprocess, "run", fake_run)

    res = gfh.get_changed_files(".")

    # created should include untracked, staged add, and ls-files entries
    assert "untracked.txt" in res["created"]
    assert "staged_add.txt" in res["created"]
    assert "extra.txt" in res["created"]
    assert "sub/another.txt" in res["created"]

    # added should contain staged_add.txt
    assert res["added"] == ["staged_add.txt"]

    # modified should contain modified_unstaged.txt
    assert "modified_unstaged.txt" in res["modified"]

    # deleted should contain deleted.txt
    assert res["deleted"] == ["deleted.txt"]
