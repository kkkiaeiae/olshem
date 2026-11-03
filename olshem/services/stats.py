from __future__ import annotations

import collections
import statistics

from sqlmodel import Session, select

from ..core.scoring import merge_rules
from ..models.entities import Assignment, Submission
from ..models.schemas import StatsOut, TopProblem


def assignment_stats(s: Session, a: Assignment, top_n: int = 8) -> StatsOut:
    subs = s.exec(select(Submission).where(Submission.assignment_id == a.id)).all()
    done = [x for x in subs if x.status == "done"]
    checklist = a.checklist_json or {"rules": []}
    fail, part, seen = collections.Counter(), collections.Counter(), collections.Counter()
    info: dict[str, tuple[str, str]] = {}
    for sub in done:
        for r in merge_rules(sub.format_result_json or [], sub.review_json, checklist):
            if r["status"] == "тексерілмеді":
                continue
            seen[r["id"]] += 1
            info[r["id"]] = (r.get("text_kk") or r["id"], r["src"])
            if r["status"] == "сәйкес емес":
                fail[r["id"]] += 1
            elif r["status"] == "ішінара":
                part[r["id"]] += 1
    ids = sorted(set(fail) | set(part), key=lambda i: (-(fail[i] + 0.5 * part[i]), info[i][0]))
    top = [TopProblem(rule_id=i, text_kk=info[i][0], source=info[i][1], failed=fail[i], partial=part[i],
                      share_pct=round(100 * (fail[i] + part[i]) / seen[i])) for i in ids[:top_n]]
    comp = [x.compliance_pct for x in done if x.compliance_pct is not None]
    ai = [x.ai_score for x in done if x.ai_score is not None]
    buckets = {"0–49%": 0, "50–69%": 0, "70–84%": 0, "85–100%": 0}
    for c in comp:
        k = "0–49%" if c < 50 else "50–69%" if c < 70 else "70–84%" if c < 85 else "85–100%"
        buckets[k] += 1
    return StatsOut(assignment_id=a.id, submissions_total=len(subs), submissions_done=len(done),
                    avg_compliance_pct=round(statistics.mean(comp), 1) if comp else None,
                    avg_ai_score=round(statistics.mean(ai), 1) if ai else None,
                    compliance_buckets=buckets, top_problems=top)
