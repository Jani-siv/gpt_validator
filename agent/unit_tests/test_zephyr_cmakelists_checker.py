import json
import os
import re

import pytest

import agent.zephyr_cmakelists_checker as zc


def test_strip_cmake_comments_and_humanize():
    s = "set(PATH 'a#b') # comment here"
    assert zc._strip_cmake_comments(s).strip() == "set(PATH 'a#b')"
    assert zc.humanize_pattern('x/') == 'x/'
    assert zc.humanize_pattern('x') == 'x'


def test_default_and_load_json(tmp_path):
    p = tmp_path / 'r.json'
    data = {'a': 1}
    p.write_text(json.dumps(data))
    loaded = zc.load_json(str(p))
    assert loaded == data
    # default path should point to module dir .agent_rules.json
    dp = zc.default_agent_rules_path()
    assert dp.endswith('.agent_rules.json')


def test_select_project_rules_variants():
    assert zc.select_project_rules([]) == {}
    rules = {'project_configurations': [{'project_type': 'a', 'x': 1}]}
    assert zc.select_project_rules(rules)['project_type'] == 'a'


def test_find_git_root(tmp_path):
    # create nested dirs and a .git at top
    top = tmp_path / 'repo'
    top.mkdir()
    (top / '.git').mkdir()
    sub = top / 'sub' / 'sub2'
    sub.mkdir(parents=True)
    found = zc.find_git_root(str(sub))
    assert found == str(top)


def test_git_changed_files_unavailable(monkeypatch, tmp_path):
    # if get_changed_files is None, raise RuntimeError
    monkeypatch.setattr(zc, 'get_changed_files', None)
    # monkeypatch find_git_root to avoid scanning FS
    monkeypatch.setattr(zc, 'find_git_root', lambda x=None: str(tmp_path))
    with pytest.raises(RuntimeError):
        zc.git_changed_files()


def test_path_allowed_variants():
    assert zc.path_allowed('foo/bar', ['foo/'])
    assert zc.path_allowed('foo\\bar', ['foo/'])
    assert not zc.path_allowed('bar/foo', ['foo/'])


def test_run_check_invalid_rules(capsys):
    # non-dict rules
    assert zc.run_check(['not', 'a', 'dict']) == 2
    captured = capsys.readouterr()
    assert 'Rules file root must be an object' in captured.err


def test_run_check_no_relevant_files(monkeypatch, tmp_path, capsys):
    data = {'project_configurations': {'allowed_to_modify': ['foo/'], 'cmake_rules': {'not_allowed_cmake_include_dirs': []}}}
    # no changed files
    monkeypatch.setattr(zc, 'git_changed_files', lambda: ['other/CMakeLists.txt'])
    monkeypatch.setattr(zc, 'find_git_root', lambda x=None: str(tmp_path))
    # ensure file not present
    assert zc.run_check(data) == 0
    out = capsys.readouterr().out
    assert 'OK' in out


def test_run_check_detects_violations(monkeypatch, tmp_path, capsys):
    # Prepare repo and CMakeLists.txt under allowed prefix
    repo = tmp_path / 'repo'
    repo.mkdir()
    allowed_dir = repo / 'foo'
    allowed_dir.mkdir()
    cm = allowed_dir / 'CMakeLists.txt'
    # Compose content to trigger multiple checks: FILE(), add_subdirectory bad, target_link_libraries badlib, abs include
    cm.write_text('\n'.join([
        "set(MYDIR ../bad/include)",
        "target_include_directories(myexe PRIVATE ${MYDIR}/inc)",
        "file(WRITE something)",
        "add_subdirectory(bad/subdir)",
        "target_link_libraries(myexe",
        "  PUBLIC",
        "  badlib",
        ")",
    ]))

    data = {'project_configurations': [
        {'project_type': 'p', 'allowed_to_modify': ['foo/'], 'cmake_rules': {
            'not_allowed_cmake_include_dirs': ['bad/include/'],
            'not_allowed_cmake_subdirectories': ['bad/subdir/'],
            'not_allowed_cmake_linked_libraries': ['badlib']
        }}
    ]}

    # monkeypatch find_git_root to repo and git_changed_files to include our CMakeLists
    monkeypatch.setattr(zc, 'find_git_root', lambda x=None: str(repo))
    monkeypatch.setattr(zc, 'git_changed_files', lambda: ['foo/CMakeLists.txt'])

    rv = zc.run_check(data)
    out = capsys.readouterr().out
    # We expect violations to be found
    assert rv == 1
    assert 'FAIL' in out
    # Expect specific failure messages for subdirectory and linked lib
    assert 'Not allowed CMake subdirectory found' in out
    assert 'Not allowed CMake include dir found' in out or 'Absolute include path found' in out


def test_run_check_handles_git_error(monkeypatch, capsys):
    monkeypatch.setattr(zc, 'git_changed_files', lambda: (_ for _ in ()).throw(Exception('git fail')))
    data = {'project_configurations': {'allowed_to_modify': [], 'cmake_rules': {'not_allowed_cmake_include_dirs': []}}}
    rv = zc.run_check(data)
    assert rv == 2
    err = capsys.readouterr().err
    assert 'Error while running git' in err
