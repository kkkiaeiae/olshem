"""Generator of synthetic course works (.docx) with controlled formatting defects.
Used by the unit tests and to seed the demo class with clearly labelled synthetic samples,
so no real student's work is ever needed for a public demo."""
from __future__ import annotations

import pathlib
import random
from dataclasses import dataclass, field

import docx
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt

SENTENCES = [
    "Деректер базасы ұйымның ақпаратын бір жерде сақтап, оны тиімді өңдеуге мүмкіндік береді.",
    "Реляциялық модельде деректер кестелер түрінде беріледі, ал кестелер арасындағы байланыс сыртқы кілттер арқылы жүзеге асады.",
    "SQL тілі деректерді анықтау, өзгерту және іздеу операцияларын біртұтас синтаксиспен орындауға мүмкіндік береді.",
    "Python тіліндегі sqlite3 модулі қосымша серверсіз жұмыс істейтін жеңіл деректер базасын пайдалануға жол ашады.",
    "Нормализация қайталанатын деректерді азайтып, жаңарту кезіндегі қайшылықтардың алдын алады.",
    "Сұратымдардың нәтижесі пайдаланушыға түсінікті кесте түрінде экранға шығарылады.",
    "Жобаның практикалық бөлімінде кестелер құрылып, оларға бастапқы деректер енгізілді.",
    "Индекстер үлкен кестелерде іздеу жылдамдығын едәуір арттырады, бірақ жазу операцияларын баяулатуы мүмкін.",
]
REFS_SORTED = [
    "Қазақстан Республикасының Заңы «Дербес деректер және оларды қорғау туралы». 2013.",
    "Әбдіғалиев Б. Деректер базасы негіздері. — Алматы, 2020.",
    "Сейітқали Н. Python тілінде бағдарламалау. — Астана, 2022.",
    "Elmasri R., Navathe S. Fundamentals of Database Systems. — Pearson, 2021.",
    "Silberschatz A., Korth H., Sudarshan S. Database System Concepts. — McGraw-Hill, 2020.",
]


@dataclass
class Spec:
    margins_cm: tuple[float, float, float, float] = (3, 1, 2, 2)  # left, right, top, bottom
    font: str = "Times New Roman"
    size_pt: float = 14
    spacing: float = 1.0
    indent_cm: float = 1.25
    body_paras: int = 150
    bad_spacing_paras: int = 0
    bad_font_paras: int = 0
    with_task_page: bool = True
    with_conclusion: bool = True
    tables_captioned: int = 3
    tables_uncaptioned: int = 0
    refs: list[str] = field(default_factory=lambda: list(REFS_SORTED))
    page_numbers: bool = True
    code_paras: int = 0
    seed: int = 1


def _page_number_footer(section) -> None:
    p = section.footer.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run()
    for tag, attr in (("w:fldChar", {"w:fldCharType": "begin"}), ("w:instrText", None), ("w:fldChar", {"w:fldCharType": "end"})):
        el = OxmlElement(tag)
        if attr:
            for k, v in attr.items():
                el.set(qn(k), v)
        else:
            el.set(qn("xml:space"), "preserve")
            el.text = "PAGE"
        run._r.append(el)


def make_work(path: str | pathlib.Path, spec: Spec | None = None) -> pathlib.Path:
    spec = spec or Spec()
    rnd = random.Random(spec.seed)
    d = docx.Document()
    st = d.styles["Normal"]
    st.font.name = spec.font
    st.element.rPr.rFonts.set(qn("w:cs"), spec.font)
    st.font.size = Pt(spec.size_pt)
    st.paragraph_format.line_spacing = spec.spacing
    st.paragraph_format.first_line_indent = Cm(spec.indent_cm)
    st.paragraph_format.space_after = Pt(0)
    sec = d.sections[0]
    sec.left_margin, sec.right_margin, sec.top_margin, sec.bottom_margin = (Cm(x) for x in spec.margins_cm)
    if spec.page_numbers:
        _page_number_footer(sec)

    def center(t: str, bold: bool = True):
        p = d.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.first_line_indent = Cm(0)
        r = p.add_run(t)
        r.bold = bold
        return p

    center("Л.Н. ГУМИЛЕВ АТЫНДАҒЫ ЕУРАЗИЯ ҰЛТТЫҚ УНИВЕРСИТЕТІ")
    center("КУРСТЫҚ ЖҰМЫС")
    center("Тақырыбы: Кітапхана қорының деректер базасы", bold=False)
    d.add_paragraph("Орындаған: Синтетикалық Студент")
    d.add_paragraph("Ғылыми жетекші: Синтетикалық Оқытушы")
    d.add_page_break()
    if spec.with_task_page:
        center("ТАПСЫРМА")
        d.add_paragraph("Кітапхана қорын есепке алатын деректер базасын жобалау және Python мен SQLite арқылы іске асыру.")
        d.add_page_break()
    center("МАЗМҰНЫ")
    for t in ("КІРІСПЕ", "1 ТЕОРИЯЛЫҚ БӨЛІМ", "2 ПРАКТИКАЛЫҚ БӨЛІМ", "ҚОРЫТЫНДЫ", "ПАЙДАЛАНЫЛҒАН ДЕРЕК КӨЗДЕРІНІҢ ТІЗІМІ"):
        d.add_paragraph(f"{t}{'.' * 20}3")
    d.add_page_break()

    sections = ["КІРІСПЕ", "1 ТЕОРИЯЛЫҚ БӨЛІМ", "2 ПРАКТИКАЛЫҚ БӨЛІМ"] + (["ҚОРЫТЫНДЫ"] if spec.with_conclusion else [])
    per = max(1, spec.body_paras // len(sections))
    bad_sp, bad_font, code = spec.bad_spacing_paras, spec.bad_font_paras, spec.code_paras
    tables_c, tables_u = spec.tables_captioned, spec.tables_uncaptioned
    n = 0
    for s in sections:
        center(s)
        for i in range(per):
            n += 1
            p = d.add_paragraph(" ".join(rnd.sample(SENTENCES, 3)))
            if bad_sp:
                p.paragraph_format.line_spacing = 1.5
                bad_sp -= 1
            elif bad_font:
                for r in p.runs:
                    r.font.name = "Arial"
                bad_font -= 1
            if s.startswith("2") and i == 2 and code:
                for _ in range(code):
                    c = d.add_paragraph("cursor.execute(\"SELECT id, title, author FROM books WHERE year > 2015 ORDER BY title\")")
                    for r in c.runs:
                        r.font.name = "Courier New"
                        r.font.size = Pt(10)
                code = 0
            if s.startswith("2") and i % 6 == 3 and (tables_c or tables_u):
                if tables_c:
                    d.add_paragraph(f"Кесте-{spec.tables_captioned - tables_c + 1}")
                    tables_c -= 1
                else:
                    tables_u -= 1
                t = d.add_table(rows=3, cols=3)
                for row in t.rows:
                    for cell in row.cells:
                        cell.text = "дерек"
        if s != sections[-1]:
            d.add_page_break()
    d.add_page_break()
    center("ПАЙДАЛАНЫЛҒАН ДЕРЕК КӨЗДЕРІНІҢ ТІЗІМІ")
    for i, r in enumerate(spec.refs, 1):
        p = d.add_paragraph(f"{i}. {r}")
        p.paragraph_format.first_line_indent = Cm(0)
    path = pathlib.Path(path)
    d.save(str(path))
    return path
