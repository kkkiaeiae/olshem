"""Regression on the real sample works (expected values measured 2026-11-03).
advokat.docx is another student's work: kept out of the repository (samples_private/, git-ignored);
the test is skipped when it is absent."""
import pathlib

import pytest

from olshem.core import format_checker as fc

ROOT = pathlib.Path(__file__).resolve().parent.parent
needs_lo = pytest.mark.skipif(not fc.soffice_available(), reason="LibreOffice not installed")


def results(path, checklist):
    res, meta = fc.run_checks(path, checklist)
    return {r["id"]: r for r in res}, meta


@needs_lo
def test_emhana(checklist):
    r, meta = results(ROOT / "demo" / "emhana.docx", checklist)
    assert meta["pages"] == 52
    assert r["rule-3"]["status"] == "сәйкес емес"                       # 52 pages vs 25–30
    assert "Жоқ: ТАПСЫРМА" in r["rule-2"]["details"]
    assert "1.15 — 12" in r["rule-10"]["found"]                         # 12 paragraphs at 1.15
    assert r["rule-16"]["status"] == "сәйкес емес" and len(r["rule-16"]["details"]) == 2
    assert r["rule-13"]["status"] == "сәйкес"


@needs_lo
@pytest.mark.skipif(not (ROOT / "samples_private" / "advokat.docx").exists(), reason="private sample absent")
def test_advokat(checklist):
    r, meta = results(ROOT / "samples_private" / "advokat.docx", checklist)
    assert r["rule-5"]["status"] == "сәйкес емес" and "1.50" in r["rule-5"]["found"]
    assert "Жоқ: ҚОРЫТЫНДЫ" in r["rule-2"]["details"]
    assert "25 кестенің 5-і" in r["rule-13"]["found"]
