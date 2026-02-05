#!/usr/bin/env python3
"""Check CMakeLists.txt files for disallowed include directories.

This is similar to `zephyr_unittest_allowed_includes.py` but only inspects
`CMakeLists.txt` files that are created or modified under paths listed in
`allowed_to_modify` from the rules JSON file (default `.agent_rules.json`).

Behavior:
- If no relevant CMakeLists.txt files were changed/created under allowed
  prefixes, print `OK` and exit 0.
- If any CMakeLists.txt contains a pattern from
  `not_allowed_cmake_include_dirs`, print `FAIL` lines and exit 1.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from typing import Any, Iterable, List, Optional


def _strip_cmake_comments(line: str) -> str:
    """Return the line with CMake '#' comments removed, preserving quoted text.

    This stops at the first '#' that is not inside single or double quotes.
    """
    out_chars = []
    in_sq = False
    in_dq = False
    i = 0
    while i < len(line):
        c = line[i]
        if c == "'" and not in_dq:
            in_sq = not in_sq
            out_chars.append(c)
        elif c == '"' and not in_sq:
            in_dq = not in_dq
            out_chars.append(c)
        elif c == '#' and not in_sq and not in_dq:
            break
        else:
            out_chars.append(c)
        i += 1
    return ''.join(out_chars)


def humanize_pattern(pat: str) -> str:
    if pat.endswith('/'):
        return pat
    return pat


def default_agent_rules_path() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), '.agent_rules.json')


def load_json(path: str) -> Any:
    with open(path, 'r', encoding='utf-8') as fh:
        return json.load(fh)


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
    not_allowed_includes = data.get('not_allowed_cmake_include_dirs', [])
    not_allowed_subdirs = data.get('not_allowed_cmake_subdirectories', [])
    not_allowed_linked_libs = data.get('not_allowed_cmake_linked_libraries', [])

    if not isinstance(allowed, list) or not isinstance(not_allowed_includes, list) or not isinstance(not_allowed_subdirs, list):
        print('Invalid rules: expected lists for allowed_to_modify, not_allowed_cmake_include_dirs and not_allowed_cmake_subdirectories', file=sys.stderr)
        return 2

    try:
        changed = git_changed_files()
    except Exception as e:
        print(f"Error while running git: {e}", file=sys.stderr)
        return 2

    # Only consider CMakeLists.txt files under allowed prefixes
    relevant = [p for p in changed if os.path.basename(p) == 'CMakeLists.txt' and path_allowed(p, allowed)]

    if not relevant:
        print('OK')
        return 0

    errors_found = []
    git_root = find_git_root() or os.getcwd()

    # Prepare regexes for not_allowed entries. If entry ends with '/', match as directory prefix.
    checks: List[tuple[str, re.Pattern, str]] = []  # (pattern, regex, kind)
    for pat in not_allowed_includes:
        if pat.endswith('/'):
            base = re.escape(pat.rstrip('/'))
            checks.append((pat, re.compile(base + r'([/\\]|\b)'), 'include'))
        else:
            checks.append((pat, re.compile(re.escape(pat)), 'include'))

    for pat in not_allowed_subdirs:
        if pat.endswith('/'):
            base = re.escape(pat.rstrip('/'))
            checks.append((pat, re.compile(base + r'([/\\]|\b)'), 'subdirectory'))
        else:
            checks.append((pat, re.compile(re.escape(pat)), 'subdirectory'))

    # linked libraries: match token-like occurrences in target_link_libraries()
    for pat in not_allowed_linked_libs:
        # match library name as a token (not part of longer identifier)
        rx = re.compile(r'(?<![A-Za-z0-9_])' + re.escape(pat) + r'(?![A-Za-z0-9_])')
        checks.append((pat, rx, 'linked_lib'))

    # path extractor to prefer showing the actual included subdirectory/token
    path_extractor = re.compile(r"(\.{2}/(?:\.{2}/)*[^\s',\)\"]*)")

    for rel in relevant:
        full = os.path.join(git_root, rel)
        if not os.path.isfile(full):
            continue
        try:
            with open(full, 'r', encoding='utf-8', errors='replace') as fh:
                lines = fh.readlines()

            # strip comments and collect simple set(VAR value) assignments to allow basic variable expansion
            cleaned_lines = [_strip_cmake_comments(ln) for ln in lines]
            var_map: dict[str, str] = {}
            set_rx = re.compile(r"^\s*set\s*\(\s*([A-Za-z0-9_]+)\s+([^\)]+)\)", re.IGNORECASE)
            for ln in cleaned_lines:
                m = set_rx.match(ln)
                if m:
                    name = m.group(1)
                    val = m.group(2).strip()
                    var_map[name] = val

            for i, (orig_line, line) in enumerate(zip(lines, cleaned_lines), start=1):
                # expand known variables (basic replacement)
                expanded = line
                for name, val in var_map.items():
                    token = '${' + name + '}'
                    if token in expanded:
                        # remove ${CMAKE_SOURCE_DIR} if present in value to keep relative path tokens
                        v = val.replace('${CMAKE_SOURCE_DIR}', '').strip()
                        # strip leading slash so ../ tokens are matched by extractor
                        v = v.lstrip('/')
                        expanded = expanded.replace(token, v)

                for pat, rx, kind in checks:
                    # For subdirectory rules, only consider lines that invoke add_subdirectory()
                    if kind == 'subdirectory' and not re.search(r'\badd_subdirectory\s*\(', expanded, re.IGNORECASE):
                        continue

                    # linked_lib checks are handled separately by scanning target_link_libraries blocks
                    if kind == 'linked_lib':
                        continue

                    m = rx.search(expanded)
                    if m:
                        matched_display = None
                        pm = path_extractor.search(expanded)
                        if pm:
                            matched_display = pm.group(1)
                        if not matched_display:
                            matched_display = pat
                        errors_found.append((rel, i, pat, kind, matched_display))

            # Now scan for target_link_libraries(...) blocks and check for disallowed linked libs
            # Build a simple stateful parser to collect the full argument list (handles multi-line).
            idx = 0
            while idx < len(cleaned_lines):
                ln = cleaned_lines[idx]
                if re.search(r'\btarget_link_libraries\s*\(', ln, re.IGNORECASE):
                    start_idx = idx
                    paren_count = ln.count('(') - ln.count(')')
                    content_parts = [ln]
                    idx += 1
                    while paren_count > 0 and idx < len(cleaned_lines):
                        ln2 = cleaned_lines[idx]
                        paren_count += ln2.count('(') - ln2.count(')')
                        content_parts.append(ln2)
                        idx += 1

                    block = ' '.join(content_parts)
                    # apply same variable expansion to the block
                    for name, val in var_map.items():
                        token = '${' + name + '}'
                        if token in block:
                            v = val.replace('${CMAKE_SOURCE_DIR}', '').strip()
                            v = v.lstrip('/')
                            block = block.replace(token, v)

                    for pat, rx, kind in checks:
                        if kind != 'linked_lib':
                            continue
                        m = rx.search(block)
                        if m:
                            # report at the line where the block started
                            matched_display = pat
                            errors_found.append((rel, start_idx + 1, pat, kind, matched_display))
                    continue
                idx += 1
        except Exception as e:
            print(f"Warning: could not read {rel}: {e}", file=sys.stderr)

    if errors_found:
        for rel, lineno, pat, kind, excerpt in errors_found:
            disp = humanize_pattern(excerpt)
            if kind == 'subdirectory':
                reason = 'Not allowed CMake subdirectory found'
            else:
                reason = 'Not allowed CMake include dir found'
            print(f"FAIL: {rel}:{lineno}: {reason}: {disp}")
        return 1

    print('OK')
    return 0


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


if __name__ == '__main__':
    raise SystemExit(main())
