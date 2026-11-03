"""Demo data: the preset assignment «Деректер базасы және SQL сұратымдар · Курстық жұмыс» with the
checklist extracted from the real ПОӘК, one public sample work (a team member's own work, cached
result of a real AI run) and three clearly labelled synthetic works for the class statistics.
No other student's work is ever included."""
from __future__ import annotations

import json
import logging
import shutil
import uuid

from sqlmodel import Session, select

from ..config import settings
from ..core.pipeline import Materials, analyze
from ..core.requirements import Checklist
from ..core.scoring import compliance_pct, merge_rules
from ..models.db import session_scope
from ..models.entities import Assignment, Course, Submission, now
from . import demo, jobs
from .synthetic import REFS_SORTED, Spec, make_work

log = logging.getLogger("olshem.seed")
SYNTHETIC_NOTE = "Синтетикалық үлгі: мәтін жасанды, сондықтан тек бағдарламалық тексеру жүргізілді."

SYNTHETIC = [
    ("Синтетикалық үлгі №1", Spec(body_paras=170, seed=11)),
    ("Синтетикалық үлгі №2", Spec(margins_cm=(2.5, 1.5, 2, 2), spacing=1.15, body_paras=110, with_task_page=False,
                                  tables_captioned=1, tables_uncaptioned=2, refs=REFS_SORTED[::-1], seed=12)),
    ("Синтетикалық үлгі №3", Spec(body_paras=240, with_conclusion=False, bad_font_paras=25, bad_spacing_paras=12,
                                  tables_captioned=2, tables_uncaptioned=1, code_paras=3, seed=13)),
]


def _copy(src) -> str:
    dst = settings.upload_dir / f"{uuid.uuid4().hex}{src.suffix}"
    shutil.copyfile(src, dst)
    return dst.name


def seed_if_empty() -> None:
    if not settings.seed_demo or not (settings.demo_dir / "checklist.json").exists():
        return
    with session_scope() as s:
        if s.exec(select(Assignment)).first():
            return
        _seed(s)


def _seed(s: Session) -> None:
    course = Course(name="Деректер базасы және SQL сұратымдар", code="")
    s.add(course); s.commit(); s.refresh(course)
    cl = Checklist.model_validate(demo.demo_checklist()).model_dump()
    a = Assignment(course_id=course.id, title="Курстық жұмыс", type="курстық",
                   requirement_files=[_copy(settings.demo_dir / "talaptar.pdf")],
                   syllabus_file=_copy(settings.demo_dir / "syllabus.pdf"),
                   checklist_json=cl, checklist_confirmed=True, checklist_status="ready",
                   checklist_model="gemini-3.5-flash", is_demo=True)
    s.add(a); s.commit(); s.refresh(a)

    for cache in demo.work_cache().values():
        f = _copy(settings.demo_dir / cache["file"])
        rules = merge_rules(cache["format_results"], cache["review"], cl)
        s.add(Submission(assignment_id=a.id, student_label="Үлгі жұмыс (команда мүшесі)", kind="docx",
                         file_paths=[f], file_path=f, original_name=cache["file"], file_sha256=cache["sha256"],
                         status="done", format_result_json=cache["format_results"], meta_json=cache["meta"],
                         review_json=cache["review"], compliance_pct=compliance_pct(rules),
                         ai_score=cache["review"].get("suggested_score"), model_used=cache["model"],
                         demo=True, finished_at=now()))
    pre = settings.demo_dir / "synthetic.json"
    if pre.exists():  # pre-computed at image build time (services/seed_build.py)
        for item in json.loads(pre.read_text(encoding="utf-8")):
            s.add(Submission(assignment_id=a.id, student_label=item["label"], kind="docx",
                             original_name="synthetic.docx", status="done",
                             format_result_json=item["format_results"], meta_json=item["meta"],
                             compliance_pct=compliance_pct(merge_rules(item["format_results"], None, cl)),
                             ai_error=SYNTHETIC_NOTE, finished_at=now()))
        s.commit()
        return
    ids = []
    for label, spec in SYNTHETIC:
        p = make_work(settings.upload_dir / f"{uuid.uuid4().hex}.docx", spec)
        sub = Submission(assignment_id=a.id, student_label=label, kind="docx", file_paths=[p.name],
                         file_path=p.name, original_name="synthetic.docx", status="queued")
        s.add(sub); s.commit(); s.refresh(sub)
        ids.append(sub.id)
    s.commit()
    for i in ids:
        jobs.submit(_run_synthetic, i, a.id)


def _run_synthetic(sub_id: str, aid: int) -> None:
    """Synthetic texts are filler, so only the program checks run (no AI score for them)."""
    with session_scope() as s:
        sub, a = s.get(Submission, sub_id), s.get(Assignment, aid)
        path, cl = settings.upload_dir / sub.file_path, a.checklist_json
    try:
        out = analyze("docx", [path], cl, Materials(),
                      on_stage=lambda st: jobs._set(sub_id, status=st),
                      skip_ai=SYNTHETIC_NOTE)
        jobs._finish(sub_id, cl, out.format_results, out.meta, None, None, out.ai_error, None)
    except Exception as e:  # noqa: BLE001
        log.exception("synthetic seed failed")
        jobs._set(sub_id, status="error", error=str(e), finished_at=now())
