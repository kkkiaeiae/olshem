"""Stage ③ (OCR of handwritten work) and stage ④ (AI content review) + citation verification.

Stage ④ gets: the teacher's original requirements, the syllabus, the ai-rules of the
checklist, the deterministic format results (as context only), the anonymised full text
and up to 6 figures from the work. Every AI verdict must carry a verbatim quote; quotes
are then verified programmatically against the work text (stage ④b) and verdicts whose
evidence cannot be found are downgraded to «тексерілмеді»."""
from __future__ import annotations

import pathlib
import re
from typing import Literal

import docx
from pydantic import BaseModel

from docx.table import Table

from .format_checker import is_heading, iter_blocks, norm
from .llm import bytes_part, call_json, file_part
from .privacy import redact_lines


# ---------------------------------------------------------------- document -> text
def docx_to_text(path: str | pathlib.Path, extra_names: list[str] | None = None) -> str:
    """Paragraphs and tables in document order; headings marked with «## »; anonymised."""
    d = docx.Document(str(path))
    raw: list[str] = []
    for b in iter_blocks(d):
        if isinstance(b, Table):
            for row in b.rows[:40]:
                cells = []
                for c in row.cells:
                    ct = norm(c.text)
                    if ct and (not cells or cells[-1] != ct):
                        cells.append(ct[:200])
                if cells:
                    raw.append("| " + " | ".join(cells))
            continue
        t = norm(b.text)
        if not t:
            continue
        raw.append(("## " if is_heading(b) or (t.isupper() and len(t) < 90) else "") + t)
    return "\n".join(redact_lines(raw, extra_names))


def lines_to_text(lines: list[str], extra_names: list[str] | None = None) -> str:
    out = []
    for t in redact_lines([norm(x) for x in lines], extra_names):
        out.append(("## " + t) if t.isupper() and len(t) < 90 else t)
    return "\n".join(out)


def docx_images(path: str | pathlib.Path, limit: int = 6) -> list:
    d = docx.Document(str(path))
    imgs = []
    for rel in d.part.rels.values():
        if "image" in rel.reltype and len(imgs) < limit:
            blob = rel.target_part.blob
            ct = rel.target_part.content_type
            if ct in ("image/png", "image/jpeg") and len(blob) > 15000:
                imgs.append(bytes_part(blob, ct))
    return imgs


# ---------------------------------------------------------------- stage ③ OCR
class OCRPage(BaseModel):
    page: int
    text: str
    confidence: Literal["жоғары", "орташа", "төмен"]
    unclear_fragments: list[str]


class OCR(BaseModel):
    pages: list[OCRPage]

    @property
    def text(self) -> str:
        return "\n".join(p.text for p in self.pages)


OCR_PROMPT = (
    "Бұл — студенттің қолжазба жұмысының фотосуреттері (әр сурет — бір бет, ретімен). "
    "Әр беттің мәтінін қазақ кирилл әліпбиімен ДӘЛ көшір. Қазақ әріптеріне ерекше назар аудар: "
    "ә ғ қ ң ө ұ ү һ і (оларды а г к н о у у х и деп ауыстырма). "
    "Сенімсіз оқылған сөзді [?сөз?] түрінде, мүлде оқылмайтынды [?] деп белгіле және unclear_fragments-ке жаз. "
    "Жолдарды сақта, тақырыптарды бөлек жолға жаз. Формулалар мен SQL/Python кодын сол күйінде сақта. "
    "Ештеңе қоспа және түзетпе — студент қалай жазса, солай. "
    "confidence: жоғары — барлығы анық; орташа — бірнеше сөз күмәнді; төмен — көп жері оқылмайды.")


def ocr_handwritten(image_paths: list[str | pathlib.Path]) -> tuple[OCR, str]:
    parts: list = []
    for i, p in enumerate(image_paths, 1):
        parts += [f"{i}-бет:", file_part(p)]
    parts.append(OCR_PROMPT)
    return call_json("ocr", parts, OCR)


# ---------------------------------------------------------------- stage ④ review
class Evidence(BaseModel):
    quote: str
    location: str


class AIRuleResult(BaseModel):
    id: str
    status: Literal["сәйкес", "ішінара", "сәйкес емес", "тексерілмеді"]
    found: str
    evidence: list[Evidence]
    suggestion: str


class SectionFeedback(BaseModel):
    section: str
    strength: str
    issue: str
    suggestion: str


class Review(BaseModel):
    summary_kk: str
    ai_rules: list[AIRuleResult]
    content_feedback: list[SectionFeedback]
    suggested_score: int
    score_reasoning: str
    teacher_attention: list[str]


SYSTEM = """Сен ЕҰУ оқытушысының көмекшісісің: студенттің жұмысын оқытушының талаптары мен силлабусқа сәйкес АЛДЫН АЛА тексересің.
Қатаң ережелер:
- Барлық жауап қазақ тілінде, түсінікті және сыпайы, студентке арналған.
- Әр тұжырымды жұмыстағы НАҚТЫ дәйексөзбен (quote) және орнымен (бөлім атауы) дәлелде. Дәйексөз жұмыс мәтінінен СӨЗБЕ-СӨЗ көшірілуі тиіс (10–30 сөз), оны бағдарлама тексереді. Дәлел таппасаң — "тексерілмеді" деп қой, ойдан шығарма.
- Бірдеңе ЖОҚ екенін айтсаң, оның болуы керек жеріндегі мәтінді дәйексөз ретінде келтір.
- Пішімдеуді (қаріп, өріс, интервал) бағалама — оны бағдарлама тексерді; оның нәтижесі саған тек контекст үшін беріледі.
- ai_rules: тек берілген ЖИ ережелерінің әрқайсысына дәл бір нәтиже, id сол күйінде.
- content_feedback: Кіріспе (мақсат/міндеттер), теориялық бөлім, практикалық бөлім (SQL/Python/код дұрыстығы), қорытынды (міндеттерге жауап бере ме) бойынша 4-6 нақты пікір.
- Код немесе SQL сұратымдарында қате, мәтін мен код арасында қайшылық (мысалы, мәтінде бір ДББЖ, кодта басқасы) болса, нақты көрсет.
- suggested_score 0-100: тек ұсыныс, соңғы баға — оқытушыда. score_reasoning қысқа.
- teacher_attention: оқытушы өзі қарауы керек күмәнді жерлер (тақырып тізімде жоқ, плагиатқа күдік, суреттердің сапасы, OCR оқи алмаған жерлер).
- [ЖАСЫРЫЛДЫ] — жасырылған жеке деректер; оларды болжама."""


def review_work(work_text: str, images: list, checklist: dict, format_results: list[dict],
                syllabus_pdf: str | pathlib.Path | None = None,
                requirement_files: list[str | pathlib.Path] | None = None,
                requirements_text: str = "", note: str = "") -> tuple[Review, str]:
    ai_rules = [r for r in checklist["rules"] if r["check"] == "ai" and r.get("enabled", True)]
    fmt = "\n".join(f"- {r['text_kk']}: {r['status']} ({r['found']})" for r in format_results)
    parts: list = []
    for f in requirement_files or []:
        parts += ["ОҚЫТУШЫНЫҢ ТАЛАПТАРЫ (түпнұсқа):", file_part(f)]
    if requirements_text:
        parts.append("ОҚЫТУШЫНЫҢ ТАЛАПТАРЫ (мәтін):\n" + requirements_text)
    if syllabus_pdf:
        parts += ["СИЛЛАБУС:", file_part(syllabus_pdf)]
    parts.append("ЖИ ТЕКСЕРЕТІН ЕРЕЖЕЛЕР:\n" + "\n".join(
        f"- id={r['id']} [{r['severity']}] {r['text_kk']}" for r in ai_rules))
    parts.append("БАҒДАРЛАМАЛЫҚ ПІШІМ ТЕКСЕРУ НӘТИЖЕСІ (тек контекст):\n" + (fmt or "жоқ"))
    if note:
        parts.append("ЕСКЕРТПЕ: " + note)
    if images:
        parts.append(f"ЖҰМЫСТАҒЫ СУРЕТТЕР ({len(images)}): диаграммалар/скриншоттар — мазмұнға сай ма, оқылады ма?")
        parts += images
    parts.append("СТУДЕНТ ЖҰМЫСЫНЫҢ МӘТІНІ (## = тақырып):\n" + work_text)
    review, model = call_json("judge", parts, Review, SYSTEM)
    # keep exactly the requested rules, in order
    got = {r.id: r for r in review.ai_rules}
    review.ai_rules = [got.get(r["id"]) or AIRuleResult(id=r["id"], status="тексерілмеді",
                                                          found="ЖИ бұл ереже бойынша жауап бермеді",
                                                          evidence=[], suggestion="")
                       for r in ai_rules]
    review.suggested_score = max(0, min(100, review.suggested_score))
    return review, model


# ---------------------------------------------------------------- stage ④b citation verification
def _canon(s: str) -> str:
    s = s.lower().replace("ё", "е")
    return re.sub(r"[^0-9a-zа-яәғқңөұүһі]", "", s)


def quote_in_text(quote: str, canon_text: str) -> bool:
    q = _canon(quote)
    if len(q) < 6:
        return False
    if q in canon_text:
        return True
    # tolerate small edits by the model: 3 of 4 chunks must be present verbatim
    k = 4
    size = len(q) // k
    if size < 8:
        return False
    hits = sum(1 for i in range(k) if q[i * size:(i + 1) * size] in canon_text)
    return hits >= 3


def verify_citations(review: dict, work_text: str) -> dict:
    """Mark each evidence quote as verified/unverified. A verdict without any verified quote
    becomes «тексерілмеді» — the model is not allowed to assert what it cannot show."""
    canon = _canon(work_text)
    total = verified = downgraded = 0
    for r in review.get("ai_rules", []):
        ok_any = False
        for ev in r.get("evidence", []):
            ok = quote_in_text(ev.get("quote", ""), canon)
            ev["verified"] = ok
            total += 1
            verified += ok
            ok_any |= ok
        if r["status"] != "тексерілмеді" and not ok_any:
            r["model_status"] = r["status"]
            r["status"] = "тексерілмеді"
            r["found"] = ("ЖИ тұжырымы жұмыстағы дәйексөзбен расталмады, сондықтан есепке алынбады. "
                          f"(ЖИ пікірі: {r['found']})")
            downgraded += 1
    review["citations"] = {"total": total, "verified": verified, "downgraded": downgraded}
    return review
