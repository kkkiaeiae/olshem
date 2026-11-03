"""Public API schemas (what SMART.ENU or any other client sees in /docs)."""
from __future__ import annotations

import datetime as dt
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from ..core.requirements import Checklist


class CourseOut(BaseModel):
    id: int
    name: str
    code: str


class AssignmentOut(BaseModel):
    id: int
    course: CourseOut
    title: str
    type: str
    deadline: Optional[dt.date]
    requirement_files: list[str] = Field(description="Жүктелген талап файлдарының атаулары")
    has_requirement_text: bool
    has_syllabus: bool
    checklist_status: Literal["extracting", "ready", "error"]
    checklist_error: Optional[str]
    checklist_model: Optional[str]
    checklist_confirmed: bool
    checklist: Optional[Checklist]
    is_demo: bool
    submissions_count: int = 0
    created_at: dt.datetime


class ChecklistUpdate(BaseModel):
    checklist: Checklist
    confirm: bool = Field(True, description="true — тізімді растап, студенттерге ашу")


class StageOut(BaseModel):
    key: str
    label: str
    state: Literal["done", "active", "pending", "skipped", "error"]


class SubmissionOut(BaseModel):
    id: str
    assignment_id: int
    assignment_title: str
    student_label: str
    kind: Literal["docx", "pdf", "photos"]
    original_name: str
    status: Literal["queued", "format", "ocr", "review", "done", "error"]
    stages: list[StageOut]
    elapsed_s: Optional[float]
    compliance_pct: Optional[int] = Field(description="Талаптарға сәйкестік (бағдарлама есептейді)")
    ai_score: Optional[int] = Field(description="Мазмұн бағасы — ЖИ ұсынысы, соңғы баға оқытушыда")
    model_used: Optional[str]
    ai_error: Optional[str]
    error: Optional[str]
    demo: bool
    problems: int = 0
    report_url: Optional[str]
    created_at: dt.datetime
    finished_at: Optional[dt.datetime]
    results: Optional[dict[str, Any]] = Field(None, description="format_results, review, meta (тек done кезінде)")


class TopProblem(BaseModel):
    rule_id: str
    text_kk: str
    source: Literal["Бағдарлама", "ЖИ"]
    failed: int = Field(description="«сәйкес емес» саны")
    partial: int = Field(description="«ішінара» саны")
    share_pct: int = Field(description="Тексерілген жұмыстардың қанша пайызында мәселе бар")


class StatsOut(BaseModel):
    assignment_id: int
    submissions_total: int
    submissions_done: int
    avg_compliance_pct: Optional[float]
    avg_ai_score: Optional[float]
    compliance_buckets: dict[str, int]
    top_problems: list[TopProblem]


class ModelStatus(BaseModel):
    status: str
    latency_s: Optional[float] = None
    code: Optional[int] = None
    detail: Optional[str] = None


class HealthOut(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    demo_mode: bool
    ai_configured: bool
    libreoffice: bool
    models: dict[str, ModelStatus]
    stage_chains: dict[str, list[str]]


class DemoModeIn(BaseModel):
    enabled: bool
