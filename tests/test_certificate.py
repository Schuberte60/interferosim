# tests/test_certificate.py -- tests of tools/testzertifikat.py (test certificates)
"""Tests of the project-independent test certificate tool ``tools/testzertifikat.py``.

The tool is a stand-alone script (Python standard library only, shared with
AAS7), not part of the package; it is loaded from its file. The tests use
small JUnit XML and AAS7 JSON test logs written to ``tmp_path`` and switch
the PDF off (``pdf=False``) so that they do not depend on a LaTeX
installation.

Version 1.0.5 (2026-11-25): first version.
"""

import csv
import hashlib
import importlib.util
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parents[1] / "tools" / "testzertifikat.py"
NOW = datetime(2026, 11, 25, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def tz():
    """The tool loaded as a module."""
    spec = importlib.util.spec_from_file_location("testzertifikat", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def junit(path: Path, failures: int = 0, skipped: int = 0, passed: int = 3) -> Path:
    """Write a JUnit XML test log with the given numbers of results."""
    cases = [f'<testcase classname="tests.test_a" name="test_ok_{i}" time="0.01"/>'
             for i in range(passed)]
    cases += [f'<testcase classname="tests.test_b" name="test_bad_{i}" time="0.02">'
              f'<failure message="assert 1 == 2">trace</failure></testcase>'
              for i in range(failures)]
    cases += [f'<testcase classname="tests.test_c" name="test_skip_{i}" time="0">'
              f'<skipped type="pytest.skip" message="no hardware"/></testcase>'
              for i in range(skipped)]
    n = passed + failures + skipped
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('<?xml version="1.0" encoding="utf-8"?><testsuites><testsuite name="pytest" '
                    f'errors="0" failures="{failures}" skipped="{skipped}" tests="{n}" '
                    'time="1.5" timestamp="2026-11-25T11:59:00" hostname="pc">'
                    + "".join(cases) + "</testsuite></testsuites>", encoding="utf-8")
    return path


def test_passed_certificate_in_english(tz, tmp_path):
    log = junit(tmp_path / "junit.xml", passed=4, skipped=1)
    z = tz.erstelle_zertifikat(log=log, projekt_ordner=tmp_path, projekt="Interferosim",
                               ziel=tmp_path / "certificates", aussteller="E. Schubert",
                               pdf=False, jetzt=NOW, sprache="en")
    folder = Path(z["ordner"])
    assert z["auswertung"]["bestanden"]
    assert folder.name.startswith("TC_20261125_120000Z_Interferosim_")
    assert {p.name for p in folder.iterdir()} == {"zertifikat.html", "zertifikat.tex",
                                                  "zertifikat.json", "testprotokoll.xml"}
    page = (folder / "zertifikat.html").read_text(encoding="utf-8")
    assert "PASSED" in page and "Test certificate" in page and 'lang="en"' in page
    assert "BESTANDEN" not in page
    data = json.loads((folder / "zertifikat.json").read_text(encoding="utf-8"))
    assert data["sprache"] == "en" and data["auswertung"]["zaehler"]["skip"] == 1


def test_checksum_belongs_to_the_enclosed_copy(tz, tmp_path):
    log = junit(tmp_path / "junit.xml")
    z = tz.erstelle_zertifikat(log=log, projekt_ordner=tmp_path, ziel=tmp_path / "c",
                               pdf=False, jetzt=NOW, sprache="en")
    copy = Path(z["ordner"]) / "testprotokoll.xml"
    assert copy.read_bytes() == log.read_bytes()
    assert hashlib.sha256(copy.read_bytes()).hexdigest() == z["sha256"]
    assert Path(z["ordner"]).name.endswith(z["sha256"][:6])


def test_failure_gives_failed_certificate_with_reason(tz, tmp_path):
    log = junit(tmp_path / "junit.xml", failures=2)
    z = tz.erstelle_zertifikat(log=log, projekt_ordner=tmp_path, ziel=tmp_path / "c",
                               pdf=False, jetzt=NOW, sprache="en")
    a = z["auswertung"]
    assert not a["bestanden"]
    assert a["gruende"] == ["2 test(s) failed"]
    assert len(a["probleme"]) == 2
    tex = (Path(z["ordner"]) / "zertifikat.tex").read_text(encoding="utf-8")
    assert "FAILED" in tex and r"\section*{Failed tests}" in tex


def test_skipped_tests_do_not_fail_but_min_tests_does(tz, tmp_path):
    log = junit(tmp_path / "junit.xml", passed=2, skipped=5)
    ok = tz.erstelle_zertifikat(log=log, projekt_ordner=tmp_path, ziel=tmp_path / "c",
                                pdf=False, jetzt=NOW, sprache="en")
    assert ok["auswertung"]["bestanden"]
    strict = tz.erstelle_zertifikat(log=log, projekt_ordner=tmp_path, ziel=tmp_path / "c",
                                    pdf=False, jetzt=NOW, sprache="en", min_tests=10)
    assert not strict["auswertung"]["bestanden"]
    assert strict["auswertung"]["gruende"] == ["only 7 test(s), at least 10 required"]


def test_folders_are_never_overwritten_and_history_grows(tz, tmp_path):
    log = junit(tmp_path / "junit.xml")
    names = [Path(tz.erstelle_zertifikat(log=log, projekt_ordner=tmp_path, ziel=tmp_path / "c",
                                         pdf=False, jetzt=NOW, sprache="en")["ordner"]).name
             for _ in range(3)]
    assert names[1] == names[0] + "_2" and names[2] == names[0] + "_3"
    with (tmp_path / "c" / "verlauf.csv").open(encoding="utf-8") as f:
        rows = list(csv.reader(f, delimiter=";"))
    assert rows[0][:4] == ["certificate_no", "issued_utc", "project", "result"]
    assert [r[0] for r in rows[1:]] == names
    assert all(r[3] == "PASSED" for r in rows[1:])


def test_strict_mode_rejects_uncommitted_state(tz, tmp_path):
    log = tmp_path / "pytest_20261125.json"
    log.write_text(json.dumps({"lauf": {"zeit_utc": "2026-11-25T10:00:00+00:00",
                                        "branch": "main", "commit": "abc1234",
                                        "geaendert": True},
                               "tests": [{"nodeid": "tests/test_a.py::t", "ergebnis": "ok"}]}),
                   encoding="utf-8")
    normal = tz.erstelle_zertifikat(log=log, projekt_ordner=tmp_path, ziel=tmp_path / "c",
                                    pdf=False, jetzt=NOW, sprache="en")
    strict = tz.erstelle_zertifikat(log=log, projekt_ordner=tmp_path, ziel=tmp_path / "c",
                                    pdf=False, jetzt=NOW, sprache="en", streng=True)
    assert normal["auswertung"]["bestanden"] and normal["format"] == "AAS7-JSON"
    assert strict["auswertung"]["gruende"] == ["test run on an uncommitted state (--streng)"]


def test_newest_junit_log_is_found_without_log_argument(tz, tmp_path):
    old = junit(tmp_path / "logs" / "tests" / "junit_old.xml", failures=1)
    new = junit(tmp_path / "logs" / "tests" / "junit_new.xml")
    os.utime(old, (1_000_000, 1_000_000))
    assert tz.neuestes_protokoll(tmp_path) == new
    # an AAS7 JSON log keeps priority over JUnit XML (behaviour of version 1.0.0)
    aas7 = tmp_path / "logs" / "tests" / "pytest_20261125_100000.json"
    aas7.write_text('{"lauf": {}, "tests": []}', encoding="utf-8")
    assert tz.neuestes_protokoll(tmp_path) == aas7


def test_german_remains_the_default(tz, tmp_path):
    log = junit(tmp_path / "junit.xml", failures=1)
    z = tz.erstelle_zertifikat(log=log, projekt_ordner=tmp_path, pdf=False, jetzt=NOW)
    assert Path(z["ordner"]).parent == tmp_path.resolve() / "zertifikate"
    assert Path(z["ordner"]).name.startswith("TZ_")
    assert z["titel"] == "Testzertifikat"
    assert z["auswertung"]["gruende"] == ["1 Test(s) fehlgeschlagen"]


def test_command_line_exit_codes(tz, tmp_path, capsys):
    good = junit(tmp_path / "good.xml")
    bad = junit(tmp_path / "bad.xml", failures=1)
    common = ["--projekt-ordner", str(tmp_path), "--ziel", str(tmp_path / "c"), "--kein-pdf",
              "--sprache", "en"]
    assert tz.main(["--log", str(good), *common]) == 0
    assert "PASSED" in capsys.readouterr().out
    assert tz.main(["--log", str(bad), *common]) == 1
    assert tz.main(["--log", str(tmp_path / "missing.xml"), *common]) == 2
    assert "test log" in capsys.readouterr().err


def test_unreadable_log_is_an_input_error(tz, tmp_path):
    broken = tmp_path / "broken.xml"
    broken.write_text("<testsuites><testsuite>", encoding="utf-8")
    with pytest.raises(tz.EingabeFehler, match="not a readable XML file"):
        tz.erstelle_zertifikat(log=broken, projekt_ordner=tmp_path, ziel=tmp_path / "c",
                               pdf=False, sprache="en")
    with pytest.raises(ValueError):
        tz.erstelle_zertifikat(log=broken, projekt_ordner=tmp_path, pdf=False, sprache="fr")
