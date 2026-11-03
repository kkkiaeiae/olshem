from __future__ import annotations

import datetime as dt
import shutil
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlmodel import Session, select

from ..config import settings
from ..core.requirements import METRICS
from ..models.db import get_session
from ..models.entities import ASSIGNMENT_TYPES, Assignment, Course, Submission
from ..models.schemas import AssignmentOut, ChecklistUpdate, CourseOut, StatsOut, SubmissionOut
from ..services import demo, jobs, storage
from ..services.serializers import assignment_out, submission_out
from ..services.stats import assignment_stats
from .deps import User, current_user, require_teacher

router = APIRouter(prefix="/api", tags=["Тапсырмалар"])

REQ_EXT = {".pdf", ".jpg", ".jpeg", ".png", ".webp"}
WORK_EXT = {".docx", ".pdf", ".jpg", ".jpeg", ".png", ".webp"}


def _get(s: Session, aid: int) -> Assignment:
    a = s.get(Assignment, aid)
    if not a:
        raise HTTPException(404, "Тапсырма табылмады")
    return a


@router.get("/courses", response_model=list[CourseOut], summary="Пәндер тізімі")
def list_courses(s: Session = Depends(get_session)):
    return [CourseOut(id=c.id, name=c.name, code=c.code) for c in s.exec(select(Course)).all()]


@router.post("/assignments", response_model=AssignmentOut, status_code=201,
             summary="Тапсырма құру + талаптарды жүктеу (① кезең фонда басталады)")
async def create_assignment(
    title: str = Form(..., description="Тапсырма атауы"),
    type: str = Form("курстық", description=" | ".join(ASSIGNMENT_TYPES)),
    course_name: str = Form(..., description="Пән атауы"),
    course_code: str = Form(""),
    deadline: Optional[dt.date] = Form(None),
    requirement_text: str = Form("", description="Талаптар мәтін түрінде (міндетті емес)"),
    requirement_files: list[UploadFile] = File(default=[], description="ПОӘК / талаптар: PDF немесе фото"),
    syllabus_file: Optional[UploadFile] = File(None, description="Силлабус PDF (міндетті емес)"),
    s: Session = Depends(get_session), _: User = Depends(require_teacher),
):
    if type not in ASSIGNMENT_TYPES:
        raise HTTPException(422, f"Тапсырма түрі: {', '.join(ASSIGNMENT_TYPES)}")
    files = [f for f in requirement_files if f and f.filename]
    if not files and not requirement_text.strip():
        raise HTTPException(422, "Талаптар файлын жүктеңіз немесе мәтінін жазыңыз")
    if len(files) > 10:
        raise HTTPException(422, "Ең көбі 10 талап файлы")
    stored = [(await storage.save_upload(f, REQ_EXT))[0].name for f in files]
    syl = None
    if syllabus_file and syllabus_file.filename:
        syl = (await storage.save_upload(syllabus_file, {".pdf"}))[0].name
    course = s.exec(select(Course).where(Course.name == course_name.strip())).first()
    if not course:
        course = Course(name=course_name.strip(), code=course_code.strip())
        s.add(course); s.commit(); s.refresh(course)
    a = Assignment(course_id=course.id, title=title.strip(), type=type, deadline=deadline,
                   requirement_files=stored, requirement_text=requirement_text, syllabus_file=syl,
                   checklist_status="extracting")
    s.add(a); s.commit(); s.refresh(a)
    jobs.submit(jobs.run_extraction, a.id)
    return assignment_out(s, a)


@router.get("/assignments", response_model=list[AssignmentOut], summary="Тапсырмалар тізімі")
def list_assignments(confirmed_only: bool = False, s: Session = Depends(get_session)):
    q = select(Assignment).order_by(Assignment.created_at.desc())
    if confirmed_only:
        q = q.where(Assignment.checklist_confirmed == True)  # noqa: E712
    return [assignment_out(s, a) for a in s.exec(q).all()]


@router.get("/assignments/{aid}", response_model=AssignmentOut, summary="Тапсырма және тексеру тізімі")
def get_assignment(aid: int, s: Session = Depends(get_session)):
    return assignment_out(s, _get(s, aid))


@router.put("/assignments/{aid}/checklist", response_model=AssignmentOut,
            summary="Оқытушы тексеру тізімін түзетеді және растайды")
def update_checklist(aid: int, body: ChecklistUpdate, s: Session = Depends(get_session),
                     _: User = Depends(require_teacher)):
    a = _get(s, aid)
    cl = body.checklist
    ids = [r.id for r in cl.rules]
    if len(set(ids)) != len(ids):
        raise HTTPException(422, "Ереже идентификаторлары қайталанбауы керек")
    for r in cl.rules:
        if not r.text_kk.strip():
            raise HTTPException(422, f"{r.id}: ереже мәтіні бос")
        if r.check == "auto" and (r.metric == "none" or r.metric not in METRICS):
            raise HTTPException(422, f"{r.id}: бағдарлама тексеретін ережеге метрика керек")
        if r.check == "ai":
            r.metric = "none"
        if r.min is not None and r.max is not None and r.min > r.max:
            raise HTTPException(422, f"{r.id}: ең кіші мән ең үлкеннен аспауы керек")
    if body.confirm and not any(r.enabled for r in cl.rules):
        raise HTTPException(422, "Кемінде бір ереже қосулы болуы керек")
    a.checklist_json = cl.model_dump()
    a.checklist_status, a.checklist_error = "ready", None
    a.checklist_confirmed = body.confirm
    s.add(a); s.commit(); s.refresh(a)
    return assignment_out(s, a)


@router.post("/assignments/{aid}/extract", response_model=AssignmentOut,
             summary="① кезеңді қайта іске қосу (ЖИ қатесінен кейін)")
def retry_extract(aid: int, s: Session = Depends(get_session), _: User = Depends(require_teacher)):
    a = _get(s, aid)
    a.checklist_status, a.checklist_error = "extracting", None
    s.add(a); s.commit(); s.refresh(a)
    jobs.submit(jobs.run_extraction, a.id)
    return assignment_out(s, a)


@router.delete("/assignments/{aid}", status_code=204, summary="Тапсырманы және барлық файлдарды жою")
def delete_assignment(aid: int, s: Session = Depends(get_session), _: User = Depends(require_teacher)):
    a = _get(s, aid)
    for sub in s.exec(select(Submission).where(Submission.assignment_id == aid)).all():
        storage.delete(sub.file_paths)
        s.delete(sub)
    storage.delete(a.requirement_files + ([a.syllabus_file] if a.syllabus_file else []))
    s.delete(a); s.commit()


@router.post("/assignments/{aid}/submissions", response_model=SubmissionOut, status_code=202,
             summary="Студент жұмысын жүктеу (.docx, .pdf немесе қолжазба фотолары) — ②③④ фонда")
async def create_submission(
    aid: int,
    files: list[UploadFile] = File(..., description="Бір .docx/.pdf немесе бірнеше фото (беттер ретімен)"),
    student_label: str = Form("", description="Студенттің аты немесе коды (модельге жіберілмейді)"),
    s: Session = Depends(get_session), _: User = Depends(current_user),
):
    a = _get(s, aid)
    if not a.checklist_confirmed:
        raise HTTPException(409, "Оқытушы тексеру тізімін әлі растаған жоқ")
    files = [f for f in files if f and f.filename]
    if not files:
        raise HTTPException(422, "Файл таңдалмаған")
    exts = {("." + f.filename.rsplit(".", 1)[-1].lower()) if "." in f.filename else "" for f in files}
    if len(files) > 1 or exts & storage.IMAGE_EXT:
        if not exts <= storage.IMAGE_EXT:
            raise HTTPException(422, "Бірнеше файл тек қолжазба фотолары үшін; .docx/.pdf біреу ғана болуы керек")
        if len(files) > settings.max_photos:
            raise HTTPException(422, f"Ең көбі {settings.max_photos} фото")
        kind = "photos"
    else:
        kind = "pdf" if exts == {".pdf"} else "docx"
    saved = [await storage.save_upload(f, WORK_EXT) for f in files]
    sub = Submission(assignment_id=aid, student_label=student_label.strip()[:80], kind=kind,
                     file_paths=[p.name for p, _, _ in saved], file_path=saved[0][0].name,
                     original_name=", ".join(n for _, n, _ in saved)[:200], file_sha256=saved[0][2])
    s.add(sub); s.commit(); s.refresh(sub)
    jobs.submit(jobs.run_submission, sub.id)
    return submission_out(s, sub)


@router.post("/assignments/{aid}/submissions/sample", response_model=SubmissionOut, status_code=202,
             summary="Демо: ашық үлгі жұмысты (emhana.docx) тексеруге жіберу")
def create_sample_submission(aid: int, s: Session = Depends(get_session), _: User = Depends(current_user)):
    a = _get(s, aid)
    if not a.checklist_confirmed:
        raise HTTPException(409, "Оқытушы тексеру тізімін әлі растаған жоқ")
    src = settings.demo_dir / "emhana.docx"
    dst = settings.upload_dir / f"{uuid.uuid4().hex}.docx"
    shutil.copyfile(src, dst)
    sub = Submission(assignment_id=aid, student_label="Үлгі жұмыс (команда мүшесі)", kind="docx",
                     file_paths=[dst.name], file_path=dst.name, original_name="emhana.docx",
                     file_sha256=demo.sha256(dst))
    s.add(sub); s.commit(); s.refresh(sub)
    jobs.submit(jobs.run_submission, sub.id)
    return submission_out(s, sub)


@router.get("/assignments/{aid}/submissions", response_model=list[SubmissionOut], summary="Тапсырмаға жіберілген жұмыстар")
def list_submissions(aid: int, s: Session = Depends(get_session), _: User = Depends(require_teacher)):
    _get(s, aid)
    subs = s.exec(select(Submission).where(Submission.assignment_id == aid).order_by(Submission.created_at.desc())).all()
    return [submission_out(s, x) for x in subs]


@router.get("/assignments/{aid}/stats", response_model=StatsOut, summary="Топ бойынша статистика")
def stats(aid: int, top: int = 8, s: Session = Depends(get_session), _: User = Depends(require_teacher)):
    return assignment_stats(s, _get(s, aid), top)
