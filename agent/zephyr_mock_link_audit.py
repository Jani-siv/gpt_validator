#!/usr/bin/env python3
"""Audit mock library linkage for unit test CMakeLists.

Ensures mock libraries referenced in CMake target_link_libraries are
reachable from the unit test app target (transitively).
"""
from __future__ import annotations

import os
import re
import sys
from typing import Dict, List, Set, Tuple


MOCK_LIB_RE = re.compile(r"zephyr_library_named\s*\(\s*([^\)]+?)\s*\)")
TARGET_LINK_RE = re.compile(r"target_link_libraries\s*\(\s*([^\)]+?)\s*\)", re.DOTALL)
ADD_SUBDIR_RE = re.compile(r"add_subdirectory\s*\(\s*([^\)]+?)\s*\)")
COMMENT_RE = re.compile(r"#.*")


def _strip_comments(text: str) -> str:
    return "\n".join(COMMENT_RE.sub("", line) for line in text.splitlines())


def _split_cmake_args(blob: str) -> List[str]:
    cleaned = re.sub(r"\s+", " ", blob.strip())
    if not cleaned:
        return []
    return cleaned.split(" ")


def parse_cmake_file(path: str) -> Tuple[Dict[str, List[str]], List[str]]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            content = _strip_comments(handle.read())
    except OSError:
        return {}, []

    target_links: Dict[str, List[str]] = {}
    add_subdirs: List[str] = []

    for match in TARGET_LINK_RE.finditer(content):
        tokens = _split_cmake_args(match.group(1))
        if not tokens:
            continue
        target = tokens[0]
        libs = [tok for tok in tokens[1:] if tok not in {"PRIVATE", "PUBLIC", "INTERFACE"}]
        if libs:
            target_links.setdefault(target, []).extend(libs)

    for match in ADD_SUBDIR_RE.finditer(content):
        tokens = _split_cmake_args(match.group(1))
        if not tokens:
            continue
        subdir = tokens[0].strip('"')
        if "$" in subdir:
            continue
        add_subdirs.append(subdir)

    return target_links, add_subdirs


def collect_mock_libs(root: str) -> Set[str]:
    cmake_path = os.path.join(root, "unit_tests", "mock_files", "CMakeLists.txt")
    try:
        with open(cmake_path, "r", encoding="utf-8") as handle:
            content = _strip_comments(handle.read())
    except OSError:
        return set()

    return {match.group(1).strip() for match in MOCK_LIB_RE.finditer(content)}


def resolve_subdir(cmake_dir: str, subdir: str) -> str | None:
    if os.path.isabs(subdir):
        return subdir
    resolved = os.path.abspath(os.path.join(cmake_dir, subdir))
    if os.path.isdir(resolved):
        return resolved
    return None


def build_link_graph(entry_cmake: str) -> Dict[str, List[str]]:
    graph: Dict[str, List[str]] = {}
    visited: Set[str] = set()

    def visit(cmake_path: str) -> None:
        if cmake_path in visited:
            return
        visited.add(cmake_path)

        cmake_dir = os.path.dirname(cmake_path)
        target_links, subdirs = parse_cmake_file(cmake_path)
        for target, libs in target_links.items():
            graph.setdefault(target, []).extend(libs)

        for subdir in subdirs:
            resolved_dir = resolve_subdir(cmake_dir, subdir)
            if not resolved_dir:
                continue
            sub_cmake = os.path.join(resolved_dir, "CMakeLists.txt")
            if os.path.isfile(sub_cmake):
                visit(sub_cmake)

    visit(entry_cmake)
    return graph


def reachable_libs(graph: Dict[str, List[str]], start: str) -> Set[str]:
    reachable: Set[str] = set()
    stack = [start]
    while stack:
        target = stack.pop()
        for lib in graph.get(target, []):
            if lib in reachable:
                continue
            reachable.add(lib)
            if lib in graph:
                stack.append(lib)
    return reachable


def audit_unit_test(cmake_path: str, mock_libs: Set[str]) -> List[str]:
    graph = build_link_graph(cmake_path)
    referenced = set()
    for libs in graph.values():
        referenced.update(lib for lib in libs if lib in mock_libs)

    if not referenced:
        return []

    reachable = reachable_libs(graph, "app")
    missing = sorted(lib for lib in referenced if lib not in reachable)
    return missing


def main() -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    zephyr_root = os.path.abspath(os.path.join(here, "..", ".."))
    unit_tests_dir = os.path.join(zephyr_root, "unit_tests", "driver")

    mock_libs = collect_mock_libs(zephyr_root)
    if not mock_libs:
        print("WARN: no mock libraries found to audit")
        return 0

    failures = []
    for root, _dirs, files in os.walk(unit_tests_dir):
        if "CMakeLists.txt" not in files:
            continue
        cmake_path = os.path.join(root, "CMakeLists.txt")
        missing = audit_unit_test(cmake_path, mock_libs)
        if missing:
            rel = os.path.relpath(cmake_path, zephyr_root)
            failures.append((rel, missing))

    if failures:
        print("FAIL: Mock link audit found unlinked mock libraries:")
        for rel, missing in failures:
            print(f"- {rel}: {', '.join(missing)}")
        return 1

    print("OK: mock link audit passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
