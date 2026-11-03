"""Build step (runs inside `docker build`): pre-compute the program checks for the synthetic demo
works, so a cold start of a small instance never spends minutes re-checking them.

    python -m olshem.services.seed_build   ->  demo/synthetic.json
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from ..config import settings
from ..core.pipeline import Materials, analyze
from .demo import demo_checklist
from .seed import SYNTHETIC
from .synthetic import make_work


def main() -> None:
    cl = demo_checklist()
    out = []
    tmp = Path(tempfile.mkdtemp())
    for label, spec in SYNTHETIC:
        p = make_work(tmp / f"{abs(hash(label))}.docx", spec)
        o = analyze("docx", [p], cl, Materials(), skip_ai="-")
        out.append({"label": label, "format_results": o.format_results, "meta": o.meta})
        print(label, o.meta)
    (settings.demo_dir / "synthetic.json").write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
