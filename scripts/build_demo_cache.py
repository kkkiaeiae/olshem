"""Build the demo-mode cache for the public sample (demo/emhana.docx).

* format results: computed now by the program (deterministic);
* AI review: taken from a REAL run of the prototype pipeline (gemini-3.5-flash, 2026-11-03,
  demo/source/report_emhana_prototype.html), or — when GEMINI_API_KEY is set and --live is
  given — produced by a fresh live run.

Usage:  python scripts/build_demo_cache.py [--live]
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bs4 import BeautifulSoup  # noqa: E402

from olshem.core import format_checker as fc  # noqa: E402
from olshem.core.review import docx_to_text, verify_citations  # noqa: E402

DEMO = ROOT / "demo"
STATUS_FROM_LABEL = {"Сәйкес": "сәйкес", "Ішінара": "ішінара", "Сәйкес емес": "сәйкес емес", "Тексерілмеді": "тексерілмеді"}


def parse_prototype_review(html_path: pathlib.Path, checklist: dict) -> tuple[dict, str]:
    soup = BeautifulSoup(html_path.read_text(encoding="utf-8"), "html.parser")
    by_text = {r["text_kk"]: r["id"] for r in checklist["rules"]}
    ai_rules = []
    for item in soup.select("div.item"):
        src = item.select_one(".src")
        if not src or src.get_text(strip=True) != "ЖИ":
            continue
        title = item.select_one("h3").get_text(strip=True)
        label = re.sub(r"^[^\wА-Яа-яӘә]+", "", item.select_one(".pill").get_text(strip=True))
        ev = []
        for bq in item.select("blockquote"):
            loc = bq.select_one("i").get_text(strip=True) if bq.select_one("i") else ""
            q = bq.get_text(" ", strip=True)
            q = re.sub(r"\s*—\s*" + re.escape(loc) + r"\s*$", "", q).strip().strip("«»")
            ev.append({"quote": q, "location": loc})
        sg = item.select_one(".sugg")
        ai_rules.append({"id": by_text.get(title, title), "status": STATUS_FROM_LABEL[label],
                         "found": item.select_one(".found").get_text(strip=True), "evidence": ev,
                         "suggestion": sg.get_text(" ", strip=True).replace("Ұсыныс:", "", 1).strip() if sg else ""})
    fb = []
    for item in soup.select("div.item.fb"):
        ps = item.select("p")
        fb.append({"section": item.select_one("h3").get_text(strip=True),
                   "strength": ps[0].get_text(" ", strip=True).lstrip("＋").strip(),
                   "issue": ps[1].get_text(" ", strip=True).lstrip("－").strip(),
                   "suggestion": ps[2].get_text(" ", strip=True).replace("Ұсыныс:", "", 1).strip()})
    summ = soup.select_one(".summary")
    reasoning = summ.select_one(".meta").get_text(" ", strip=True)
    summary = summ.get_text(" ", strip=True).replace("Қысқаша қорытынды.", "", 1).replace(reasoning, "").strip()
    score = int(soup.select(".ring b")[1].get_text(strip=True))
    attn = [li.get_text(" ", strip=True) for li in soup.select(".attn li")]
    model = re.search(r"мазмұнды (\S+) моделі", soup.select_one("footer").get_text()).group(1)
    return {"summary_kk": summary, "ai_rules": ai_rules, "content_feedback": fb, "suggested_score": score,
            "score_reasoning": reasoning, "teacher_attention": attn}, model


def main() -> None:
    checklist = json.loads((DEMO / "checklist.json").read_text(encoding="utf-8"))
    work = DEMO / "emhana.docx"
    fmt, meta = fc.run_checks(work, checklist)
    text = docx_to_text(work)
    if "--live" in sys.argv:
        from olshem.core.pipeline import Materials, analyze
        out = analyze("docx", [work], checklist, Materials([DEMO / "talaptar.pdf"], "", DEMO / "syllabus.pdf"))
        if out.ai_error:
            raise SystemExit(out.ai_error)
        review, model, source = out.review, out.model, "live run"
    else:
        review, model = parse_prototype_review(DEMO / "source" / "report_emhana_prototype.html", checklist)
        review = verify_citations(review, text)
        source = "prototype run 2026-11-03 (demo/source/report_emhana_prototype.html)"
    cache = {"sha256": hashlib.sha256(work.read_bytes()).hexdigest(), "file": work.name,
             "title": "Қалалық емхана пациенттерінің картотекасы", "source": source,
             "format_results": fmt, "meta": meta, "review": review, "model": model}
    (DEMO / "cache").mkdir(exist_ok=True)
    (DEMO / "cache" / "emhana.json").write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    print("ok:", meta, "ai rules:", [(r["id"], r["status"]) for r in review["ai_rules"]], review.get("citations"))


if __name__ == "__main__":
    main()
