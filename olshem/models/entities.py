"""Data model (SQLite via SQLModel). Designed to map 1:1 onto SMART.ENU entities:
Course ↔ discipline (пән), Assignment ↔ task inside a discipline, Submission ↔ student's upload.
JSON columns hold the structured checklist / results so the schema stays stable while rules evolve."""
from __future__ import annotations

import datetime as dt
import uuid
from typing import Any, Optional

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel

ASSIGNMENT_TYPES = ("курстық", "БӨЖ", "реферат", "эссе", "зертханалық")
SUBMISSION_STATUSES = ("queued", "format", "ocr", "review", "done", "error")
CHECKLIST_STATUSES = ("extracting", "ready", "error")


def now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def aware(t: dt.datetime | None) -> dt.datetime | None:
    return t.replace(tzinfo=dt.timezone.utc) if t is not None and t.tzinfo is None else t


class Course(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    code: str = ""
    external_id: Optional[str] = Field(default=None, description="SMART.ENU / Platonus discipline id")


class Assignment(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    course_id: int = Field(foreign_key="course.id", index=True)
    title: str
    type: str = "курстық"
    deadline: Optional[dt.date] = None
    requirement_files: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    requirement_text: str = ""
    syllabus_file: Optional[str] = None
    checklist_json: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    checklist_confirmed: bool = False
    checklist_status: str = "extracting"
    checklist_error: Optional[str] = None
    checklist_model: Optional[str] = None
    is_demo: bool = False
    created_at: dt.datetime = Field(default_factory=now)


class Submission(SQLModel, table=True):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:16], primary_key=True)
    assignment_id: int = Field(foreign_key="assignment.id", index=True)
    student_label: str = ""
    file_path: str = ""                       # first file (docx/pdf) — kept for the spec'd model
    file_paths: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    original_name: str = ""
    file_sha256: str = ""
    kind: str = "docx"                        # docx | pdf | photos
    status: str = "queued"
    stage_started_at: Optional[dt.datetime] = None
    format_result_json: Optional[list[dict[str, Any]]] = Field(default=None, sa_column=Column(JSON))
    meta_json: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    review_json: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    ocr_json: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    compliance_pct: Optional[int] = None
    ai_score: Optional[int] = None
    model_used: Optional[str] = None
    ai_error: Optional[str] = None
    error: Optional[str] = None
    demo: bool = False
    created_at: dt.datetime = Field(default_factory=now)
    finished_at: Optional[dt.datetime] = None


class Setting(SQLModel, table=True):
    key: str = Field(primary_key=True)
    value: str
