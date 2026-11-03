import os
import pathlib
import sys
import tempfile

# isolated data dir, no demo seeding, no network probes — must be set before importing olshem
_tmp = tempfile.mkdtemp(prefix="olshem_test_")
os.environ["DATA_DIR"] = _tmp
os.environ["SEED_DEMO"] = "0"
os.environ["PROBE_MODELS_ON_START"] = "0"
os.environ["DEMO_MODE"] = "0"
os.environ.pop("GEMINI_API_KEY", None)
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import json  # noqa: E402

import pytest  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def checklist() -> dict:
    return json.loads((ROOT / "demo" / "checklist.json").read_text(encoding="utf-8"))


@pytest.fixture
def rule():
    def make(metric, **kw):
        base = {"id": "r", "category": "рәсімдеу", "text_kk": "т", "check": "auto", "metric": metric,
                "severity": "маңызды", "value": None, "min": None, "max": None, "items": None, "source_quote": ""}
        base.update(kw)
        return {"rules": [base]}
    return make
