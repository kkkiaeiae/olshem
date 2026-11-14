from __future__ import annotations

from sqlmodel import Session, func, select

from ..core.requirements import Checklist
from ..models.entities import Assignment, Course, Submission, aware, now
from ..core.scoring import merge_rules
from ..models.schemas import AssignmentOut, CourseOut, PreviousOut, StageOut, SubmissionOut

STAGES = [("checklist", "Талаптар"), ("format", "Рәсімдеу"), ("review", "Мазмұн"), ("report", "Есеп")]
OCR_STAGE = ("ocr", "Қолжазба")


def assignment_out(s: Session, a: Assignment) -> AssignmentOut:
    c = s.get(Course, a.course_id)
    n = s.exec(select(func.count()).select_from(Submission).where(Submission.assignment_id == a.id)).one()
    return AssignmentOut(
        id=a.id, course=CourseOut(id=c.id, name=c.name, code=c.code), title=a.title, type=a.type,
        deadline=a.deadline, requirement_files=[f"талап-{i + 1}{n_[n_.rfind('.'):]}" for i, n_ in enumerate(a.requirement_files)],
        has_requirement_text=bool(a.requirement_text.strip()), has_syllabus=bool(a.syllabus_file),
        checklist_status=a.checklist_status, checklist_error=a.checklist_error, checklist_model=a.checklist_model,
        checklist_confirmed=a.checklist_confirmed,
        checklist=Checklist.model_validate(a.checklist_json) if a.checklist_json else None,
        is_demo=a.is_demo, submissions_count=n, created_at=aware(a.created_at))


def stages(sub: Submission) -> list[StageOut]:
    seq = STAGES[:1] + ([OCR_STAGE] if sub.kind == "photos" else []) + STAGES[1:]
    order = ["queued"] + (["ocr"] if sub.kind == "photos" else []) + ["format", "review", "done"]
    cur = sub.status
    out = []
    for key, label in seq:
        if key == "checklist":
            state = "done"
        elif cur == "done":
            state = "skipped" if key == "review" and sub.ai_error else "done"
        elif cur == "error":
            state = "error" if key == "report" else "pending"
        else:
            k = "done" if key == "report" else key
            ci, ki = order.index(cur), order.index(k)
            state = "done" if ki < ci else "active" if ki == ci else "pending"
        out.append(StageOut(key=key, label=label, state=state))
    if cur == "error":  # mark the stage where it broke
        for st in out:
            if st.state == "pending":
                st.state = "error"
                break
    return out


PROBLEM = ("сәйкес емес", "ішінара")


def label_key(label: str | None) -> str:
    """Case/space-insensitive key for matching a student's versions. Done in Python because
    SQLite's lower() only folds ASCII and the labels are Kazakh / Russian names."""
    return " ".join((label or "").split()).casefold()


def _problems(sub: Submission, checklist: dict) -> dict[str, str]:
    """rule id -> text of every rule that is not satisfied (optional rules excluded)."""
    rules = merge_rules(sub.format_result_json or [], sub.review_json, checklist)
    return {r["id"]: r.get("text_kk") or r["id"] for r in rules
            if r.get("status") in PROBLEM and not r.get("optional")}


def compare_previous(s: Session, sub: Submission) -> PreviousOut | None:
    key = label_key(sub.student_label)
    if sub.status != "done" or not key:
        return None
    rows = s.exec(select(Submission).where(Submission.assignment_id == sub.assignment_id,
                                           Submission.status == "done", Submission.id != sub.id,
                                           Submission.created_at < sub.created_at)
                  .order_by(Submission.created_at.desc())).all()
    prev = next((x for x in rows if label_key(x.student_label) == key), None)
    if not prev:
        return None
    a = s.get(Assignment, sub.assignment_id)
    cl = (a.checklist_json if a else None) or {"rules": []}
    before, after = _problems(prev, cl), _problems(sub, cl)
    fixed = [before[k] for k in before if k not in after]
    return PreviousOut(id=prev.id, compliance_pct=prev.compliance_pct, ai_score=prev.ai_score,
                       fixed=len(fixed), new_problems=sum(1 for k in after if k not in before),
                       fixed_rules=fixed[:8], created_at=aware(prev.created_at))


def submission_out(s: Session, sub: Submission, with_results: bool = False) -> SubmissionOut:
    a = s.get(Assignment, sub.assignment_id)
    end = aware(sub.finished_at) or now()
    problems = 0
    if sub.status == "done":
        problems = sum(1 for r in (sub.format_result_json or []) if r["status"] in ("сәйкес емес", "ішінара"))
        problems += sum(1 for r in (sub.review_json or {}).get("ai_rules", []) if r["status"] in ("сәйкес емес", "ішінара"))
    return SubmissionOut(
        id=sub.id, assignment_id=sub.assignment_id, assignment_title=a.title if a else "",
        student_label=sub.student_label, kind=sub.kind, original_name=sub.original_name, status=sub.status,
        stages=stages(sub), elapsed_s=round((end - aware(sub.created_at)).total_seconds(), 1),
        compliance_pct=sub.compliance_pct, ai_score=sub.ai_score, model_used=sub.model_used,
        ai_error=sub.ai_error, error=sub.error, demo=sub.demo, problems=problems,
        report_url=f"/api/submissions/{sub.id}/report" if sub.status == "done" else None,
        created_at=aware(sub.created_at), finished_at=aware(sub.finished_at),
        results={"format_results": sub.format_result_json, "review": sub.review_json, "meta": sub.meta_json,
                 "ocr": sub.ocr_json} if with_results and sub.status == "done" else None,
        previous=compare_previous(s, sub))
