import os
import json
import re

import pytest

import agent.zephyr_unittest_file_checker as zf


def test_humanize_pattern_variants():
    assert '#include <foo/...>' == zf.humanize_pattern('foo/')
    assert '#include <zephyr.h>' == zf.humanize_pattern('zephyr.h')
    assert '#include <path/to/header.h>' == zf.humanize_pattern('path/to/header.h')
    assert 'plain' == zf.humanize_pattern('plain')


def test_select_project_rules_and_default_and_load(tmp_path):
    p = tmp_path / 'rules.json'
    data = {'project_configurations': [{'project_type': 'x', 'a': 1}]}
    p.write_text(json.dumps(data))
    assert zf.select_project_rules(data)['project_type'] == 'x'
    loaded = zf.load_json(str(p))
    assert loaded == data
    assert zf.default_agent_rules_path().endswith('.agent_rules.json')


def test_git_changed_files_unavailable(monkeypatch, tmp_path):
    monkeypatch.setattr(zf, 'get_changed_files', None)
    monkeypatch.setattr(zf, 'find_git_root', lambda x=None: str(tmp_path))
    with pytest.raises(RuntimeError):
        zf.git_changed_files()


def setup_repo_with_files(tmp_path):
    repo = tmp_path / 'repo'
    repo.mkdir()
    (repo / '.git').mkdir()
    src = repo / 'src'
    src.mkdir()
    # create a C file with includes
    c1 = src / 'a.c'
    c1.write_text('\n'.join([
        '#include <good.h>',
        '#include <bad/include/some.h>',
        '/* #include <bad/include/commented.h> */',
        '// #include <bad/include/linecomment.h>',
        '#include "relative/path/header.inc"',
    ]))
    # create a header with a path-like include
    h1 = src / 'b.h'
    h1.write_text('#include <path/to/forbidden.h>')
    return str(repo)


def test_run_check_no_relevant_and_scan(tmp_path, monkeypatch, capsys):
    repo_path = setup_repo_with_files(tmp_path)
    # project rules: allowed prefix 'src/' and patterns to detect
    data = {'project_configurations': [{'project_type': 'p', 'allowed_to_modify': ['src/'],
                                        'cpp_code_rules': {'not_allowed_header_includes': ['bad/include/', 'path/to/forbidden.h'],
                                                          'not_allowed_include_extensions': ['.inc']}}]}
    # make git_changed_files return empty so run_check will scan filesystem
    monkeypatch.setattr(zf, 'git_changed_files', lambda: [])
    monkeypatch.setattr(zf, 'find_git_root', lambda x=None: repo_path)

    rv = zf.run_check(data)
    out = capsys.readouterr().out
    assert rv == 1
    # Expect failure messages for bad/include and forbidden.h and .inc
    assert 'bad/include' in out
    assert 'forbidden.h' in out
    assert 'includes *.inc files' in out


def test_ignored_and_comments(monkeypatch, tmp_path, capsys):
    repo = tmp_path / 'repo'
    repo.mkdir()
    (repo / '.git').mkdir()
    src = repo / 'src'
    src.mkdir()
    f = src / 'ok.c'
    f.write_text('/* block comment with #include <bad/include/foo.h> */\n// line comment #include <bad/include/bar.h>\n#include <good.h>')

    data = {'project_configurations': [{'project_type': 'p', 'allowed_to_modify': ['src/'],
                                        'cpp_code_rules': {'not_allowed_header_includes': ['bad/include/']}}]}
    monkeypatch.setattr(zf, 'git_changed_files', lambda: ['src/ok.c'])
    monkeypatch.setattr(zf, 'find_git_root', lambda x=None: str(repo))
    rv = zf.run_check(data)
    out = capsys.readouterr().out
    # No matching includes because they're in comments
    assert rv == 0
    assert 'OK' in out


def test_run_check_errors_and_invalid_rules(monkeypatch, capsys):
    # non-dict rules
    assert zf.run_check(['no']) == 2
    # invalid not_allowed_exts (ensure select_project_rules returns a dict)
    data = {'project_configurations': [{'project_type': 'p', 'not_allowed_include_extensions': 'bad'}]}
    assert zf.run_check(data) == 2
    # git error
    monkeypatch.setattr(zf, 'git_changed_files', lambda: (_ for _ in ()).throw(Exception('gitfail')))
    data = {'project_configurations': [{'project_type': 'p', 'allowed_to_modify': [], 'cpp_code_rules': {'not_allowed_header_includes': []}}]}
    rv = zf.run_check(data)
    assert rv == 2
    err = capsys.readouterr().err
    assert 'Error while running git' in err


def test_main_file_missing_and_json_error(monkeypatch, capsys):
    # file missing
    monkeypatch.setattr(zf, 'default_agent_rules_path', lambda: '/nonexistent/path')
    rv = zf.main()
    assert rv == 2

    # file exists but load_json raises
    monkeypatch.setattr(zf, 'default_agent_rules_path', lambda: '/some/path')
    monkeypatch.setattr(zf.os.path, 'exists', lambda p: True)
    monkeypatch.setattr(zf, 'load_json', lambda p: (_ for _ in ()).throw(Exception('bad json')))
    rv = zf.main()
    assert rv == 3


def test_git_changed_files_flatten(monkeypatch, tmp_path):
    # simulate get_changed_files returning various lists with overlap
    monkeypatch.setattr(zf, 'get_changed_files', lambda cwd: {'created': ['a', 'b'], 'added': ['b', 'c'], 'modified': ['d'], 'deleted': ['e']})
    monkeypatch.setattr(zf, 'find_git_root', lambda x=None: str(tmp_path))
    out = zf.git_changed_files()
    # order should be created then added then modified then deleted with no duplicates
    assert out == ['a', 'b', 'c', 'd', 'e']


def test_per_line_token_match_and_dedupe(monkeypatch, tmp_path, capsys):
    repo = tmp_path / 'repo'
    repo.mkdir()
    (repo / '.git').mkdir()
    src = repo / 'src'
    src.mkdir()
    f = src / 'tok.c'
    f.write_text('SOMETHING token_here\nSOMETHING token_here\n')
    data = {'project_configurations': [{'project_type': 'p', 'allowed_to_modify': ['src/'], 'cpp_code_rules': {'not_allowed_header_includes': ['token_here']}}]}
    monkeypatch.setattr(zf, 'find_git_root', lambda x=None: str(repo))
    monkeypatch.setattr(zf, 'git_changed_files', lambda: ['src/tok.c'])
    rv = zf.run_check(data)
    out = capsys.readouterr().out
    assert rv == 1
    # output should contain FAIL lines for the occurrences
    assert out.count('FAIL: src/tok.c') >= 1


def test_absolute_include_trimming(monkeypatch, tmp_path, capsys):
    repo = tmp_path / 'repo'
    repo.mkdir()
    (repo / '.git').mkdir()
    src = repo / 'src'
    src.mkdir()
    f = src / 'abs.c'
    # include with absolute path starting with repo
    f.write_text(f'#include <{str(repo)}/src/foo/forbidden.h>')
    data = {'project_configurations': [{'project_type': 'p', 'allowed_to_modify': ['src/'], 'cpp_code_rules': {'not_allowed_header_includes': ['foo/forbidden.h']}}]}
    monkeypatch.setattr(zf, 'find_git_root', lambda x=None: str(repo))
    monkeypatch.setattr(zf, 'git_changed_files', lambda: ['src/abs.c'])
    rv = zf.run_check(data)
    out = capsys.readouterr().out
    assert rv == 1
    assert 'foo/forbidden.h' in out
