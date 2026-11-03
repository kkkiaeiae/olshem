"""Privacy, citation verification and the LLM fallback logic (no network)."""
import types as pytypes

import pytest

from olshem.core import llm
from olshem.core.privacy import MASK, redact_lines
from olshem.core.review import quote_in_text, verify_citations, _canon


def test_redaction_title_page():
    lines = ["Орындаған:", "Иванов Иван", "Ғылыми жетекші: Сауханова М.С.", "Студенттер базасы құрылды.",
             "Байланыс: test@enu.kz, +7 701 123 45 67", "Оқытушы деректерді енгізеді."]
    out = redact_lines(lines)
    joined = "\n".join(out)
    assert "Иванов" not in joined and "Сауханова" not in joined
    assert "test@enu.kz" not in joined and "701" not in joined
    assert "Студенттер базасы құрылды." in out          # normal sentence kept
    assert "Оқытушы деректерді енгізеді." in out         # weak label without colon kept
    assert out[0] == f"Орындаған: {MASK}"


def test_redaction_student_label():
    assert MASK in redact_lines(["Жұмысты Айгерім Тұрсын орындады"], ["Айгерім Тұрсын"])[0]


def test_quote_verification():
    text = _canon("Осы курстық жұмыста қалалық емхана пациенттерінің картотекасын автоматтандырылған түрде жүргізуге арналған деректер базасын құру қарастырылады.")
    assert quote_in_text("курстық жұмыста қалалық емхана пациенттерінің картотекасын", text)
    assert quote_in_text("«Курстық жұмыста қалалық  емхана пациенттерінің картотекасын!»", text)  # punctuation/case/space
    assert not quote_in_text("жұмыста MySQL серверінде деректер қоймасы құрылды", text)


def test_unverified_verdict_is_downgraded():
    review = {"ai_rules": [
        {"id": "a", "status": "сәйкес", "found": "ok", "evidence": [{"quote": "деректер базасын құру қарастырылады", "location": "К"}], "suggestion": ""},
        {"id": "b", "status": "сәйкес емес", "found": "ойдан", "evidence": [{"quote": "бұл сөйлем жұмыста мүлдем жоқ болатын мәтін", "location": "?"}], "suggestion": ""},
        {"id": "c", "status": "ішінара", "found": "дәлелсіз", "evidence": [], "suggestion": ""}]}
    out = verify_citations(review, "Кіріспе. Деректер базасын құру қарастырылады.")
    st = {r["id"]: r["status"] for r in out["ai_rules"]}
    assert st == {"a": "сәйкес", "b": "тексерілмеді", "c": "тексерілмеді"}
    assert out["citations"] == {"total": 2, "verified": 1, "downgraded": 2}


class _Err(Exception):
    def __init__(self, code):
        super().__init__(f"{code} error")
        self.code = code


def test_fallback_chain(monkeypatch):
    """429 -> next model immediately; 503 -> retry, then next; a valid answer is returned with its model."""
    from pydantic import BaseModel

    class S(BaseModel):
        x: int

    calls = []

    def gen(model, contents, config):
        calls.append(model)
        if model == "m-pro":
            raise _Err(429)
        if model == "m-busy":
            raise _Err(503)
        return pytypes.SimpleNamespace(text='{"x": 7}')

    fake = pytypes.SimpleNamespace(models=pytypes.SimpleNamespace(generate_content=gen))
    monkeypatch.setattr(llm, "client", lambda: fake)
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    monkeypatch.setitem(llm.settings.models, "judge", ["m-pro", "m-busy", "m-ok"])
    obj, model = llm.call_json("judge", ["hi"], S)
    assert obj.x == 7 and model == "m-ok"
    assert calls == ["m-pro", "m-busy", "m-busy", "m-ok"]


def test_all_models_fail(monkeypatch):
    from pydantic import BaseModel

    class S(BaseModel):
        x: int

    def gen(model, contents, config):
        raise _Err(404)
    monkeypatch.setattr(llm, "client", lambda: pytypes.SimpleNamespace(models=pytypes.SimpleNamespace(generate_content=gen)))
    monkeypatch.setitem(llm.settings.models, "ocr", ["a", "b"])
    with pytest.raises(llm.LLMUnavailable):
        llm.call_json("ocr", ["x"], S)


def test_no_key_is_readable():
    with pytest.raises(llm.LLMUnavailable, match="GEMINI_API_KEY"):
        llm.client()
