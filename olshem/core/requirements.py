"""Stage ①: teacher's free-form requirements (PDF / photo / text) -> structured checklist.

Rules with check="auto" carry a machine metric that the format checker executes exactly;
rules with check="ai" are judged by the LLM in stage ④. The teacher must confirm (and may
edit) the checklist before students can submit."""
from __future__ import annotations

import pathlib
from typing import Literal, Optional

from pydantic import BaseModel, Field

from .llm import call_json, file_part

Metric = Literal[
    "margin_left_cm", "margin_right_cm", "margin_top_cm", "margin_bottom_cm",
    "font_name", "font_size_pt", "line_spacing", "first_line_indent_cm",
    "page_count", "page_number_position", "required_sections",
    "table_caption", "references_min", "references_order", "none"]

METRICS: tuple[str, ...] = Metric.__args__  # type: ignore[attr-defined]


class RuleLLM(BaseModel):
    """Shape the LLM must return (kept minimal so the response schema stays simple)."""
    id: str
    category: Literal["рәсімдеу", "құрылым", "мазмұн", "әдебиет", "көлем"]
    text_kk: str
    check: Literal["auto", "ai"]
    metric: Metric
    value: Optional[str] = None
    min: Optional[float] = None
    max: Optional[float] = None
    items: Optional[list[str]] = None
    severity: Literal["критикалық", "маңызды", "ұсыныс"]
    source_quote: str


class ChecklistLLM(BaseModel):
    course: str
    assignment: str
    rules: list[RuleLLM]


class Rule(RuleLLM):
    """Rule as stored and edited by the teacher."""
    source_quote: str = ""
    enabled: bool = True
    optional: bool = Field(False, description="Ұсыныс ретінде көрсетіледі, сәйкестік пайызына кірмейді")
    exclude_appendix: bool = Field(False, description="page_count: қосымшаларды бет санына қоспау")
    skip_result_tables: bool = Field(False, description="table_caption: «Нәтиже:» кестелерін есептемеу")


class Checklist(BaseModel):
    course: str = ""
    assignment: str = ""
    rules: list[Rule] = []


SYSTEM = """Сен ЕҰУ оқытушысының талаптарын құрылымдалған тексеру тізіміне айналдыратын көмекшісің.
Rules:
- Extract EVERY verifiable requirement for the student's written work (formatting, structure, content, references, volume). Do not invent requirements that are not in the source.
- Use check="auto" ONLY when the requirement maps to one of the metrics; fill value/min/max/items so a program can verify it. Font names: join alternatives with "|". Numbers in cm or pt without units.
- required_sections: items = section titles exactly as they should appear (uppercase as in source), e.g. КІРІСПЕ, ҚОРЫТЫНДЫ.
- page_count: min/max pages. references_min: minimum number of sources if stated, otherwise skip.
- table_caption: value = the caption pattern quoted (e.g. "Кесте-1").
- Everything about meaning/quality (goal stated in introduction, conclusions match tasks, literature review, figures referenced in text, topic agreed with syllabus, code/SQL correctness) -> check="ai", metric="none".
- text_kk: short clear Kazakh sentence. source_quote: verbatim fragment of the source.
- id: "rule-1", "rule-2", ...
- severity: критикалық = work is not accepted without it; маңызды = affects grade; ұсыныс = recommendation."""


def extract_checklist(files: list[str | pathlib.Path], text: str = "", note: str = "") -> tuple[Checklist, str]:
    parts: list = [file_part(f) for f in files]
    if text.strip():
        parts.append("ОҚЫТУШЫНЫҢ ТАЛАПТАРЫ (мәтін):\n" + text.strip())
    parts.append("Оқытушының қосымша ескертпесі: " + (note.strip() or "жоқ"))
    parts.append("Осы материалдардан студенттің жазбаша жұмысына қойылатын талаптар тізімін құр.")
    obj, model = call_json("extract", parts, ChecklistLLM, SYSTEM)
    return normalize(Checklist.model_validate(obj.model_dump())), model


def normalize(cl: Checklist) -> Checklist:
    """Defensive clean-up of LLM output: unique ids, ai rules have metric none, auto rules have a metric."""
    seen: set[str] = set()
    for i, r in enumerate(cl.rules, 1):
        if not r.id or r.id in seen:
            r.id = f"rule-{i}"
        seen.add(r.id)
        if r.check == "ai":
            r.metric = "none"
        elif r.metric == "none":
            r.check = "ai"
        if r.items:
            r.items = [x.strip() for x in r.items if x and x.strip()]
    return cl
