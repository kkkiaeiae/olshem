"""Unit tests for stage ② — documents are generated on the fly with python-docx."""
import docx
import pytest
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt

from olshem.core import format_checker as fc
from olshem.services.synthetic import REFS_SORTED, Spec, make_work

needs_lo = pytest.mark.skipif(not fc.soffice_available(), reason="LibreOffice not installed")


def run(path, cl):
    res, meta = fc.run_checks(path, cl)
    return {r["id"]: r for r in res}, meta


def by_metric(cl, metric):
    return next(r for r in cl["rules"] if r["metric"] == metric)["id"]


@pytest.fixture(scope="module")
def good(tmp_path_factory):
    return make_work(tmp_path_factory.mktemp("w") / "good.docx", Spec(body_paras=60))


@pytest.fixture(scope="module")
def bad(tmp_path_factory):
    return make_work(tmp_path_factory.mktemp("w") / "bad.docx",
                     Spec(margins_cm=(2.5, 1.5, 2, 2), spacing=1.15, body_paras=40, with_task_page=False,
                          with_conclusion=False, tables_captioned=1, tables_uncaptioned=2,
                          refs=REFS_SORTED[1:] + REFS_SORTED[:1], bad_font_paras=12, code_paras=3))


def test_margins(good, bad, checklist):
    g, _ = run(good, checklist)
    b, _ = run(bad, checklist)
    left, right = by_metric(checklist, "margin_left_cm"), by_metric(checklist, "margin_right_cm")
    assert g[left]["status"] == g[right]["status"] == "сәйкес"
    assert b[left]["status"] == "сәйкес емес" and "2.50" in b[left]["found"]
    assert b[right]["status"] == "сәйкес емес" and "1.50" in b[right]["found"]


def test_font_spacing_indent(good, bad, checklist):
    g, _ = run(good, checklist)
    b, _ = run(bad, checklist)
    for m in ("font_name", "font_size_pt", "line_spacing", "first_line_indent_cm"):
        assert g[by_metric(checklist, m)]["status"] == "сәйкес", m
    assert b[by_metric(checklist, "line_spacing")]["status"] == "сәйкес емес"
    assert b[by_metric(checklist, "font_name")]["status"] in ("ішінара", "сәйкес емес")
    assert any("Arial" in d for d in b[by_metric(checklist, "font_name")]["details"])


def test_monospace_code_is_not_counted(bad, checklist):
    b, meta = run(bad, checklist)
    assert meta["code_paragraphs"] == 3
    assert all("Courier" not in d for d in b[by_metric(checklist, "font_name")]["details"][:-1])
    assert b[by_metric(checklist, "font_size_pt")]["status"] == "сәйкес"


def test_required_sections(good, bad, checklist):
    g, _ = run(good, checklist)
    b, _ = run(bad, checklist)
    rid = by_metric(checklist, "required_sections")
    assert "ТАПСЫРМА" not in " ".join(g[rid]["details"])
    det = " ".join(b[rid]["details"])
    assert "ТАПСЫРМА" in det and "ҚОРЫТЫНДЫ" in det


def test_toc_line_and_sentence_are_not_headings(tmp_path, rule):
    """Regression: a TOC line with dot leaders and «Қорытындылай келе…» must not count as ҚОРЫТЫНДЫ."""
    d = docx.Document()
    for t in ["МАЗМҰНЫ", "КІРІСПЕ........3", "ҚОРЫТЫНДЫ........20", "КІРІСПЕ", "Мәтін " * 30,
              "Қорытындылай келе, жұмыс аяқталды.", "ПАЙДАЛАНЫЛҒАН ДЕРЕК КӨЗДЕРІНІҢ ТІЗІМІ"]:
        d.add_paragraph(t)
    p = tmp_path / "toc.docx"
    d.save(p)
    res, _ = fc.run_checks(p, rule("required_sections", items=["КІРІСПЕ", "ҚОРЫТЫНДЫ"]))
    assert res[0]["status"] == "сәйкес емес"
    assert "Жоқ: ҚОРЫТЫНДЫ" in res[0]["details"]


def test_indent_from_doc_defaults(tmp_path, rule):
    """Regression: first-line indent defined only in w:docDefaults."""
    d = docx.Document()
    ppr = d.styles.element.find(qn("w:docDefaults")).find(qn("w:pPrDefault")).find(qn("w:pPr"))
    ind = OxmlElement("w:ind")
    ind.set(qn("w:firstLine"), "709")  # 1.25 cm
    ppr.append(ind)
    d.add_paragraph("КІРІСПЕ")
    for _ in range(5):
        d.add_paragraph("Деректер базасы туралы ұзын абзац мәтіні, ол сексен таңбадан асады және негізгі мәтінге жатады.")
    p = tmp_path / "ind.docx"
    d.save(p)
    res, _ = fc.run_checks(p, rule("first_line_indent_cm", min=1.25, max=1.25))
    assert res[0]["status"] == "сәйкес", res[0]["found"]


def test_table_captions_and_result_tables(tmp_path, rule):
    d = docx.Document()
    d.add_paragraph("Кесте-1")
    d.add_table(rows=1, cols=1)
    d.add_paragraph("Нәтиже:")
    d.add_table(rows=1, cols=1)
    d.add_paragraph("Студенттер тізімі")
    d.add_table(rows=1, cols=1)
    p = tmp_path / "t.docx"
    d.save(p)
    plain, _ = fc.run_checks(p, rule("table_caption", value="Кесте-1"))
    assert "3 кестенің 1-і" in plain[0]["found"]
    skip, _ = fc.run_checks(p, rule("table_caption", value="Кесте-1", skip_result_tables=True))
    assert "2 кестенің 1-і" in skip[0]["found"] and skip[0]["status"] == "ішінара"


def test_references_government_first(rule):
    r = rule("references_order", text_kk="Алдымен үкімет құжаттары, кейін алфавит бойынша")["rules"][0]
    ok = fc.check_references(r, REFS_SORTED)
    assert ok["status"] == "сәйкес", ok["details"]
    moved = REFS_SORTED[1:3] + REFS_SORTED[:1] + REFS_SORTED[3:]
    bad = fc.check_references(r, moved)
    assert bad["status"] == "сәйкес емес"
    assert any("Нормативтік" in d for d in bad["details"])


def test_disabled_rules_are_skipped(good, checklist):
    cl = {"rules": [dict(r, enabled=False) if r["metric"] == "margin_left_cm" else r for r in checklist["rules"]]}
    g, _ = run(good, cl)
    assert by_metric(checklist, "margin_left_cm") not in g


@needs_lo
def test_page_count_and_numbers(good, checklist, tmp_path):
    g, meta = run(good, checklist)
    assert meta["pages"] and meta["pages"] > 5
    assert g[by_metric(checklist, "page_number_position")]["status"] == "сәйкес"
    nonum = make_work(tmp_path / "nonum.docx", Spec(body_paras=20, page_numbers=False))
    n, _ = run(nonum, checklist)
    assert n[by_metric(checklist, "page_number_position")]["status"] == "сәйкес емес"


@needs_lo
def test_pdf_input(good, checklist):
    pdf = fc.render_pdf(good)
    res, meta, lines = fc.run_checks_pdf(pdf, checklist)
    r = {x["id"]: x for x in res}
    assert meta["pages"] > 5
    assert r[by_metric(checklist, "margin_left_cm")]["status"] == "сәйкес"
    assert r[by_metric(checklist, "references_order")]["status"] == "сәйкес"
    assert r[by_metric(checklist, "line_spacing")]["status"] == "тексерілмеді"


def test_text_checks_for_handwriting(checklist):
    lines = ["КІРІСПЕ", "мәтін", "ҚОРЫТЫНДЫ", "ПАЙДАЛАНЫЛҒАН ДЕРЕК КӨЗДЕРІНІҢ ТІЗІМІ", "1. Ә автор", "2. Б автор"]
    res = {r["id"]: r for r in fc.run_checks_text(lines, checklist)}
    assert res[by_metric(checklist, "margin_left_cm")]["status"] == "тексерілмеді"
    assert res[by_metric(checklist, "references_order")]["status"] == "сәйкес"  # Ә comes before Б in the Kazakh alphabet
    assert res[by_metric(checklist, "required_sections")]["status"] == "сәйкес емес"  # no ТАПСЫРМА etc.


def test_kz_alphabet_order(rule):
    r = rule("references_order")["rules"][0]
    assert fc.check_references(r, ["Абай", "Әуезов", "Бөкейхан", "Smith"])["status"] == "сәйкес"
    assert fc.check_references(r, ["Бөкейхан", "Абай"])["status"] == "сәйкес емес"


@pytest.mark.parametrize("margin", [Cm(3), Cm(2)])
def test_margin_tolerance(tmp_path, rule, margin):
    d = docx.Document()
    d.sections[0].left_margin = margin
    d.add_paragraph("x").runs[0].font.size = Pt(14)
    p = tmp_path / "m.docx"
    d.save(p)
    res, _ = fc.run_checks(p, rule("margin_left_cm", min=3, max=3))
    assert res[0]["status"] == ("сәйкес" if margin == Cm(3) else "сәйкес емес")
