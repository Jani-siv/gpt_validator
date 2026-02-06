import os
from pathlib import Path
import xml.etree.ElementTree as ET

import agent.zephyr_verify_coverage as zv


REPORTS_DIR = Path(__file__).resolve().parents[2] / 'reports'
COVERAGE_PATH = REPORTS_DIR / 'coverage.xml'


def setup_file(content: str | None):
    REPORTS_DIR.mkdir(exist_ok=True)
    if content is None:
        # remove file if exists
        if COVERAGE_PATH.exists():
            COVERAGE_PATH.unlink()
        return
    COVERAGE_PATH.write_text(content)


def test_coverage_from_xml_root_line_rate(tmp_path):
    xml = '<coverage line-rate="0.85"></coverage>'
    p = tmp_path / 'c.xml'
    p.write_text(xml)
    assert zv.coverage_from_xml(str(p)) == pytest_float(85.0)


def test_coverage_from_xml_sum_attrs(tmp_path):
    xml = '<coverage><file lines-covered="3" lines-valid="4" /></coverage>'
    p = tmp_path / 'c2.xml'
    p.write_text(xml)
    assert zv.coverage_from_xml(str(p)) == pytest_float(75.0)


def test_coverage_from_xml_element_line_rate(tmp_path):
    xml = '<coverage><package line-rate="0.5"/></coverage>'
    p = tmp_path / 'c3.xml'
    p.write_text(xml)
    assert zv.coverage_from_xml(str(p)) == pytest_float(50.0)


def test_coverage_from_xml_malformed(tmp_path):
    p = tmp_path / 'bad.xml'
    p.write_text('not xml')
    assert zv.coverage_from_xml(str(p)) is None


def test_find_low_coverage_filenames(tmp_path):
    xml = '<coverage>'
    xml += '<file filename="a.c" line-rate="0.9"/>'
    xml += '<file filename="b.c" line-rate="0.5"/>'
    xml += '</coverage>'
    p = tmp_path / 'c4.xml'
    p.write_text(xml)
    low = zv.find_low_coverage_filenames(str(p), threshold=80.0)
    assert low == ['b.c']


def pytest_float(val: float):
    # helper to allow float comparison tolerant to tiny FP fluctuations
    return pytest_float_wrapper(val)


class pytest_float_wrapper:
    def __init__(self, v):
        self.v = v

    def __eq__(self, other):
        return abs(other - self.v) < 1e-6


def test_main_missing_and_empty_and_invalid(tmp_path, capsys):
    # backup existing
    bak = None
    if COVERAGE_PATH.exists():
        bak = COVERAGE_PATH.read_text()
        COVERAGE_PATH.unlink()

    try:
        # missing file
        if COVERAGE_PATH.exists():
            COVERAGE_PATH.unlink()
        rc = zv.main()
        out = capsys.readouterr().out
        assert rc == 1
        assert 'coverage.xml not found' in out

        # empty file
        setup_file('')
        rc = zv.main()
        out = capsys.readouterr().out
        assert rc == 1
        assert 'no content on coverage.xml' in out

        # invalid xml
        setup_file('not xml')
        rc = zv.main()
        out = capsys.readouterr().out
        assert rc == 1
        assert 'unable to determine line coverage' in out
    finally:
        # restore
        if bak is not None:
            COVERAGE_PATH.write_text(bak)
        else:
            if COVERAGE_PATH.exists():
                COVERAGE_PATH.unlink()


def test_main_low_and_ok(tmp_path, capsys):
    # create low coverage with filename
    xml = '<coverage line-rate="0.5"><file filename="low.c" line-rate="0.5"/></coverage>'
    setup_file(xml)
    rc = zv.main()
    out = capsys.readouterr().out
    assert rc == 1
    assert 'low.c coverage under 80%' in out

    # create low coverage without filenames
    xml = '<coverage line-rate="0.5"></coverage>'
    setup_file(xml)
    rc = zv.main()
    out = capsys.readouterr().out
    assert rc == 1
    assert 'coverage.xml coverage under 80%' in out or 'coverage under 80%' in out

    # ok coverage
    xml = '<coverage line-rate="0.95"></coverage>'
    setup_file(xml)
    rc = zv.main()
    out = capsys.readouterr().out
    assert rc == 0
    assert 'OK: coverage check passed' in out
