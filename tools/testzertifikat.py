#!/usr/bin/env python3
# tools/testzertifikat.py
# Status: AKTIV
# Beschreibung: Universelle Erstellung eines TESTZERTIFIKATS aus einem
#               Testprotokoll (Nutzer 25.11.2026: "universelle Zertifikats-
#               erstellungsfunktion, welche auf Basis von Testlogs ein
#               Zertifikat erstellt. Die Datei soll auch fuer andere
#               Projekte verwendbar sein. Das Zertifikat ist in ein eigenes
#               Verzeichnis mit eindeutigem Namen abzulegen (=> History)").
#               - NUR Python-Standardbibliothek (>= 3.8), keine Projekt-
#                 Importe -> die Datei kann unveraendert in jedes Projekt
#                 kopiert werden.
#               - Eingabe (automatisch erkannt):
#                 a) AAS7-Testprotokoll logs/tests/pytest_*.json (conftest.py
#                    1.1.0: {"lauf": {...}, "tests": [...]}),
#                 b) JUnit-XML (pytest --junitxml=..., ebenso viele andere
#                    Test-Werkzeuge: <testsuites>/<testsuite>/<testcase>).
#                 Ohne Angabe: das neueste logs/tests/pytest_*.json im
#                 Projektordner.
#               - Ergebnis BESTANDEN, wenn mindestens --min-tests Tests
#                 gelaufen sind und keiner fehlgeschlagen ist (fehler = 0,
#                 error = 0). skip/xfail zaehlen nicht als Fehler. Mit
#                 --streng zusaetzlich: kein nicht committeter Stand
#                 ("geaendert") und kein xpass.
#               - Ausgabe in <ziel>/<Zertifikat-Nr.>/ (Vorgabe <projekt>/
#                 zertifikate/), Name eindeutig:
#                   TZ_<JJJJMMTT_hhmmss>Z_<projekt>_<branch>_<commit>_<pruef6>
#                 (Ausstellungszeit UTC + erste 6 Zeichen der SHA-256-
#                 Pruefsumme des Protokolls; bestehende Ordner werden nie
#                 ueberschrieben, notfalls Zusatz _2, _3, ...). Inhalt:
#                   zertifikat.html  (immer, ohne weitere Programme lesbar)
#                   zertifikat.tex   (immer) und zertifikat.pdf (wenn
#                                    pdflatex gefunden wird, --kein-pdf
#                                    schaltet ab)
#                   zertifikat.json  (alle Angaben maschinenlesbar)
#                   testprotokoll.json|.xml (unveraenderte Kopie, Pruefsumme
#                                    im Zertifikat)
#                 und eine Zeile in <ziel>/verlauf.csv (History aller
#                 Zertifikate).
#               - Alle Zeiten in UTC.
#               Rueckgabecode: 0 BESTANDEN, 1 NICHT BESTANDEN, 2 Eingabe-
#               fehler (Protokoll fehlt/unlesbar).
#               Aufruf: python tools/testzertifikat.py [--log DATEI]
#                       [--projekt NAME] [--ziel ORDNER] [--titel TEXT]
#                       [--aussteller NAME] [--min-tests N] [--streng]
#                       [--kein-pdf] [--quiet] [--sprache de|en]
#
#               Neu in 1.1.0 (25.11.2026, uebernommen nach Interferosim,
#               Projektsprache Englisch):
#               - --sprache de|en (Vorgabe de): Sprache aller Ausgaben --
#                 HTML, TeX/PDF, Konsole, Spaltenkoepfe von verlauf.csv,
#                 Kennung im Ordnernamen (de TZ_, en TC_) und Vorgabe-
#                 Ablage (de zertifikate/, en certificates/). Mit de (oder
#                 ohne Angabe) ist das Ergebnis genau wie in 1.0.0; AAS7
#                 kann 1.1.0 daher unveraendert uebernehmen.
#               - Ohne --log: gibt es kein logs/tests/pytest_*.json, wird
#                 das neueste JUnit-XML logs/tests/*.xml genommen (z. B.
#                 aus "pytest --junitxml=logs/tests/junit.xml"). Ein
#                 vorhandenes AAS7-JSON hat weiterhin Vorrang.
#               - Die Schluessel von zertifikat.json bleiben deutsch
#                 (festes Format fuer Auswertungen); neu ist der Schluessel
#                 "sprache".
#               Usage (English): python tools/testzertifikat.py --sprache en
#                       [--log FILE] [--ziel DIR] ... -- writes a test
#                       certificate (HTML, TeX/PDF, JSON, copy of the log)
#                       into its own uniquely named folder and appends a
#                       line to verlauf.csv. Exit code 0 PASSED, 1 FAILED,
#                       2 input error.
# Version: 1.1.0
#   1.1.0 (25.11.2026): --sprache de|en; JUnit-XML als Vorgabe-Protokoll,
#         wenn kein AAS7-JSON vorhanden ist
#   1.0.0: erste Fassung (AAS7)

from __future__ import annotations

__VERSION__ = "1.1.0"

import argparse
import csv
import getpass
import hashlib
import html
import json
import platform
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path

ERGEBNISSE = ("ok", "fehler", "error", "skip", "xfail", "xpass")
ERGEBNIS_TEXT = {"ok": "bestanden", "fehler": "fehlgeschlagen", "error": "Fehler (Aufbau)",
                 "skip": "übersprungen", "xfail": "erwarteter Fehler", "xpass": "unerwartet bestanden"}
VERLAUF_KOPF = ["zertifikat_nr", "ausgestellt_utc", "projekt", "ergebnis", "testlauf_utc",
                "branch", "commit", "geaendert", "gesamt", "ok", "fehler", "error", "skip",
                "xfail", "xpass", "dauer_s", "sha256", "pdf", "aussteller"]
MAX_LISTE = 50                       # hoechstens so viele Fehler im Zertifikat einzeln

# 1.1.0: Ausgabesprachen. "de" gibt genau die Texte von 1.0.0 aus; "en" ist
# die englische Entsprechung (Interferosim). Neue Texte immer in beiden
# Sprachen eintragen.
SPRACHEN = ("de", "en")
ERGEBNIS_TEXT_EN = {"ok": "passed", "fehler": "failed", "error": "error (setup)",
                    "skip": "skipped", "xfail": "expected failure", "xpass": "unexpectedly passed"}
VERLAUF_KOPF_EN = ["certificate_no", "issued_utc", "project", "result", "test_run_utc",
                   "branch", "commit", "uncommitted", "total", "passed", "failed", "error",
                   "skipped", "xfail", "xpass", "duration_s", "sha256", "pdf", "issuer"]
TEXTE = {
    "de": {
        "titel": "Testzertifikat", "kennung": "TZ", "ablage": "zertifikate",
        "bestanden": "BESTANDEN", "nicht_bestanden": "NICHT BESTANDEN",
        "ja": "ja", "nein": "nein", "ohne_branch": "ohne-branch", "ohne_commit": "ohne-commit",
        "k_nr": "Zertifikat-Nr.", "k_projekt": "Projekt", "k_ausgestellt": "Ausgestellt (UTC)",
        "k_aussteller": "Aussteller", "k_lauf": "Testlauf (UTC)", "k_dauer": "Dauer",
        "k_branch": "Branch / Commit", "k_geaendert": "Nicht committete Änderungen",
        "k_python": "Python / System", "k_rechner": "Rechner", "k_aufruf": "Aufruf",
        "k_auswahl": "Auswahl (Marker)", "k_protokoll": "Protokoll",
        "k_sha": "SHA-256 des Protokolls", "k_kriterien": "Kriterien", "k_ergebnis": "Ergebnis",
        "auswahl_alle": "alle",
        "kriterien": "mindestens {n} Test(s), keine Fehlschläge", "streng": ", streng",
        "g_min": "nur {g} Test(s), verlangt mindestens {n}",
        "g_fehler": "{n} Test(s) fehlgeschlagen",
        "g_error": "{n} Test(s) mit Fehler im Aufbau",
        "g_geaendert": "Testlauf auf nicht committetem Stand (--streng)",
        "g_xpass": "{n} Test(s) unerwartet bestanden (--streng)",
        "gruende": "Gründe:", "zusammenfassung": "Zusammenfassung", "gesamt": "Tests gesamt",
        "je_datei": "Ergebnis je Testdatei", "datei": "Datei",
        "fehlgeschlagen": "Fehlgeschlagene Tests", "weitere": "… und {n} weitere",
        "fuss": ("Die SHA-256-Prüfsumme bezieht sich auf die beigelegte Datei {datei}; sie belegt, "
                 "dass das zugrunde liegende Testprotokoll unverändert ist. Erstellt mit "
                 "{werkzeug} {version}."),
        "e_kein_json": "{d}: kein lesbares JSON ({e})",
        "e_kein_prot": "{d}: kein Testprotokoll (Schluessel 'tests' fehlt)",
        "e_kein_xml": "{d}: kein lesbares XML ({e})",
        "e_kein_junit": "{d}: kein JUnit-XML (testsuite fehlt)",
        "e_fehlt": "Testprotokoll {p} nicht gefunden",
        "e_keins": ("kein Testprotokoll unter {p} -- zuerst die Tests laufen lassen oder --log "
                    "angeben"),
        "c_fehler": "FEHLER", "c_tests": "{g} Tests (ok {ok}, fehler {f}, error {e}, skip {s}, "
                                         "xfail {x})",
        "c_zertifikat": "Zertifikat", "c_kein_pdf": "kein PDF",
        "pdf_ok": "ok", "pdf_kein": "kein pdflatex", "pdf_nicht": "pdflatex nicht ausfuehrbar",
        "pdf_fehler": "pdflatex-Fehler (siehe zertifikat.log)", "pdf_leer": "kein PDF entstanden",
        "pdf_aus": "abgeschaltet (--kein-pdf)",
    },
    "en": {
        "titel": "Test certificate", "kennung": "TC", "ablage": "certificates",
        "bestanden": "PASSED", "nicht_bestanden": "FAILED",
        "ja": "yes", "nein": "no", "ohne_branch": "no-branch", "ohne_commit": "no-commit",
        "k_nr": "Certificate no.", "k_projekt": "Project", "k_ausgestellt": "Issued (UTC)",
        "k_aussteller": "Issued by", "k_lauf": "Test run (UTC)", "k_dauer": "Duration",
        "k_branch": "Branch / commit", "k_geaendert": "Uncommitted changes",
        "k_python": "Python / system", "k_rechner": "Host", "k_aufruf": "Command",
        "k_auswahl": "Selection (markers)", "k_protokoll": "Test log",
        "k_sha": "SHA-256 of the test log", "k_kriterien": "Criteria", "k_ergebnis": "Result",
        "auswahl_alle": "all",
        "kriterien": "at least {n} test(s), no failures", "streng": ", strict",
        "g_min": "only {g} test(s), at least {n} required",
        "g_fehler": "{n} test(s) failed",
        "g_error": "{n} test(s) with an error in setup",
        "g_geaendert": "test run on an uncommitted state (--streng)",
        "g_xpass": "{n} test(s) passed unexpectedly (--streng)",
        "gruende": "Reasons:", "zusammenfassung": "Summary", "gesamt": "Tests in total",
        "je_datei": "Result per test file", "datei": "File",
        "fehlgeschlagen": "Failed tests", "weitere": "… and {n} more",
        "fuss": ("The SHA-256 checksum refers to the enclosed file {datei}; it shows that the "
                 "underlying test log is unchanged. Created with {werkzeug} {version}."),
        "e_kein_json": "{d}: not a readable JSON file ({e})",
        "e_kein_prot": "{d}: not a test log (key 'tests' missing)",
        "e_kein_xml": "{d}: not a readable XML file ({e})",
        "e_kein_junit": "{d}: not a JUnit XML file (testsuite missing)",
        "e_fehlt": "test log {p} not found",
        "e_keins": ("no test log in {p} -- run the tests first (e.g. pytest "
                    "--junitxml=logs/tests/junit.xml) or pass --log"),
        "c_fehler": "ERROR", "c_tests": "{g} tests (passed {ok}, failed {f}, error {e}, "
                                        "skipped {s}, xfail {x})",
        "c_zertifikat": "Certificate", "c_kein_pdf": "no PDF",
        "pdf_ok": "ok", "pdf_kein": "no pdflatex", "pdf_nicht": "pdflatex cannot be run",
        "pdf_fehler": "pdflatex error (see zertifikat.log)", "pdf_leer": "no PDF produced",
        "pdf_aus": "switched off (--kein-pdf)",
    },
}


def _t(sprache: str, schluessel: str, **werte) -> str:
    """1.1.0: Text in der gewaehlten Sprache (unbekannte Sprache -> de)."""
    text = TEXTE.get(sprache, TEXTE["de"])[schluessel]
    return text.format(**werte) if werte else text


def _ergebnis_text(sprache: str) -> dict:
    return ERGEBNIS_TEXT_EN if sprache == "en" else ERGEBNIS_TEXT


class EingabeFehler(Exception):
    pass


# ----------------------------------------------------------------------
# Hilfen
# ----------------------------------------------------------------------
def _git(ordner: Path, *args) -> str:
    try:
        r = subprocess.run(["git", *args], cwd=str(ordner), capture_output=True, text=True,
                           timeout=10)
        return r.stdout.strip() if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def _sha256(pfad: Path) -> str:
    h = hashlib.sha256()
    with pfad.open("rb") as f:
        for block in iter(lambda: f.read(1 << 16), b""):
            h.update(block)
    return h.hexdigest()


def _sicher(text: str, laenge: int = 40) -> str:
    """Bestandteil fuer Ordnernamen: nur Buchstaben, Ziffern, - und ."""
    s = "".join(c if (c.isalnum() and c.isascii()) or c in "-." else "-" for c in str(text))
    while "--" in s:
        s = s.replace("--", "-")
    return s.strip("-.")[:laenge] or "x"


def _datei_von(nodeid: str) -> str:
    return nodeid.split("::", 1)[0] if "::" in nodeid else (nodeid.rsplit(".", 1)[0] or nodeid)


def _zeit(txt) -> datetime | None:
    if not txt:
        return None
    try:
        t = datetime.fromisoformat(str(txt).replace("Z", "+00:00"))
    except ValueError:
        return None
    return (t if t.tzinfo else t.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


# ----------------------------------------------------------------------
# Protokolle lesen -> einheitliches Format
# ----------------------------------------------------------------------
def lies_aas7_json(pfad: Path, sprache: str = "de") -> dict:
    try:
        d = json.loads(pfad.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as e:
        raise EingabeFehler(_t(sprache, "e_kein_json", d=pfad.name, e=e))
    if not isinstance(d, dict) or not isinstance(d.get("tests"), list):
        raise EingabeFehler(_t(sprache, "e_kein_prot", d=pfad.name))
    lauf = d.get("lauf") or {}
    tests = []
    for t in d["tests"]:
        erg = t.get("ergebnis") if t.get("ergebnis") in ERGEBNISSE else "error"
        tests.append({"name": str(t.get("nodeid", "?")), "ergebnis": erg,
                      "dauer_s": float(t.get("dauer_s") or 0.0), "grund": t.get("grund")})
    return {"format": "AAS7-JSON", "lauf": {
        "zeit_utc": lauf.get("zeit_utc"), "dauer_s": lauf.get("dauer_s"),
        "branch": lauf.get("branch"), "commit": lauf.get("commit"),
        "geaendert": lauf.get("geaendert"), "python": lauf.get("python"),
        "rechner": lauf.get("rechner"), "system": lauf.get("system"),
        "aufruf": lauf.get("aufruf"), "auswahl": lauf.get("auswahl")}, "tests": tests}


def lies_junit_xml(pfad: Path, sprache: str = "de") -> dict:
    try:
        wurzel = ET.parse(str(pfad)).getroot()
    except (OSError, ET.ParseError) as e:
        raise EingabeFehler(_t(sprache, "e_kein_xml", d=pfad.name, e=e))
    suiten = [wurzel] if wurzel.tag == "testsuite" else list(wurzel.iter("testsuite"))
    if not suiten:
        raise EingabeFehler(_t(sprache, "e_kein_junit", d=pfad.name))
    tests, dauer, zeit, rechner = [], 0.0, None, None
    for s in suiten:
        dauer += float(s.get("time") or 0.0)
        zeit = zeit or s.get("timestamp")
        rechner = rechner or s.get("hostname")
        for tc in s.iter("testcase"):
            kl, nm = tc.get("classname") or "", tc.get("name") or "?"
            name = f"{kl}::{nm}" if kl else nm
            erg, grund = "ok", None
            for kind, e in (("fehler", "failure"), ("error", "error"), ("skip", "skipped")):
                el = tc.find(e)
                if el is not None:
                    erg = kind
                    grund = (el.get("message") or (el.text or "")).strip()[:2000] or None
                    if kind == "skip" and (el.get("type") or "").endswith("xfail"):
                        erg = "xfail"
                    break
            tests.append({"name": name, "ergebnis": erg, "dauer_s": float(tc.get("time") or 0.0),
                          "grund": grund})
    t = _zeit(zeit)                                  # JUnit-Zeitstempel -> UTC
    return {"format": "JUnit-XML", "lauf": {
        "zeit_utc": t.isoformat(timespec="seconds") if t else zeit, "dauer_s": round(dauer, 3), "branch": None, "commit": None,
        "geaendert": None, "python": None, "rechner": rechner, "system": None,
        "aufruf": None, "auswahl": None}, "tests": tests}


def lies_protokoll(pfad: Path, sprache: str = "de") -> dict:
    if not pfad.is_file():
        raise EingabeFehler(_t(sprache, "e_fehlt", p=pfad))
    if pfad.suffix.lower() == ".xml":
        return lies_junit_xml(pfad, sprache)
    return lies_aas7_json(pfad, sprache)


def neuestes_protokoll(projekt_ordner: Path, sprache: str = "de") -> Path:
    ordner = projekt_ordner / "logs" / "tests"
    kandidaten = sorted(ordner.glob("pytest_*.json"))
    if kandidaten:
        return kandidaten[-1]
    # 1.1.0: ohne AAS7-JSON das zuletzt geaenderte JUnit-XML (pytest --junitxml)
    xml = sorted(ordner.glob("*.xml"), key=lambda p: (p.stat().st_mtime, p.name))
    if xml:
        return xml[-1]
    raise EingabeFehler(_t(sprache, "e_keins", p=ordner))


# ----------------------------------------------------------------------
# Auswertung
# ----------------------------------------------------------------------
def auswerten(prot: dict, min_tests: int = 1, streng: bool = False, sprache: str = "de") -> dict:
    z = OrderedDict((k, 0) for k in ERGEBNISSE)
    je_datei: "OrderedDict[str, OrderedDict]" = OrderedDict()
    for t in prot["tests"]:
        z[t["ergebnis"]] += 1
        d = je_datei.setdefault(_datei_von(t["name"]), OrderedDict((k, 0) for k in ERGEBNISSE))
        d[t["ergebnis"]] += 1
    gesamt = len(prot["tests"])
    gruende = []
    if gesamt < max(1, min_tests):
        gruende.append(_t(sprache, "g_min", g=gesamt, n=max(1, min_tests)))
    if z["fehler"]:
        gruende.append(_t(sprache, "g_fehler", n=z["fehler"]))
    if z["error"]:
        gruende.append(_t(sprache, "g_error", n=z["error"]))
    if streng and prot["lauf"].get("geaendert"):
        gruende.append(_t(sprache, "g_geaendert"))
    if streng and z["xpass"]:
        gruende.append(_t(sprache, "g_xpass", n=z["xpass"]))
    probleme = [t for t in prot["tests"] if t["ergebnis"] in ("fehler", "error")]
    return {"bestanden": not gruende, "gruende": gruende, "gesamt": gesamt, "zaehler": z,
            "je_datei": je_datei, "probleme": probleme}


# ----------------------------------------------------------------------
# Ausgabe
# ----------------------------------------------------------------------
def _tex(s) -> str:
    s = "" if s is None else str(s)
    tausch = {"\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#",
              "_": r"\_", "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}",
              "^": r"\textasciicircum{}", "<": r"\textless{}", ">": r"\textgreater{}"}
    return "".join(tausch.get(c, c) for c in s)


def _ja_nein(v, sprache: str = "de") -> str:
    return "–" if v is None else (_t(sprache, "ja") if v else _t(sprache, "nein"))


def _urteil(bestanden: bool, sprache: str = "de") -> str:
    """1.1.0: BESTANDEN / NICHT BESTANDEN bzw. PASSED / FAILED."""
    return _t(sprache, "bestanden") if bestanden else _t(sprache, "nicht_bestanden")


def _zeilen_kopf(z: dict) -> list:
    """(Bezeichnung, Wert) fuer die Angaben-Tabelle."""
    l, a, s = z["lauf"], z["auswertung"], z.get("sprache", "de")
    return [
        (_t(s, "k_nr"), z["nr"]),
        (_t(s, "k_projekt"), z["projekt"]),
        (_t(s, "k_ausgestellt"), z["ausgestellt_utc"]),
        (_t(s, "k_aussteller"), z["aussteller"]),
        (_t(s, "k_lauf"), l.get("zeit_utc") or "–"),
        (_t(s, "k_dauer"), f"{float(l['dauer_s']):.1f} s" if l.get("dauer_s") is not None else "–"),
        (_t(s, "k_branch"), f"{l.get('branch') or '–'} / {l.get('commit') or '–'}"),
        (_t(s, "k_geaendert"), _ja_nein(l.get("geaendert"), s)),
        (_t(s, "k_python"), f"{l.get('python') or '–'} / {l.get('system') or '–'}"),
        (_t(s, "k_rechner"), l.get("rechner") or "–"),
        (_t(s, "k_aufruf"), l.get("aufruf") or "–"),
        (_t(s, "k_auswahl"), l.get("auswahl") or _t(s, "auswahl_alle")),
        (_t(s, "k_protokoll"), f"{z['protokoll_datei']} ({z['format']})"),
        (_t(s, "k_sha"), z["sha256"]),
        (_t(s, "k_kriterien"), _t(s, "kriterien", n=z["min_tests"])
                               + (_t(s, "streng") if z["streng"] else "")),
        (_t(s, "k_ergebnis"), _urteil(a["bestanden"], s)),
    ]


def schreibe_tex(z: dict, pfad: Path) -> None:
    a = z["auswertung"]
    s = z.get("sprache", "de")
    et = _ergebnis_text(s)
    sha_kopf = _t(s, "k_sha")
    farbe = "gruen" if a["bestanden"] else "rot"
    # 1.1.0: Silbentrennung passend zur Sprache (nur wenn babel-Datei vorhanden)
    babel = (r"\IfFileExists{english.ldf}{\usepackage[english]{babel}}{}" if s == "en" else
             r"\IfFileExists{ngerman.ldf}{\usepackage[ngerman]{babel}}{}")
    zeilen = [r"% zertifikat.tex -- erzeugt von tools/testzertifikat.py " + __VERSION__,
              r"\documentclass[a4paper,11pt]{article}",
              r"\usepackage[T1]{fontenc}", r"\usepackage[utf8]{inputenc}", r"\usepackage{lmodern}",
              # Silbentrennung Deutsch nur, wenn babel-ngerman installiert ist
              babel,
              r"\usepackage[margin=2cm]{geometry}",
              r"\usepackage{booktabs,longtable,array}", r"\usepackage[table]{xcolor}",
              r"\usepackage{seqsplit}",
              r"\definecolor{gruen}{RGB}{32,128,64}\definecolor{rot}{RGB}{176,32,32}",
              r"\pagestyle{plain}\setlength{\parindent}{0pt}",
              r"\begin{document}",
              r"\begin{center}{\Huge\bfseries " + _tex(z["titel"]) + r"}\\[4pt]",
              r"{\Large " + _tex(z["projekt"]) + r"}\\[14pt]",
              r"\fcolorbox{" + farbe + r"}{white}{\parbox{0.6\textwidth}{\centering\vspace{4pt}"
              r"{\Huge\bfseries\color{" + farbe + "}" +
              _urteil(a["bestanden"], s) + r"}\vspace{4pt}}}",
              r"\end{center}\vspace{10pt}"]
    if a["gruende"]:
        zeilen.append(r"\textbf{" + _tex(_t(s, "gruende")) + r"} " + _tex("; ".join(a["gruende"]))
                      + r"\par\medskip")
    zeilen += [r"\begin{longtable}{>{\bfseries\raggedright\arraybackslash}p{5.4cm}"
               r">{\raggedright\arraybackslash}p{11cm}}", r"\toprule"]
    for k, v in _zeilen_kopf(z):
        wert = r"\texttt{\seqsplit{" + _tex(v) + "}}" if k == sha_kopf else _tex(v)
        zeilen.append(_tex(k) + " & " + wert + r" \\")
    zeilen += [r"\bottomrule", r"\end{longtable}",
               r"\section*{" + _tex(_t(s, "zusammenfassung")) + "}",
               r"\begin{tabular}{lr}", r"\toprule"]
    zeilen.append(_tex(_t(s, "gesamt")) + " & " + str(a["gesamt"]) + r" \\ \midrule")
    for k in ERGEBNISSE:
        zeilen.append(_tex(et[k]) + " & " + str(a["zaehler"][k]) + r" \\")
    zeilen += [r"\bottomrule", r"\end{tabular}",
               r"\section*{" + _tex(_t(s, "je_datei")) + "}",
               r"\begin{longtable}{p{8.4cm}rrrrrr}", r"\toprule",
               _tex(_t(s, "datei")) + r" & ok & fehler & error & skip & xfail & xpass \\ "
               r"\midrule \endhead" if s == "de" else
               _tex(_t(s, "datei")) + r" & passed & failed & error & skipped & xfail & xpass \\ "
               r"\midrule \endhead"]
    for datei, d in a["je_datei"].items():
        zeilen.append(r"\texttt{\seqsplit{" + _tex(datei) + "}} & " +
                      " & ".join(str(d[k]) for k in ERGEBNISSE) + r" \\")
    zeilen += [r"\bottomrule", r"\end{longtable}"]
    if a["probleme"]:
        zeilen += [r"\section*{" + _tex(_t(s, "fehlgeschlagen")) + "}", r"\begin{itemize}"]
        for t in a["probleme"][:MAX_LISTE]:
            zeilen.append(r"\item \texttt{\seqsplit{" + _tex(t["name"]) + "}} -- " +
                          _tex(et[t["ergebnis"]]) +
                          (r"\\ {\small " + _tex((t["grund"] or "").splitlines()[0][:300]) + "}"
                           if t.get("grund") else ""))
        if len(a["probleme"]) > MAX_LISTE:
            zeilen.append(r"\item " + _tex(_t(s, "weitere", n=len(a["probleme"]) - MAX_LISTE)))
        zeilen.append(r"\end{itemize}")
    fuss = _t(s, "fuss", datei="@@DATEI@@", werkzeug="@@WERKZEUG@@", version=__VERSION__)
    fuss = (_tex(fuss).replace("@@DATEI@@", r"\texttt{" + _tex(z["kopie"]) + "}")
            .replace("@@WERKZEUG@@", r"\texttt{testzertifikat.py}"))
    zeilen += [r"\vfill{\small " + fuss + r"}", r"\end{document}", ""]
    pfad.write_text("\n".join(zeilen), encoding="utf-8")


def schreibe_html(z: dict, pfad: Path) -> None:
    a = z["auswertung"]
    s = z.get("sprache", "de")
    et = _ergebnis_text(s)
    sha_kopf = _t(s, "k_sha")
    e = html.escape
    farbe = "#208040" if a["bestanden"] else "#b02020"
    teile = ["<!doctype html>",
             f"<!-- zertifikat.html -- erzeugt von tools/testzertifikat.py {__VERSION__} -->",
             f'<html lang="{"en" if s == "en" else "de"}"><head><meta charset="utf-8">',
             f"<title>{e(z['titel'])} – {e(z['projekt'])}</title>",
             "<style>body{font-family:system-ui,'Segoe UI',sans-serif;max-width:900px;margin:24px auto;"
             "padding:0 16px;color:#17212b;background:#fff}h1{margin:0}table{border-collapse:collapse;"
             "width:100%;margin:8px 0 16px}td,th{border-bottom:1px solid #d8e0e7;padding:4px 8px;"
             "text-align:left;vertical-align:top}th{background:#f3f6f8}td.n{text-align:right}"
             f".erg{{border:3px solid {farbe};color:{farbe};font-size:2em;font-weight:700;"
             "text-align:center;padding:10px;margin:16px 0}code{word-break:break-all}"
             ".klein{color:#627181;font-size:.85em}</style></head><body>",
             f"<h1>{e(z['titel'])}</h1><div style='font-size:1.3em'>{e(z['projekt'])}</div>",
             f"<div class='erg'>{_urteil(a['bestanden'], s)}</div>"]
    if a["gruende"]:
        teile.append(f"<p><b>{e(_t(s, 'gruende'))}</b> {e('; '.join(a['gruende']))}</p>")
    teile.append("<table>")
    for k, v in _zeilen_kopf(z):
        teile.append(f"<tr><th>{e(k)}</th><td><code>{e(str(v))}</code></td></tr>"
                     if k == sha_kopf else f"<tr><th>{e(k)}</th><td>{e(str(v))}</td></tr>")
    teile.append(f"</table><h2>{e(_t(s, 'zusammenfassung'))}</h2><table>")
    teile.append(f"<tr><th>{e(_t(s, 'gesamt'))}</th><td class='n'>{a['gesamt']}</td></tr>")
    for k in ERGEBNISSE:
        teile.append(f"<tr><td>{e(et[k])}</td><td class='n'>{a['zaehler'][k]}</td></tr>")
    spalten = ERGEBNISSE if s == "de" else ("passed", "failed", "error", "skipped", "xfail", "xpass")
    teile.append(f"</table><h2>{e(_t(s, 'je_datei'))}</h2><table><tr><th>{e(_t(s, 'datei'))}</th>" +
                 "".join(f"<th>{k}</th>" for k in spalten) + "</tr>")
    for datei, d in a["je_datei"].items():
        teile.append(f"<tr><td><code>{e(datei)}</code></td>" +
                     "".join(f"<td class='n'>{d[k]}</td>" for k in ERGEBNISSE) + "</tr>")
    teile.append("</table>")
    if a["probleme"]:
        teile.append(f"<h2>{e(_t(s, 'fehlgeschlagen'))}</h2><ul>")
        for t in a["probleme"][:MAX_LISTE]:
            g = (t.get("grund") or "").splitlines()
            teile.append(f"<li><code>{e(t['name'])}</code> – {e(et[t['ergebnis']])}" +
                         (f"<br><span class='klein'>{e(g[0][:300])}</span>" if g else "") + "</li>")
        if len(a["probleme"]) > MAX_LISTE:
            teile.append(f"<li>{e(_t(s, 'weitere', n=len(a['probleme']) - MAX_LISTE))}</li>")
        teile.append("</ul>")
    fuss = e(_t(s, "fuss", datei="@@DATEI@@", werkzeug="testzertifikat.py", version=__VERSION__))
    teile.append("<p class='klein'>" + fuss.replace("@@DATEI@@", f"<code>{e(z['kopie'])}</code>") +
                 "</p></body></html>")
    pfad.write_text("\n".join(teile), encoding="utf-8")


def _pdflatex(tex: Path, sprache: str = "de") -> str:
    """'ok' | 'kein pdflatex' | 'pdflatex-Fehler (siehe zertifikat.log)' (en: englisch)."""
    exe = shutil.which("pdflatex")
    if not exe:
        return _t(sprache, "pdf_kein")
    for _ in range(2):                                   # zweimal wegen longtable
        try:
            r = subprocess.run([exe, "-interaction=nonstopmode", "-halt-on-error", tex.name],
                               cwd=str(tex.parent), capture_output=True, timeout=180)
        except (OSError, subprocess.SubprocessError):
            return _t(sprache, "pdf_nicht")
        if r.returncode != 0:
            return _t(sprache, "pdf_fehler")
    for endung in (".aux", ".log", ".out"):              # nur bei Erfolg aufraeumen
        try:
            tex.with_suffix(endung).unlink()
        except OSError:
            pass
    return _t(sprache, "pdf_ok") if tex.with_suffix(".pdf").is_file() else _t(sprache, "pdf_leer")


def _eindeutig(ziel: Path, name: str) -> Path:
    p, i = ziel / name, 2
    while p.exists():
        p, i = ziel / f"{name}_{i}", i + 1
    return p


def erstelle_zertifikat(log: Path | None = None, projekt_ordner: Path | None = None,
                        projekt: str | None = None, ziel: Path | None = None,
                        titel: str | None = None, aussteller: str | None = None,
                        min_tests: int = 1, streng: bool = False, pdf: bool = True,
                        jetzt: datetime | None = None, sprache: str = "de") -> dict:
    """Erstellt ein Zertifikat und liefert dessen Angaben (dict, wie zertifikat.json,
    zusaetzlich 'ordner'). Wirft EingabeFehler, wenn das Protokoll fehlt/unlesbar ist.
    1.1.0: sprache "de" (Vorgabe, wie 1.0.0) oder "en"; titel None = Vorgabe der Sprache."""
    if sprache not in SPRACHEN:
        raise ValueError(f"sprache muss eine von {SPRACHEN} sein, nicht {sprache!r}")
    titel = titel or _t(sprache, "titel")
    projekt_ordner = Path(projekt_ordner or Path.cwd()).resolve()
    log = Path(log).resolve() if log else neuestes_protokoll(projekt_ordner, sprache)
    prot = lies_protokoll(log, sprache)
    git_wurzel = _git(projekt_ordner, "rev-parse", "--show-toplevel")
    projekt = projekt or (Path(git_wurzel).name if git_wurzel else projekt_ordner.name)
    lauf = dict(prot["lauf"])
    if not lauf.get("branch"):                       # JUnit: Stand beim Ausstellen
        lauf["branch"] = _git(projekt_ordner, "rev-parse", "--abbrev-ref", "HEAD") or None
        lauf["commit"] = _git(projekt_ordner, "rev-parse", "--short", "HEAD") or None
    aussteller = (aussteller or _git(projekt_ordner, "config", "user.name")
                  or getpass.getuser() or "?")
    ausw = auswerten(prot, min_tests=min_tests, streng=streng, sprache=sprache)
    jetzt = (jetzt or datetime.now(timezone.utc)).astimezone(timezone.utc).replace(microsecond=0)
    pruef = _sha256(log)
    nr = "_".join([_t(sprache, "kennung"), jetzt.strftime("%Y%m%d_%H%M%S") + "Z",
                   _sicher(projekt, 30),
                   _sicher(lauf.get("branch") or _t(sprache, "ohne_branch"), 30),
                   _sicher(lauf.get("commit") or _t(sprache, "ohne_commit"), 12), pruef[:6]])
    ziel = Path(ziel).resolve() if ziel else projekt_ordner / _t(sprache, "ablage")
    ziel.mkdir(parents=True, exist_ok=True)
    ordner = _eindeutig(ziel, nr)
    ordner.mkdir()
    nr = ordner.name
    kopie = "testprotokoll" + (".xml" if prot["format"] == "JUnit-XML" else ".json")
    shutil.copy2(str(log), str(ordner / kopie))
    z = {"nr": nr, "titel": titel, "projekt": projekt, "aussteller": aussteller,
         "ausgestellt_utc": jetzt.isoformat(), "werkzeug": f"testzertifikat.py {__VERSION__}",
         "format": prot["format"], "protokoll_datei": log.name, "kopie": kopie, "sha256": pruef,
         "min_tests": max(1, int(min_tests)), "streng": bool(streng), "lauf": lauf,
         "auswertung": ausw, "sprache": sprache}
    schreibe_html(z, ordner / "zertifikat.html")
    schreibe_tex(z, ordner / "zertifikat.tex")
    pdf_status = _pdflatex(ordner / "zertifikat.tex", sprache) if pdf else _t(sprache, "pdf_aus")
    hat_pdf = pdf_status == _t(sprache, "pdf_ok")
    z["pdf"] = hat_pdf
    z["pdf_status"] = pdf_status
    aus = dict(z)
    aus["auswertung"] = {**ausw, "probleme": ausw["probleme"][:MAX_LISTE]}
    (ordner / "zertifikat.json").write_text(json.dumps(aus, ensure_ascii=False, indent=1),
                                            encoding="utf-8")
    verlauf = ziel / "verlauf.csv"
    neu = not verlauf.exists()
    with verlauf.open("a", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter=";")
        if neu:
            w.writerow(VERLAUF_KOPF_EN if sprache == "en" else VERLAUF_KOPF)
        c = ausw["zaehler"]
        w.writerow([nr, z["ausgestellt_utc"], projekt, _urteil(ausw["bestanden"], sprache),
                    lauf.get("zeit_utc") or "", lauf.get("branch") or "", lauf.get("commit") or "",
                    _ja_nein(lauf.get("geaendert"), sprache), ausw["gesamt"], c["ok"], c["fehler"],
                    c["error"], c["skip"], c["xfail"], c["xpass"], lauf.get("dauer_s") or "",
                    pruef, _t(sprache, "ja") if hat_pdf else _t(sprache, "nein"), aussteller])
    z["ordner"] = str(ordner)
    return z


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="testzertifikat.py",
        description="Erstellt aus einem Testprotokoll (AAS7-JSON oder JUnit-XML) ein Testzertifikat "
                    "in einem eigenen, eindeutig benannten Ordner (History). / Creates a test "
                    "certificate from a test log (AAS7 JSON or JUnit XML) in its own, uniquely "
                    "named folder (history); use --sprache en for English output.")
    ap.add_argument("--log", help="Testprotokoll (.json AAS7 oder .xml JUnit); Vorgabe: neuestes "
                                  "logs/tests/pytest_*.json im Projektordner, sonst neuestes "
                                  "logs/tests/*.xml")
    ap.add_argument("--projekt-ordner", default=".", help="Projektordner (Vorgabe: aktueller Ordner)")
    ap.add_argument("--projekt", help="Projektname (Vorgabe: Name des Git- bzw. Projektordners)")
    ap.add_argument("--ziel", help="Ablage der Zertifikate (Vorgabe: <projekt-ordner>/zertifikate, "
                                   "mit --sprache en <projekt-ordner>/certificates)")
    ap.add_argument("--titel", help="Ueberschrift (Vorgabe: Testzertifikat bzw. Test certificate)")
    ap.add_argument("--aussteller", help="Aussteller (Vorgabe: git user.name bzw. Anmeldename)")
    ap.add_argument("--min-tests", type=int, default=1, help="mindestens so viele Tests (Vorgabe 1)")
    ap.add_argument("--streng", action="store_true",
                    help="zusaetzlich: kein nicht committeter Stand, kein xpass")
    ap.add_argument("--kein-pdf", action="store_true", help="kein PDF erzeugen (nur HTML/TeX/JSON)")
    ap.add_argument("--quiet", action="store_true", help="nur Fehlermeldungen ausgeben")
    ap.add_argument("--sprache", choices=SPRACHEN, default="de",
                    help="Sprache der Ausgaben / output language (Vorgabe de)")
    ap.add_argument("--version", action="version", version=f"%(prog)s {__VERSION__}")
    a = ap.parse_args(argv)
    s = a.sprache
    try:
        z = erstelle_zertifikat(log=a.log, projekt_ordner=Path(a.projekt_ordner), projekt=a.projekt,
                                ziel=a.ziel, titel=a.titel, aussteller=a.aussteller,
                                min_tests=a.min_tests, streng=a.streng, pdf=not a.kein_pdf,
                                sprache=s)
    except EingabeFehler as e:
        print(f"{_t(s, 'c_fehler')}: {e}", file=sys.stderr)
        return 2
    ausw = z["auswertung"]
    if not a.quiet:
        c = ausw["zaehler"]
        print(f"{_urteil(ausw['bestanden'], s)}: {z['projekt']}, " +
              _t(s, "c_tests", g=ausw["gesamt"], ok=c["ok"], f=c["fehler"], e=c["error"],
                 s=c["skip"], x=c["xfail"]))
        for g in ausw["gruende"]:
            print(f"  - {g}")
        print(f"{_t(s, 'c_zertifikat')}: {z['ordner']}")
        print("  zertifikat.html, zertifikat.tex" + (", zertifikat.pdf" if z["pdf"] else
              f" ({_t(s, 'c_kein_pdf')}: {z['pdf_status']})") + ", zertifikat.json, " + z["kopie"])
    return 0 if ausw["bestanden"] else 1


if __name__ == "__main__":
    sys.exit(main())
