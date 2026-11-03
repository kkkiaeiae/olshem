"""Deterministic metrics computed by the program (never by the LLM)."""
from __future__ import annotations

WEIGHT = {"сәйкес": 1.0, "ішінара": 0.5, "сәйкес емес": 0.0}


def compliance_pct(rule_results: list[dict]) -> int | None:
    """Share of satisfied requirements. «тексерілмеді» and optional rules are not counted."""
    rated = [WEIGHT[r["status"]] for r in rule_results
             if r["status"] in WEIGHT and not r.get("optional")]
    return round(100 * sum(rated) / len(rated)) if rated else None


def merge_rules(format_results: list[dict], review: dict | None, checklist: dict) -> list[dict]:
    """Program results + AI results in one list, each tagged with its source."""
    byid = {r["id"]: r for r in checklist.get("rules", [])}
    rules = [{**r, "src": "Бағдарлама", "evidence": [], "suggestion": ""} for r in format_results]
    for r in (review or {}).get("ai_rules", []):
        src = byid.get(r["id"], {})
        rules.append({**r, "src": "ЖИ", "details": r.get("details", []),
                      "text_kk": src.get("text_kk", r["id"]), "severity": src.get("severity", "маңызды"),
                      "category": src.get("category", "мазмұн"), "optional": bool(src.get("optional"))})
    return rules
