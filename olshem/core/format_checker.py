"""Stage ②: deterministic format checks — no LLM here.

Every check="auto" rule is executed exactly, with locations (page number + text snippet)
for each problem. Page numbers come from rendering the .docx to PDF with LibreOffice.

Supported inputs:
* .docx  — full precision: inherited style resolution (run → paragraph style chain →
  docDefaults → theme fonts), margins from section properties, footer fields, tables;
* .pdf   — approximate: fonts/sizes from glyphs, margins from text bounding boxes;
* plain text lines (OCR of handwritten work) — structure and references only.

Lessons already learnt (do not regress):
1. first-line indent may live only in w:docDefaults;
2. table-of-contents lines (dot leaders + page number) are not section headings;
3. sentences like «Қорытындылай келе…» must not match the section ҚОРЫТЫНДЫ.
"""
from __future__ import annotations

import collections
import pathlib
import re
import shutil
import statistics
import subprocess
import tempfile
import threading
from typing import Any, Callable, Iterable

import docx
import pdfplumber
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

TOL = {"cm": 0.15, "pt": 0.5, "spacing": 0.05, "pdf_cm": 0.3}
KZ_ALPHA = "АӘБВГҒДЕЁЖЗИЙКҚЛМНҢОӨПРСТУҰҮФХҺЦЧШЩЪЫІЬЭЮЯ"
MONO = ("courier", "consolas", "mono", "menlo", "monaco", "lucida console", "source code")
OK, PART, BAD, NA = "сәйкес", "ішінара", "сәйкес емес", "тексерілмеді"

Result = dict[str, Any]


def norm(s: str | None) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def squash(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


# ---------------------------------------------------------------- style resolution
class Resolver:
    """Effective (inherited) formatting of runs and paragraphs."""

    def __init__(self, d: docx.document.Document):
        self.d = d
        st = d.styles.element
        self.rpr_def = st.find(qn("w:docDefaults") + "/" + qn("w:rPrDefault") + "/" + qn("w:rPr"))
        self.ppr_def = st.find(qn("w:docDefaults") + "/" + qn("w:pPrDefault") + "/" + qn("w:pPr"))
        self.theme = self._theme_fonts()

    def _theme_fonts(self) -> dict[str, str | None]:
        fonts: dict[str, str | None] = {}
        try:
            for rel in self.d.part.rels.values():
                if rel.reltype.endswith("/theme"):
                    x = rel.target_part.blob.decode("utf8", "ignore")
                    m = re.search(r"<a:majorFont><a:latin typeface=\"([^\"]+)\"", x)
                    n = re.search(r"<a:minorFont><a:latin typeface=\"([^\"]+)\"", x)
                    fonts = {"major": m and m.group(1), "minor": n and n.group(1)}
        except Exception:  # noqa: BLE001
            pass
        return fonts

    def _rfonts_name(self, rpr) -> str | None:
        if rpr is None:
            return None
        rf = rpr.find(qn("w:rFonts"))
        if rf is None:
            return None
        name = rf.get(qn("w:ascii")) or rf.get(qn("w:hAnsi")) or rf.get(qn("w:cs"))
        if name:
            return name
        th = rf.get(qn("w:asciiTheme")) or rf.get(qn("w:hAnsiTheme"))
        if th:
            return self.theme.get("major" if "major" in th else "minor")
        return None

    @staticmethod
    def _style_chain(style):
        while style is not None:
            yield style
            style = style.base_style

    def font_name(self, run, para) -> str:
        if run.font.name:
            return run.font.name
        n = self._rfonts_name(run._r.rPr)
        if n:
            return n
        for s in self._style_chain(para.style):
            if s.font.name:
                return s.font.name
            n = self._rfonts_name(s.element.rPr)
            if n:
                return n
        return self._rfonts_name(self.rpr_def) or "?"

    def font_size(self, run, para) -> float:
        if run.font.size:
            return run.font.size.pt
        for s in self._style_chain(para.style):
            if s.font.size:
                return s.font.size.pt
        if self.rpr_def is not None:
            sz = self.rpr_def.find(qn("w:sz"))
            if sz is not None:
                return int(sz.get(qn("w:val"))) / 2
        return 10.0

    def _pf(self, para, attr):
        v = getattr(para.paragraph_format, attr)
        if v is not None:
            return v
        for s in self._style_chain(para.style):
            v = getattr(s.paragraph_format, attr)
            if v is not None:
                return v
        return None

    def line_spacing(self, para):
        v = self._pf(para, "line_spacing")
        if v is None and self.ppr_def is not None:
            sp = self.ppr_def.find(qn("w:spacing"))
            if sp is not None and sp.get(qn("w:line")) and sp.get(qn("w:lineRule"), "auto") == "auto":
                return round(int(sp.get(qn("w:line"))) / 240, 2)
        if v is None:
            return 1.0
        if isinstance(v, float):
            return round(v, 2)
        return f"exact {v.pt:.0f}pt"

    def first_indent(self, para) -> float:
        v = self._pf(para, "first_line_indent")
        if v is not None:
            return round(v.cm, 2)
        if self.ppr_def is not None:  # document-wide default (w:docDefaults/w:pPrDefault/w:ind)
            ind = self.ppr_def.find(qn("w:ind"))
            if ind is not None:
                if ind.get(qn("w:firstLine")):
                    return round(int(ind.get(qn("w:firstLine"))) / 567, 2)
                if ind.get(qn("w:hanging")):
                    return round(-int(ind.get(qn("w:hanging"))) / 567, 2)
        return 0.0

    def dominant_font(self, p) -> str | None:
        names = collections.Counter(self.font_name(r, p) for r in p.runs if r.text.strip())
        return names.most_common(1)[0][0] if names else None

    def is_code(self, p) -> bool:
        n = (self.dominant_font(p) or "").lower()
        return any(m in n for m in MONO)


# ---------------------------------------------------------------- document walking
def iter_blocks(d) -> Iterable[Paragraph | Table]:
    for child in d.element.body.iterchildren():
        if child.tag == qn("w:p"):
            yield Paragraph(child, d)
        elif child.tag == qn("w:tbl"):
            yield Table(child, d)


def is_heading(p) -> bool:
    n = (p.style.name or "").lower() if p.style is not None else ""
    return n.startswith("heading") or n.startswith("заголовок") or n.startswith("title") or "toc" in n


def is_toc_line(t: str) -> bool:
    return bool(re.search(r"\.{4,}|…{2,}|\t", t))


def body_start_index(texts: list[str]) -> int:
    """Index of the real КІРІСПЕ heading (not the table-of-contents line with a page number)."""
    for i, t in enumerate(texts):
        u = norm(t).upper().rstrip(":")
        if u in ("КІРІСПЕ", "КIРIСПЕ", "ВВЕДЕНИЕ", "INTRODUCTION"):
            return i
    return 0


def body_paragraphs(paras, R: Resolver | None = None) -> tuple[list, int]:
    """Main-text paragraphs between КІРІСПЕ and the reference list.
    Headings, captions, short lines and monospace code are excluded. Returns (paras, code_count)."""
    start = body_start_index([p.text for p in paras])
    out, code = [], 0
    for p in paras[start + 1:]:
        t = norm(p.text)
        if t.upper().startswith("ПАЙДАЛАНЫЛҒАН"):
            break
        if len(t) < 80 or is_heading(p):
            continue
        if R is not None and R.is_code(p):
            code += 1
            continue
        out.append(p)
    return out, code


# ---------------------------------------------------------------- LibreOffice rendering
_lo_lock = threading.Lock()


def soffice_available() -> bool:
    return shutil.which("soffice") is not None


def render_pdf(path: str | pathlib.Path) -> pathlib.Path | None:
    """Convert to PDF with LibreOffice. Serialised with a lock: concurrent soffice runs that
    share a profile corrupt each other."""
    if not soffice_available():
        return None
    out = pathlib.Path(tempfile.mkdtemp(prefix="olshem_pdf_"))
    profile = pathlib.Path(tempfile.gettempdir()) / "olshem_lo_profile"
    with _lo_lock:
        subprocess.run(["soffice", f"-env:UserInstallation=file://{profile}", "--headless",
                        "--convert-to", "pdf", "--outdir", str(out), str(path)],
                       capture_output=True, timeout=240)
    return next(out.glob("*.pdf"), None)


def pdf_pages_text(pdf: pathlib.Path | None) -> list[str]:
    if not pdf:
        return []
    with pdfplumber.open(pdf) as p:
        return [squash(pg.extract_text() or "") for pg in p.pages]


def page_of(snippet: str, pages: list[str], start: int = 0) -> int | None:
    key = squash(snippet)[:35]
    for i in range(start, len(pages)):
        if key and key in pages[i]:
            return i + 1
    return None


# ---------------------------------------------------------------- helpers
def _issue(rule: dict, status: str, found: str, details: list[str] | None = None,
           stat: dict | None = None) -> Result:
    return {"id": rule["id"], "text_kk": rule["text_kk"], "severity": rule["severity"],
            "category": rule["category"], "status": status, "found": found,
            "details": details or [], "stat": stat, "optional": bool(rule.get("optional"))}


def _bounds(rule: dict) -> tuple[float | None, float | None]:
    lo, hi = rule.get("min"), rule.get("max")
    if lo is None and hi is None and rule.get("value"):
        try:
            lo = hi = float(str(rule["value"]).replace(",", "."))
        except ValueError:
            pass
    return lo, hi


def _within(x: float, rule: dict, tol: float) -> tuple[bool, float | None, float | None]:
    lo, hi = _bounds(rule)
    return (lo is None or x >= lo - tol) and (hi is None or x <= hi + tol), lo, hi


def _req(lo, hi, unit: str = "") -> str:
    if lo is not None and hi is not None and lo != hi:
        return f"{lo:g}–{hi:g}{unit}"
    if lo is not None and hi is not None:
        return f"{lo:g}{unit}"
    if lo is not None:
        return f"≥ {lo:g}{unit}"
    if hi is not None:
        return f"≤ {hi:g}{unit}"
    return "—"


def _share_status(share: float) -> str:
    return OK if share >= 95 else (PART if share >= 70 else BAD)


def _loc(p, pages) -> str:
    pg = page_of(p.text, pages)
    return f"б. {pg}: " if pg else ""


def check_paragraph_metric(rule, paras, get: Callable, unit: str, tol: float, pages, label: str,
                           code_skipped: int = 0) -> Result:
    """Compute a property for every body paragraph; report the compliant share + examples."""
    bad, total, counter = [], 0, collections.Counter()
    for p in paras:
        v = get(p)
        if v is None:
            continue
        total += 1
        counter[v] += 1
        ok = _within(v, rule, tol)[0] if isinstance(v, (int, float)) else False
        if not ok:
            bad.append((p, v))
    if total == 0:
        return _issue(rule, NA, "Негізгі мәтін абзацтары табылмады")
    share = 100 * (total - len(bad)) / total
    common = ", ".join(f"{k}{unit} — {c}" for k, c in counter.most_common(3))
    details = [f"{_loc(p, pages)}«{norm(p.text)[:70]}…» — {v}{unit}" for p, v in bad[:4]]
    if code_skipped:
        details.append(f"Моноширинді қаріптегі {code_skipped} код абзацы есептелмеді")
    lo, hi = _bounds(rule)
    return _issue(rule, _share_status(share),
                  f"{label}: {share:.0f}% абзац талапқа сай (талап: {_req(lo, hi, unit)}; жұмыста: {common})",
                  details, {"compliant_pct": round(share), "bad": len(bad), "total": total})


# ---------------------------------------------------------------- text-level checks (docx / pdf / ocr)
def check_sections(rule: dict, texts: list[str]) -> Result:
    """texts — all paragraph/line texts of the document, in order."""
    start = body_start_index(texts)
    body = [norm(t).upper() for t in texts[start:]]
    front = [norm(t).upper() for t in texts[:120]]
    head = " ".join(front[:25])
    missing, partial = [], []
    heads = [t for t in body if 0 < len(t) < 70 and not is_toc_line(t)]
    for item in rule.get("items") or []:
        it = norm(item).upper()
        if it == "ТИТУЛДЫҚ БЕТ":
            if "УНИВЕРСИТЕТ" not in head:
                missing.append(item)
        elif it == "ТАПСЫРМА":
            if not any(t.rstrip(":") == "ТАПСЫРМА" or t.startswith("КУРСТЫҚ ЖҰМЫСҚА ТАПСЫРМА") for t in front):
                missing.append(item)
        elif it == "МАЗМҰНЫ":
            if not any(t.startswith("МАЗМҰНЫ") or t.startswith("МАЗМҰН") for t in front):
                missing.append(item)
        elif it == "НЕГІЗГІ БӨЛІМ":
            if not any(re.match(r"^\d[\.\s]", t) for t in heads):
                missing.append(item)
        else:
            # a real heading: short line, no TOC leaders, word boundary right after the title
            if any(t == it or re.match(re.escape(it) + r"(\W|$)", t) for t in heads):
                continue
            first = it.split()[0]
            alt = next((t for t in heads if re.match(re.escape(first) + r"(\W|$)", t)), None)
            (partial if alt else missing).append(item + (f" (жұмыста: «{alt}»)" if alt else ""))
    n = len(rule.get("items") or [])
    st = OK if not missing and not partial else (PART if not missing else BAD)
    det = [f"Жоқ: {x}" for x in missing] + [f"Атауы өзгеше: {x}" for x in partial]
    return _issue(rule, st, f"{n - len(missing) - len(partial)}/{n} бөлім талапқа сай", det)


def extract_references(texts: list[str], stop: Callable[[str], bool] | None = None,
                       strip_numbers: bool = True) -> list[str]:
    start_body = body_start_index(texts)
    start = next((i for i, t in enumerate(texts) if norm(t).upper().startswith("ПАЙДАЛАНЫЛҒАН")
                  and i > start_body and not is_toc_line(norm(t))), None)
    refs: list[str] = []
    if start is None:
        return refs
    for t in texts[start + 1:]:
        t = norm(t)
        if not t:
            continue
        if t.upper().startswith("ҚОСЫМША") or (stop and stop(t)):
            break
        if t.isdigit():  # page number line in PDF/OCR text
            continue
        refs.append(re.sub(r"^\[?\d+[\.\)\]]\s*", "", t) if strip_numbers else t)
    return refs


GOV_RE = re.compile(r"Заң[ыы]?\b|Кодекс|Жарлығ|Жарлық|Қаулы|Конституция|Бұйрығ|Закон\b|Указ\b|Постановлени|"
                    r"Республикасының\s+(Заңы|Үкіметінің|Президентінің)|нормативтік", re.I)


def _ref_key(s: str):
    c = s[:1].upper()
    return (0, KZ_ALPHA.index(c)) if c in KZ_ALPHA else (1, ord(c) if c else 0)


def check_references(rule: dict, refs: list[str]) -> Result:
    if rule["metric"] == "references_min":
        ok, lo, _ = _within(len(refs), rule, 0)
        return _issue(rule, OK if ok else BAD, f"{len(refs)} дереккөз (талап: {_req(lo, None)})")
    if not refs:
        return _issue(rule, NA, "Пайдаланылған әдебиеттер тізімі табылмады")
    wrong: list[str] = []
    rule_txt = (rule.get("text_kk", "") + " " + rule.get("source_quote", "")).lower()
    gov_first = bool(re.search(r"үкімет|нормативт|заң|закон", rule_txt))
    rest = refs
    if gov_first:  # «ең бірінші үкімет орындарының құжаттары, содан кейін алфавит бойынша»
        is_gov = [bool(GOV_RE.search(r[:120])) for r in refs]
        lead = 0
        while lead < len(refs) and is_gov[lead]:
            lead += 1
        wrong += [f"Нормативтік құжат тізімнің басында болуы керек: «{refs[i][:50]}» ({i + 1}-орында)"
                  for i in range(lead, len(refs)) if is_gov[i]]
        rest = [r for r, g in zip(refs, is_gov) if not g]
    wrong += [f"«{rest[i][:40]}» → «{rest[i + 1][:40]}»" for i in range(len(rest) - 1)
              if _ref_key(rest[i]) > _ref_key(rest[i + 1])]
    return _issue(rule, OK if not wrong else BAD,
                  f"{len(refs)} дереккөз; рет бұзылған жерлер: {len(wrong)}", wrong[:5])


# ---------------------------------------------------------------- .docx
def run_checks(docx_path: str | pathlib.Path, checklist: dict) -> tuple[list[Result], dict]:
    d = docx.Document(str(docx_path))
    R = Resolver(d)
    paras = d.paragraphs
    texts = [p.text for p in paras]
    body, code_skipped = body_paragraphs(paras, R)
    pdf = render_pdf(docx_path)
    pages = pdf_pages_text(pdf)
    sec = d.sections[0]
    results: list[Result] = []

    for rule in [r for r in checklist["rules"] if r["check"] == "auto" and r.get("enabled", True)]:
        m = rule["metric"]
        try:
            if m.startswith("margin_"):
                side = m.split("_")[1]
                val = getattr(sec, f"{side}_margin").cm
                ok, lo, hi = _within(val, rule, TOL["cm"])
                results.append(_issue(rule, OK if ok else BAD,
                                      f"Құжатта: {val:.2f} см (талап: {_req(lo, hi, ' см')})"))
            elif m == "font_name":
                allowed = [a.strip().lower() for a in (rule.get("value") or "").split("|") if a.strip()]
                bad, cnt = [], collections.Counter()
                for p in body:
                    n = R.dominant_font(p)
                    if not n:
                        continue
                    cnt[n] += 1
                    if n.lower() not in allowed:
                        bad.append((p, n))
                tot = sum(cnt.values())
                if not tot:
                    results.append(_issue(rule, NA, "Негізгі мәтін абзацтары табылмады"))
                    continue
                share = 100 * (tot - len(bad)) / tot
                det = [f"{_loc(p, pages)}«{norm(p.text)[:70]}…» — {n}" for p, n in bad[:4]]
                if code_skipped:
                    det.append(f"Моноширинді қаріптегі {code_skipped} код абзацы есептелмеді")
                results.append(_issue(rule, _share_status(share),
                                      "Қаріптер: " + ", ".join(f"{k} — {v}" for k, v in cnt.most_common(3)),
                                      det, {"compliant_pct": round(share), "bad": len(bad), "total": tot}))
            elif m == "font_size_pt":
                def g(p):
                    s = collections.Counter(R.font_size(r, p) for r in p.runs if r.text.strip())
                    return s.most_common(1)[0][0] if s else None
                results.append(check_paragraph_metric(rule, body, g, " pt", TOL["pt"], pages, "Қаріп өлшемі", code_skipped))
            elif m == "line_spacing":
                results.append(check_paragraph_metric(rule, body, R.line_spacing, "", TOL["spacing"], pages,
                                                      "Жоларалық интервал", code_skipped))
            elif m == "first_line_indent_cm":
                results.append(check_paragraph_metric(rule, body, R.first_indent, " см", TOL["cm"], pages,
                                                      "Абзац шегінісі", code_skipped))
            elif m == "page_count":
                results.append(_page_count(rule, pages, texts))
            elif m == "page_number_position":
                xml = "".join(s.footer._element.xml for s in d.sections
                              if not s.footer.is_linked_to_previous or s is d.sections[0])
                has_page = "PAGE" in xml
                center = 'w:val="center"' in xml
                st = OK if has_page and center else (PART if has_page else BAD)
                results.append(_issue(rule, st, "Төменгі колонтитулда бет нөмірі " + ("бар" if has_page else "жоқ")
                                      + (", ортада" if center else ", ортада емес" if has_page else "")))
            elif m == "required_sections":
                results.append(check_sections(rule, texts))
            elif m == "table_caption":
                results.append(_table_captions(rule, d, pages))
            elif m in ("references_order", "references_min"):
                hp = {norm(p.text) for p in paras if is_heading(p)}
                results.append(check_references(rule, extract_references(texts, stop=lambda t: t in hp)))
            else:
                results.append(_issue(rule, NA, f"'{m}' метрикасы үшін тексеру жоқ"))
        except Exception as e:  # noqa: BLE001 — one broken rule must not break the report
            results.append(_issue(rule, NA, f"Тексеру кезінде қате: {e}"))
    meta = {"pages": len(pages) or None, "body_paragraphs": len(body), "code_paragraphs": code_skipped,
            "tables": len(d.tables), "images": len(d.inline_shapes), "kind": "docx"}
    return results, meta


def _page_count(rule: dict, pages: list[str], texts: list[str]) -> Result:
    if not pages:
        return _issue(rule, NA, "Бет санын анықтау мүмкін болмады (LibreOffice жоқ)")
    n = len(pages)
    note = ""
    if rule.get("exclude_appendix"):
        refs = next((t for t in texts if norm(t).upper().startswith("ПАЙДАЛАНЫЛҒАН")), None)
        ref_page = None
        if refs:  # the last page that mentions the reference heading = the real heading, not the TOC
            key = squash(refs)[:25]
            hits = [i for i, pg in enumerate(pages) if key in pg]
            ref_page = hits[-1] if hits else None
        app_idx = next((i for i in range((ref_page or 0) + 1, n)
                        if re.match(r"^ҚОСЫМША", pages[i].upper())), None)
        if app_idx is not None:
            note = f" — қосымшалар есептелмеді, жалпы {n} бет"
            n = app_idx
    ok, lo, hi = _within(n, rule, 0)
    return _issue(rule, OK if ok else BAD, f"Құжатта {n} бет (талап: {_req(lo, hi)}){note}",
                  stat={"pages": n})


def _table_captions(rule: dict, d, pages) -> Result:
    blocks = list(iter_blocks(d))
    total, good, results_tables, det = 0, 0, 0, []
    for i, b in enumerate(blocks):
        if not isinstance(b, Table):
            continue
        prev = [norm(x.text) for x in blocks[max(0, i - 2):i] if isinstance(x, Paragraph) and norm(x.text)]
        cap = prev[-1] if prev else ""
        if rule.get("skip_result_tables") and re.match(r"^Нәтиже", cap, re.I):
            results_tables += 1
            continue
        total += 1
        if re.search(r"Кесте\s*[-–—]?\s*\d", " ".join(prev), re.I):
            good += 1
        else:
            det.append(f"{total}-кесте алдында: " + (f"«{cap[:50]}»" if cap else "атауы жоқ"))
    if not total:
        return _issue(rule, NA, "Құжатта кесте жоқ")
    note = f" («Нәтиже:» кестелері есептелмеді: {results_tables})" if results_tables else ""
    st = OK if good == total else (PART if good else BAD)
    return _issue(rule, st, f"{total} кестенің {good}-і «Кесте-N» үлгісімен белгіленген{note}", det[:5],
                  {"compliant_pct": round(100 * good / total), "bad": total - good, "total": total})


# ---------------------------------------------------------------- .pdf (approximate)
def _font_family(fontname: str) -> str:
    n = fontname.split("+", 1)[-1]
    n = re.sub(r"[-,](Bold|Italic|BoldItalic|Regular|Oblique).*$", "", n, flags=re.I)
    n = re.sub(r"(PSMT|PS|MT)$", "", n)
    return n


def _flat(s: str) -> str:
    return re.sub(r"[^a-zа-яәғқңөұүһі]", "", s.lower())


def run_checks_pdf(pdf_path: str | pathlib.Path, checklist: dict) -> tuple[list[Result], dict, list[str]]:
    """Returns (results, meta, text lines). Margins/fonts measured from glyph positions."""
    cm = 2.54 / 72
    lines: list[str] = []
    pages_sq: list[str] = []
    fonts, sizes = collections.Counter(), collections.Counter()
    margins: dict[str, list[float]] = {"left": [], "right": [], "top": [], "bottom": []}
    pnum_center, pnum_pages = 0, 0
    with pdfplumber.open(str(pdf_path)) as pdf:
        n_pages = len(pdf.pages)
        for pg in pdf.pages:
            txt = pg.extract_text() or ""
            lines += txt.splitlines()
            pages_sq.append(squash(txt))
            words = pg.extract_words(extra_attrs=["fontname", "size"])
            if not words:
                continue
            H, W = pg.height, pg.width
            body = []
            footer_nums = [w for w in words if w["text"].isdigit() and len(w["text"]) <= 3
                           and (w["top"] > H * 0.88 or w["bottom"] < H * 0.08)]
            if footer_nums:
                w = max(footer_nums, key=lambda w: w["bottom"])
                pnum_pages += 1
                if abs((w["x0"] + w["x1"]) / 2 - W / 2) < W * 0.08:
                    pnum_center += 1
            skip = {id(w) for w in footer_nums}
            for w in words:
                if id(w) in skip:
                    continue
                body.append(w)
                if not any(m in w["fontname"].lower() for m in MONO):
                    fonts[_font_family(w["fontname"])] += len(w["text"])
                    sizes[round(w["size"] * 2) / 2] += len(w["text"])
            if body:
                margins["left"].append(min(w["x0"] for w in body) * cm)
                margins["right"].append((W - max(w["x1"] for w in body)) * cm)
                margins["top"].append(min(w["top"] for w in body) * cm)
                margins["bottom"].append((H - max(w["bottom"] for w in body)) * cm)

    results: list[Result] = []
    total_chars = sum(fonts.values()) or 1
    for rule in [r for r in checklist["rules"] if r["check"] == "auto" and r.get("enabled", True)]:
        m = rule["metric"]
        try:
            if m.startswith("margin_"):
                side = m.split("_")[1]
                vals = margins[side]
                if not vals:
                    results.append(_issue(rule, NA, "PDF-те мәтін табылмады"))
                    continue
                val = statistics.median(vals)
                ok, lo, hi = _within(val, rule, TOL["pdf_cm"])
                if side in ("top", "bottom") and not ok and lo is not None and val > lo:
                    ok = True  # text block may end above the margin on a short page
                results.append(_issue(rule, OK if ok else BAD,
                                      f"Шамамен {val:.1f} см (мәтін шекарасы бойынша; талап: {_req(lo, hi, ' см')})",
                                      ["PDF-те өріс мәтіннің орналасуы бойынша есептеледі; дәл өлшеу үшін .docx жүктеңіз"]))
            elif m == "font_name":
                allowed = [_flat(a) for a in (rule.get("value") or "").split("|") if a.strip()]
                good = sum(c for f, c in fonts.items() if any(a and a in _flat(f) for a in allowed))
                share = 100 * good / total_chars
                results.append(_issue(rule, _share_status(share),
                                      f"Мәтін таңбаларының {share:.0f}% талапқа сай қаріппен ("
                                      + ", ".join(f"{k} — {round(100 * v / total_chars)}%" for k, v in fonts.most_common(3)) + ")",
                                      stat={"compliant_pct": round(share)}))
            elif m == "font_size_pt":
                good = sum(c for s, c in sizes.items() if _within(s, rule, TOL["pt"])[0])
                share = 100 * good / total_chars
                results.append(_issue(rule, _share_status(share),
                                      f"Таңбалардың {share:.0f}% талап етілген өлшемде ("
                                      + ", ".join(f"{k:g} pt — {round(100 * v / total_chars)}%" for k, v in sizes.most_common(3)) + ")",
                                      stat={"compliant_pct": round(share)}))
            elif m == "page_count":
                results.append(_page_count(rule, pages_sq, lines))
            elif m == "page_number_position":
                st = OK if pnum_pages and pnum_center >= 0.8 * pnum_pages else (PART if pnum_pages else BAD)
                results.append(_issue(rule, st, f"Бет нөмірі {pnum_pages} бетте табылды, оның {pnum_center}-і ортада"))
            elif m == "required_sections":
                results.append(check_sections(rule, lines))
            elif m in ("references_order", "references_min"):
                results.append(check_references(rule, _merge_ref_lines(extract_references(lines, strip_numbers=False))))
            else:
                results.append(_issue(rule, NA, "PDF файлында бұл талапты дәл өлшеу мүмкін емес — .docx жүктеңіз"))
        except Exception as e:  # noqa: BLE001
            results.append(_issue(rule, NA, f"Тексеру кезінде қате: {e}"))
    meta = {"pages": n_pages, "tables": None, "images": None, "kind": "pdf"}
    return results, meta, lines


def _merge_ref_lines(lines: list[str]) -> list[str]:
    """In PDF text a reference may wrap over several lines; a new entry starts with a number."""
    out: list[str] = []
    if not any(re.match(r"^\[?\d{1,3}[\.\)\]]\s", ln) for ln in lines):
        return lines
    for ln in lines:
        if re.match(r"^\[?\d{1,3}[\.\)\]]\s", ln) or not out:
            out.append(re.sub(r"^\[?\d{1,3}[\.\)\]]\s*", "", ln))
        else:
            out[-1] += " " + ln
    return out


# ---------------------------------------------------------------- OCR text (handwritten)
def run_checks_text(lines: list[str], checklist: dict) -> list[Result]:
    """For handwritten work only structure and references can be checked."""
    out = []
    for rule in [r for r in checklist["rules"] if r["check"] == "auto" and r.get("enabled", True)]:
        if rule["metric"] == "required_sections":
            out.append(check_sections(rule, lines))
        elif rule["metric"] in ("references_order", "references_min"):
            out.append(check_references(rule, _merge_ref_lines(extract_references(lines, strip_numbers=False))))
        else:
            out.append(_issue(rule, NA, "Қолжазба жұмыс: рәсімдеу талабы өлшенбейді"))
    return out
