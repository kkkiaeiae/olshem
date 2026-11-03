"""Background jobs. Long tasks (checklist extraction ~10 s, a check ~45 s) never block a request:
the API stores the row, schedules the job here and returns immediately; the client polls
GET /api/submissions/{id} (or listens to the SSE stream)."""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor

from sqlmodel import select

from ..config import settings
from ..core.llm import LLMUnavailable
from ..core.pipeline import Materials, analyze
from ..core.requirements import Checklist, extract_checklist
from ..core.scoring import compliance_pct, merge_rules
from ..models.db import session_scope
from ..models.entities import Assignment, Submission, now
from . import demo, storage

log = logging.getLogger("olshem.jobs")
_pool = ThreadPoolExecutor(max_workers=settings.max_parallel_jobs, thread_name_prefix="olshem-job")


def submit(fn, *args) -> None:
    fut = _pool.submit(fn, *args)
    fut.add_done_callback(lambda f: f.exception() and log.error("job crashed: %r", f.exception()))


def materials(a: Assignment) -> Materials:
    files = [p for p in (storage.stored(n) for n in a.requirement_files) if p]
    return Materials(files, a.requirement_text or "", storage.stored(a.syllabus_file))


# ------------------------------------------------------------------ stage ①
def run_extraction(assignment_id: int) -> None:
    with session_scope() as s:
        a = s.get(Assignment, assignment_id)
        if not a:
            return
        m = materials(a)
        demo_on = demo.is_demo_mode(s)
        title = a.title
    try:
        cached = None
        if demo_on:
            for f in m.requirement_files:
                cached = demo.checklist_cache().get(demo.sha256(f))
                if cached:
                    break
        if cached:
            time.sleep(1.0)
            cl, model = Checklist.model_validate(cached), "демо кэш"
        else:
            if not m.requirement_files and not m.requirement_text.strip():
                raise ValueError("Талап файлы да, мәтіні де жоқ")
            cl, model = extract_checklist(m.requirement_files, m.requirement_text)
        if not cl.assignment:
            cl.assignment = title
        with session_scope() as s:
            a = s.get(Assignment, assignment_id)
            a.checklist_json = cl.model_dump()
            a.checklist_status, a.checklist_error, a.checklist_model = "ready", None, model
            a.checklist_confirmed = False
            s.add(a); s.commit()
    except Exception as e:  # noqa: BLE001
        msg = str(e) if isinstance(e, (LLMUnavailable, ValueError)) else f"Талаптарды өңдеу мүмкін болмады: {str(e)[:200]}"
        log.warning("extraction failed for %s: %s", assignment_id, e)
        with session_scope() as s:
            a = s.get(Assignment, assignment_id)
            a.checklist_status, a.checklist_error = "error", msg
            s.add(a); s.commit()


# ------------------------------------------------------------------ stages ②③④
def _set(sub_id: str, **kw) -> None:
    with session_scope() as s:
        sub = s.get(Submission, sub_id)
        for k, v in kw.items():
            setattr(sub, k, v)
        s.add(sub); s.commit()


def run_submission(sub_id: str) -> None:
    with session_scope() as s:
        sub = s.get(Submission, sub_id)
        a = s.get(Assignment, sub.assignment_id)
        checklist = a.checklist_json or {"rules": []}
        m = materials(a)
        demo_on = demo.is_demo_mode(s)
        kind, files = sub.kind, [p for p in (storage.stored(n) for n in sub.file_paths) if p]
        sha, label = sub.file_sha256, sub.student_label
    stage = lambda st: _set(sub_id, status=st, stage_started_at=now())  # noqa: E731
    try:
        if not files:
            raise RuntimeError("Жүктелген файл табылмады")
        cached = demo.work_cache().get(sha) if demo_on else None
        if cached:  # demo mode: show the stored result of a real earlier run, clearly labelled
            for st in ("format", "review"):
                stage(st); time.sleep(0.8)
            fmt_by_id = {r["id"]: r for r in cached["format_results"]}
            enabled = [r for r in checklist["rules"] if r["check"] == "auto" and r.get("enabled", True)]
            fmt = [fmt_by_id[r["id"]] | {"optional": bool(r.get("optional"))} for r in enabled if r["id"] in fmt_by_id]
            ai_ids = {r["id"] for r in checklist["rules"] if r["check"] == "ai" and r.get("enabled", True)}
            review = dict(cached["review"])
            review["ai_rules"] = [r for r in review["ai_rules"] if r["id"] in ai_ids]
            _finish(sub_id, checklist, fmt, cached["meta"], review, cached["model"], None, None, demo=True)
            return
        skip = "Демо режимі қосулы: ЖИ кезеңі өткізілді (бұл файл үшін сақталған нәтиже жоқ)." if demo_on else None
        out = analyze(kind, files, checklist, m, on_stage=stage,
                      extra_names=[label] if label else None, skip_ai=skip)
        _finish(sub_id, checklist, out.format_results, out.meta, out.review, out.model, out.ai_error, out.ocr)
    except Exception as e:  # noqa: BLE001 — any failure ends in a readable error state
        log.exception("submission %s failed", sub_id)
        msg = str(e) if isinstance(e, RuntimeError) else f"Тексеру кезінде қате шықты: {type(e).__name__}: {str(e)[:200]}"
        _set(sub_id, status="error", error=msg, finished_at=now())


def _finish(sub_id, checklist, fmt, meta, review, model, ai_error, ocr, demo: bool = False) -> None:
    rules = merge_rules(fmt, review, checklist)
    _set(sub_id, status="done", format_result_json=fmt, meta_json=meta, review_json=review, ocr_json=ocr,
         compliance_pct=compliance_pct(rules), ai_score=(review or {}).get("suggested_score"),
         model_used=model, ai_error=ai_error, demo=demo, finished_at=now())


def resume_unfinished() -> None:
    """After a restart, re-queue jobs that were interrupted."""
    with session_scope() as s:
        subs = s.exec(select(Submission).where(Submission.status.in_(["queued", "format", "ocr", "review"]))).all()
        ids = [(x.id, x.assignment_id, x.original_name == "synthetic.docx") for x in subs]
        asg = s.exec(select(Assignment).where(Assignment.checklist_status == "extracting")).all()
        aids = [x.id for x in asg]
    from .seed import _run_synthetic
    for i, aid, synthetic in ids:
        if synthetic:
            submit(_run_synthetic, i, aid)
        else:
            submit(run_submission, i)
    for i in aids:
        submit(run_extraction, i)
