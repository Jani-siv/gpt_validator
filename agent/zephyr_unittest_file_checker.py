#!/usr/bin/env python3
"""Simple launcher to load the `.agent_rules.json` file in this tools directory.

Usage:
  python3 zephyr_unittest_allowed_includes.py
  python3 zephyr_unittest_allowed_includes.py --file /path/to/.agent_rules.json
  python3 zephyr_unittest_allowed_includes.py --keys

The default file is the `.agent_rules.json` located next to this script.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import re
from typing import Any, Iterable, List, Optional
import fnmatch
import sys as _sys_for_import
import os as _os_for_import
# ensure local tools dir is importable
_SCRIPT_DIR = _os_for_import.path.dirname(_os_for_import.path.abspath(__file__))
if _SCRIPT_DIR not in _sys_for_import.path:
    _sys_for_import.path.insert(0, _SCRIPT_DIR)
try:
    from git_file_handler import get_changed_files
except Exception:
    get_changed_files = None


def humanize_pattern(pat: str) -> str:
    # If pattern ends with '/', show a human-friendly closing char
    if pat.endswith('/'):
        # show folder-like patterns as an include fragment
        inner = pat[:-1]
        return f'#include <{inner}/...>'
    # If pattern is a filename like 'zephyr.h', show as an include
    if pat.endswith('.h'):
        return f'#include <{pat}>'
    # If pattern contains a path fragment, show as an include
    if '/' in pat:
        return f'#include <{pat}>'
    return pat


def default_agent_rules_path() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), '.agent_rules.json')


def load_json(path: str) -> Any:
    with open(path, 'r', encoding='utf-8') as fh:
        return json.load(fh)


def main() -> int:
    path = default_agent_rules_path()
    if not os.path.exists(path):
        print(f"Error: rules file not found: {path}", file=sys.stderr)
        return 2

    try:
        data = load_json(path)
    except Exception as e:
        print(f"Error loading JSON from {path}: {e}", file=sys.stderr)
        return 3

    return run_check(data)


def find_git_root(start: Optional[str] = None) -> Optional[str]:
    d = os.path.abspath(start or os.path.dirname(os.path.abspath(__file__)))
    while True:
        if os.path.isdir(os.path.join(d, '.git')):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


def git_changed_files(repo_dir: Optional[str] = None) -> List[str]:
    git_root = find_git_root(repo_dir)
    cwd = git_root or os.getcwd()
    if get_changed_files:
        info = get_changed_files(cwd)
        out: List[str] = []
        for key in ("created", "added", "modified", "deleted"):
            for p in info.get(key, []):
                if p not in out:
                    out.append(p)
        return out

    try:
        proc = subprocess.run(
            ['git', 'status', '--porcelain=v1', '-uall'],
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        raise RuntimeError('git executable not found')

    if proc.returncode != 0:
        raise RuntimeError(f"git failed: {proc.stderr.strip()}")

    paths: List[str] = []
    for ln in proc.stdout.splitlines():
        if not ln:
            continue
        raw = ln[3:].strip()
        if raw.startswith('./'):
            raw = raw[2:]
        if '->' in raw:
            raw = raw.split('->')[-1].strip()
        paths.append(raw)

    try:
        proc2 = subprocess.run(
            ['git', 'ls-files', '-o', '--exclude-standard'],
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if proc2.returncode == 0 and proc2.stdout:
            for ln in proc2.stdout.splitlines():
                p = ln.strip()
                if p.startswith('./'):
                    p = p[2:]
                if p and p not in paths:
                    paths.append(p)
    except FileNotFoundError:
        pass

    return paths


def path_allowed(path: str, allowed_prefixes: Iterable[str]) -> bool:
    p = path.replace('\\', '/')
    for pref in allowed_prefixes:
        pref_norm = pref.replace('\\', '/')
        if p.startswith(pref_norm):
            return True
    return False


def run_check(data: Any) -> int:
    if not isinstance(data, dict):
        print('Rules file root must be an object', file=sys.stderr)
        return 2

    allowed = data.get('allowed_to_modify', [])
    not_allowed = data.get('not_allowed_header_includes', [])
    not_allowed_exts = data.get('not_allowed_include_extensions', [])
    ignored = data.get('ignored_files', [])
    

    if not isinstance(allowed, list) or not isinstance(not_allowed, list):
        print('Invalid rules: expected lists for allowed_to_modify and not_allowed_header_includes', file=sys.stderr)
        return 2
    if not isinstance(not_allowed_exts, list):
        print('Invalid rules: expected list for not_allowed_include_extensions', file=sys.stderr)
        return 2

    try:
        changed = git_changed_files()
    except Exception as e:
        print(f"Error while running git: {e}", file=sys.stderr)
        return 2

    # Filter files to those under allowed prefixes
    relevant = [p for p in changed if path_allowed(p, allowed)]

    def is_ignored(path: str) -> bool:
        # Check against ignored patterns. Match basename, full path, and normalized path.
        bn = os.path.basename(path)
        norm = path.replace('\\', '/')
        for pat in ignored:
            if fnmatch.fnmatch(bn, pat):
                return True
            if fnmatch.fnmatch(path, pat):
                return True
            if fnmatch.fnmatch(norm, pat):
                return True
        return False

    # Remove ignored files from relevant
    relevant = [p for p in relevant if not is_ignored(p)]

    # If there are no git-changed files to check, fall back to scanning all files
    # under the allowed prefixes so unit-test mock files are validated as well.
    if not relevant:
        git_root = find_git_root() or os.getcwd()
        for pref in allowed:
            pref_path = os.path.join(git_root, pref)
            if os.path.isdir(pref_path):
                for root, dirs, files in os.walk(pref_path):
                    for fn in files:
                        relp = os.path.relpath(os.path.join(root, fn), git_root)
                        if relp not in relevant and not is_ignored(relp):
                            relevant.append(relp)
            else:
                # If prefix is a file path relative to repo, include it if present
                candidate = os.path.join(git_root, pref)
                if os.path.isfile(candidate):
                    relp = os.path.relpath(candidate, git_root)
                    if relp not in relevant and not is_ignored(relp):
                        relevant.append(relp)

    if not relevant:
        print('OK')
        return 0

    errors_found = []
    git_root = find_git_root() or os.getcwd()
    # prepare regexes for not_allowed patterns.
    # If pattern ends with '/', match either '/' or '.' after the base (legacy behavior).
    # If pattern is a filename like 'zephyr.h', match common #include forms.
    regexes = []
    for pat in not_allowed:
        if pat.endswith('/'):
            # Match folder-like patterns only in include lines to avoid
            # matching these fragments in arbitrary files (comments, scripts).
            base = re.escape(pat[:-1])
            regexes.append(re.compile(r'#\s*include\s*[<\"]\s*' + base + r'(?:[/.][^>\"]*)?[>\"]'))
        elif pat.endswith('.h'):
            regexes.append(re.compile(r'#\s*include\s*[<\"]\s*' + re.escape(pat) + r'\s*[>\"]'))
        else:
            # If pattern contains path separators, avoid generic matching across
            # arbitrary files (prevents matching inside tool scripts). Path-like
            # patterns will be checked against include targets and via the
            # restricted full-file fragment search for C/C++ files.
            if '/' in pat:
                continue
            regexes.append(re.compile(re.escape(pat)))
    for rel in relevant:
        full = os.path.join(git_root, rel)
        if not os.path.isfile(full):
            # skip directories or missing files
            continue
        # skip ignored files (re-check with full path)
        if is_ignored(rel):
            continue
        try:
            with open(full, 'r', encoding='utf-8', errors='replace') as fh:
                text = fh.read()
                # Identify block-comment spans (/* ... */) so we can ignore includes inside them
                block_spans = []
                for bb in re.finditer(r'/\*.*?\*/', text, flags=re.DOTALL):
                    block_spans.append((bb.start(), bb.end()))
                def idx_in_block(idx: int) -> bool:
                    for a, b in block_spans:
                        if a <= idx < b:
                            return True
                    return False
                # Map block-comment spans to line numbers to skip per-line checks
                commented_lines = set()
                if block_spans:
                    lines = text.splitlines()
                    # compute line start indices
                    line_starts = []
                    pos = 0
                    for ln in lines:
                        line_starts.append(pos)
                        pos += len(ln) + 1
                    for a, b in block_spans:
                        start_line = 1 + sum(1 for s in line_starts if s <= a) - 1
                        end_line = 1 + sum(1 for s in line_starts if s <= b) - 1
                        for L in range(start_line, end_line + 1):
                            commented_lines.add(L)
                
                # Per-line checks (legacy behavior) — ignore includes inside comments
                for i, line in enumerate(text.splitlines(), start=1):
                    if i in commented_lines:
                        continue
                    # detect line comment start
                    line_comment_pos = line.find('//')
                    for pat, rx in zip(not_allowed, regexes):
                        mrx = rx.search(line)
                        if not mrx:
                            continue
                        # if match is after a '//' line comment marker, ignore
                        if line_comment_pos != -1 and mrx.start() >= line_comment_pos:
                            continue
                        errors_found.append((rel, i, pat, line.rstrip('\n')))

                    m = re.search(r'#\s*include\s*[<\"]\s*([^>\"]+)\s*[>\"]', line)
                    if m:
                        # if include is after a '//' comment on the same line, skip
                        if line_comment_pos != -1 and m.start() >= line_comment_pos:
                            continue
                        include_target = m.group(1).replace('\\', '/')
                        if git_root and include_target.startswith('/') and include_target.startswith(git_root.replace('\\', '/')):
                            include_target = include_target[len(git_root.rstrip('/'))+1:]
                        # Flag header include patterns (folder-like or path-like)
                        for pat in not_allowed:
                            # Folder-like patterns
                            if pat.endswith('/'):
                                pat_norm = pat.replace('\\', '/')
                                if pat_norm in include_target:
                                    errors_found.append((rel, i, pat, line.rstrip('\n')))
                            # Path-like patterns containing directories (e.g. 'register_c_lite/wrappers/ParestRegsRegApiWrapper.h')
                            elif '/' in pat:
                                pat_norm = pat.replace('\\', '/')
                                if pat_norm in include_target:
                                    errors_found.append((rel, i, pat, line.rstrip('\n')))
                        # Flag includes that reference disallowed source-file extensions
                        inc_lower = include_target.lower()
                        for ext in not_allowed_exts:
                            if not isinstance(ext, str):
                                continue
                            e = ext.lower()
                            if not e.startswith('.'):
                                e = '.' + e
                            if inc_lower.endswith(e):
                                errors_found.append((rel, i, f'includes *{e} files', line.rstrip('\n')))

                # Extra: full-file search for folder-like or path-like patterns to catch
                # absolute includes or other occurrences spanning whitespace or macros.
                # Only perform the full-file fragment search for likely C/C++ source
                # or header files to avoid matching these patterns inside tool scripts.
                ext = os.path.splitext(full)[1].lower()
                allowed_exts = {'.c', '.cpp', '.cc', '.cxx', '.h', '.hpp', '.hh', '.inl'}
                if ext in allowed_exts:
                    for pat in not_allowed:
                        # Folder-like patterns
                        if pat.endswith('/'):
                            pat_norm = pat.replace('\\', '/')
                            search_text = text.replace('\\', '/')
                            idx = search_text.find(pat_norm)
                            while idx != -1:
                                # ignore occurrences inside block comments
                                if idx_in_block(idx):
                                    idx = search_text.find(pat_norm, idx + 1)
                                    continue
                                # ignore if occurrence is after '//' on same line
                                line_start = search_text.rfind('\n', 0, idx) + 1
                                if '//' in search_text[line_start:idx]:
                                    idx = search_text.find(pat_norm, idx + 1)
                                    continue
                                lineno = search_text.count('\n', 0, idx) + 1
                                excerpt_line = search_text.splitlines()[lineno-1] if lineno-1 < len(search_text.splitlines()) else ''
                                errors_found.append((rel, lineno, pat, excerpt_line))
                                idx = search_text.find(pat_norm, idx + 1)
                        # Path-like patterns containing directories
                        elif '/' in pat:
                            pat_norm = pat.replace('\\', '/')
                            search_text = text.replace('\\', '/')
                            idx = search_text.find(pat_norm)
                            while idx != -1:
                                if idx_in_block(idx):
                                    idx = search_text.find(pat_norm, idx + 1)
                                    continue
                                line_start = search_text.rfind('\n', 0, idx) + 1
                                if '//' in search_text[line_start:idx]:
                                    idx = search_text.find(pat_norm, idx + 1)
                                    continue
                                lineno = search_text.count('\n', 0, idx) + 1
                                excerpt_line = search_text.splitlines()[lineno-1] if lineno-1 < len(search_text.splitlines()) else ''
                                errors_found.append((rel, lineno, pat, excerpt_line))
                                idx = search_text.find(pat_norm, idx + 1)
        except Exception as e:
            print(f"Warning: could not read {rel}: {e}", file=sys.stderr)

    if errors_found:
        # Deduplicate identical findings while preserving order
        seen = set()
        unique = []
        for item in errors_found:
            if item not in seen:
                unique.append(item)
                seen.add(item)
        for rel, lineno, pat, excerpt in unique:
            disp = humanize_pattern(pat)
            excerpt_display = excerpt.strip()
            if excerpt_display:
                print(f"FAIL: {rel}:{lineno}: Not allowed include found: {disp} -- matched: {excerpt_display}")
            else:
                print(f"FAIL: {rel}:{lineno}: Not allowed include found: {disp}")
        return 1

    print('OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
