"""Stages ②–④ glued together, independent of the web layer and of the database.

    ② format  (program)  → ③ ocr (LLM, photos only) → ④ review (LLM) → ④b citation check (program)

If ② fails the whole check fails (that is a bug or a broken file). If ③/④ fail because the
LLM is unavailable, the report is still produced from ② and the AI error is shown honestly.
"""
from __future__ import annotations

import logging
import pathlib
from dataclasses import dataclass, field
from typing import Callable, Literal

from . import format_checker as fc
from .llm import LLMUnavailable
from .review import (docx_images, docx_to_text, lines_to_text, ocr_handwritten, review_work,
                     verify_citations)

log = logging.getLogger("olshem.pipeline")
Kind = Literal["docx", "pdf", "photos"]


@dataclass
class Materials:
    """What the teacher uploaded for the assignment."""
    requirement_files: list[pathlib.Path] = field(default_factory=list)
    requirement_text: str = ""
    syllabus_file: pathlib.Path | None = None


@dataclass
class Outcome:
    format_results: list[dict]
    meta: dict
    review: dict | None = None
    model: str | None = None
    ai_error: str | None = None
    ocr: dict | None = None


def analyze(kind: Kind, files: list[pathlib.Path], checklist: dict, materials: Materials,
            on_stage: Callable[[str], None] = lambda s: None, extra_names: list[str] | None = None,
            skip_ai: str | None = None) -> Outcome:
    """skip_ai: reason string to skip the LLM stages (e.g. demo mode without a cached result)."""
    ocr = None
    if kind == "docx":
        on_stage("format")
        fmt, meta = fc.run_checks(files[0], checklist)
        text = docx_to_text(files[0], extra_names)
        images = docx_images(files[0])
    elif kind == "pdf":
        on_stage("format")
        fmt, meta, lines = fc.run_checks_pdf(files[0], checklist)
        text, images = lines_to_text(lines, extra_names), []
    else:
        if skip_ai:
            return Outcome(fc.run_checks_text([], checklist), {"pages": len(files), "kind": "photos"},
                           ai_error=skip_ai)
        on_stage("ocr")
        try:
            o, _ = ocr_handwritten(files)
        except LLMUnavailable as e:
            raise RuntimeError(f"Қолжазбаны тану мүмкін болмады: {e}") from e
        ocr = o.model_dump()
        lines = o.text.splitlines()
        on_stage("format")
        fmt = fc.run_checks_text(lines, checklist)
        meta = {"pages": len(files), "kind": "photos", "tables": None, "images": None}
        text, images = lines_to_text(lines, extra_names), []

    if skip_ai:
        return Outcome(fmt, meta, ai_error=skip_ai, ocr=ocr)
    on_stage("review")
    try:
        rv, model = review_work(text, images, checklist, fmt, materials.syllabus_file,
                                materials.requirement_files, materials.requirement_text,
                                note="Жұмыс қолжазбадан OCR арқылы алынды; оқылмаған жерлерді қате деп санама."
                                if kind == "photos" else "")
        review = verify_citations(rv.model_dump(), text)
        return Outcome(fmt, meta, review, model, ocr=ocr)
    except LLMUnavailable as e:
        return Outcome(fmt, meta, ai_error=str(e), ocr=ocr)
    except Exception as e:  # noqa: BLE001 — malformed model output etc.
        log.exception("review failed")
        return Outcome(fmt, meta, ai_error=f"ЖИ жауабын өңдеу мүмкін болмады: {str(e)[:200]}", ocr=ocr)
