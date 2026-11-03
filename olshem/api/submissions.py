from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from sqlmodel import Session

from ..core.report import render
from ..models.db import get_session, session_scope
from ..models.entities import Assignment, Course, Submission
from ..models.schemas import SubmissionOut
from ..services import jobs, storage
from ..services.serializers import submission_out
from .deps import User, current_user, require_teacher

router = APIRouter(prefix="/api/submissions", tags=["Жұмыстар"])


def _get(s: Session, sid: str) -> Submission:
    sub = s.get(Submission, sid)
    if not sub:
        raise HTTPException(404, "Жұмыс табылмады")
    return sub


@router.get("/{sid}", response_model=SubmissionOut, summary="Тексеру күйі және нәтижесі (polling)")
def get_submission(sid: str, results: bool = False, s: Session = Depends(get_session)):
    return submission_out(s, _get(s, sid), with_results=results)


@router.get("/{sid}/events", summary="Тексеру барысы — Server-Sent Events")
async def events(sid: str, request: Request):
    async def gen():
        last = None
        for _ in range(900):  # ≤ 15 min
            if await request.is_disconnected():
                return
            with session_scope() as s:
                sub = s.get(Submission, sid)
                if not sub:
                    yield "event: error\ndata: {}\n\n"
                    return
                data = submission_out(s, sub).model_dump_json()
                status = sub.status
            if data != last:
                yield f"data: {data}\n\n"
                last = data
            if status in ("done", "error"):
                return
            await asyncio.sleep(1)
    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@router.get("/{sid}/report", response_class=HTMLResponse, summary="Қазақ тіліндегі HTML есеп")
def report(sid: str, embed: bool = False, s: Session = Depends(get_session)):
    sub = _get(s, sid)
    if sub.status != "done":
        raise HTTPException(409, "Тексеру әлі аяқталған жоқ")
    a = s.get(Assignment, sub.assignment_id)
    c = s.get(Course, a.course_id)
    cl = a.checklist_json or {"rules": []}
    title = (sub.student_label or sub.original_name or "Жұмыс")
    if sub.original_name and sub.student_label:
        title = f"{sub.student_label} — {sub.original_name}"
    html = render(title, f"{c.name} · {a.title}", sub.format_result_json or [], sub.review_json,
                  sub.meta_json or {}, sub.model_used, cl, demo=sub.demo, ai_error=sub.ai_error,
                  ocr=sub.ocr_json, checked_at=sub.finished_at, embed=embed)
    return HTMLResponse(html, headers={"X-Robots-Tag": "noindex"})


@router.post("/{sid}/retry", response_model=SubmissionOut, status_code=202, summary="Тексеруді қайта іске қосу")
def retry(sid: str, s: Session = Depends(get_session), _: User = Depends(current_user)):
    sub = _get(s, sid)
    if sub.status not in ("done", "error"):
        raise HTTPException(409, "Тексеру әлі жүріп жатыр")
    sub.status, sub.error, sub.ai_error, sub.finished_at = "queued", None, None, None
    s.add(sub); s.commit(); s.refresh(sub)
    jobs.submit(jobs.run_submission, sub.id)
    return submission_out(s, sub)


@router.delete("/{sid}", status_code=204, summary="Жұмысты және оның файлдарын жою")
def delete(sid: str, s: Session = Depends(get_session), _: User = Depends(require_teacher)):
    sub = _get(s, sid)
    storage.delete(sub.file_paths)
    s.delete(sub); s.commit()

