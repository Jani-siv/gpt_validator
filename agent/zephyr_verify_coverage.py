#!/usr/bin/env python3
"""Verify coverage reported in ../reports/coverage.xml.

Behavior:
- No args: reads reports/coverage.xml relative to this script.
- If file missing: prints "FAIL: <reason>" and exits non-zero.
- If file empty: prints "FAIL: no content on coverage.xml" and exits non-zero.
- If line coverage < 80%: prints "FAIL: <filename> coverage under 80%" and exits non-zero.
- Otherwise prints "OK" and exits 0.
"""
from __future__ import annotations

import os
import sys
import xml.etree.ElementTree as ET


def coverage_from_xml(path: str) -> float | None:
    try:
        tree = ET.parse(path)
    except Exception:
        return None
    root = tree.getroot()

    # 1) Common: root may have 'line-rate'
    lr = root.attrib.get("line-rate")
    if lr is not None:
        try:
            return float(lr) * 100.0
        except Exception:
            pass

    # 2) Sum up attributes like lines-covered / lines-valid across the document
    covered = 0
    valid = 0
    for el in root.iter():
        c = el.attrib.get("lines-covered") or el.attrib.get("covered")
        v = (
            el.attrib.get("lines-valid")
            or el.attrib.get("valid")
            or el.attrib.get("lines_total")
            or el.attrib.get("lines-total")
        )
        if c is not None and v is not None:
            try:
                covered += int(float(c))
                valid += int(float(v))
            except Exception:
                pass
    if valid > 0:
        return (covered / valid) * 100.0

    # 3) Try any element with line-rate attribute
    for el in root.iter():
        lr = el.attrib.get("line-rate")
        if lr is not None:
            try:
                return float(lr) * 100.0
            except Exception:
                pass

    return None


def find_low_coverage_filenames(path: str, threshold: float = 80.0) -> list[str]:
    """Return a list of filenames present in the coverage XML with line-rate < threshold."""
    try:
        tree = ET.parse(path)
    except Exception:
        return []
    root = tree.getroot()

    low: list[str] = []
    for el in root.iter():
        fn = el.attrib.get("filename")
        if not fn:
            continue
        lr = el.attrib.get("line-rate")
        if lr is None:
            continue
        try:
            pct = float(lr) * 100.0
        except Exception:
            continue
        if pct < threshold:
            low.append(fn)
    return low


def main() -> int:
    # locate coverage.xml relative to this script
    script_dir = os.path.dirname(os.path.abspath(__file__))
    coverage_path = os.path.abspath(os.path.join(script_dir, '..', 'reports', 'coverage.xml'))

    if not os.path.exists(coverage_path):
        print(f"FAIL: coverage.xml not found at {coverage_path}")
        return 1

    try:
        size = os.path.getsize(coverage_path)
    except Exception as e:
        print(f"FAIL: cannot stat coverage.xml: {e}")
        return 1

    if size == 0:
        print("FAIL: no content on coverage.xml")
        return 1

    pct = coverage_from_xml(coverage_path)
    if pct is None:
        print("FAIL: unable to determine line coverage from coverage.xml")
        return 1

    if pct < 80.0:
        low_files = find_low_coverage_filenames(coverage_path, 80.0)
        if low_files:
            # show first failing filename
            print(f"FAIL: {low_files[0]} coverage under 80% ({pct:.2f}%)")
        else:
            print(f"FAIL: {os.path.basename(coverage_path)} coverage under 80% ({pct:.2f}%)")
        return 1

    print("OK: coverage check passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
