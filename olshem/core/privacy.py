"""Anonymisation applied to every text before it is sent to an LLM."""
from __future__ import annotations

import re

MASK = "[ЖАСЫРЫЛДЫ]"
# strong labels practically never start a normal sentence -> colon optional;
# weak labels («Студент», «Оқытушы») do -> only with a colon.
_STRONG = r"Орындаған|Орындады|Ғылыми жетекші|Тексерген|Қабылдаған|Выполнил[а]?|Проверил[а]?"
_WEAK = r"Орындаушы|Студент|Жетекші|Тексерді|Қабылдады|Оқытушы|Руководитель"
_LABEL_RE = re.compile(rf"^\s*(?:##\s*)?(?:({_STRONG})\b\s*[:：]?|({_WEAK})\s*[:：])", re.I)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_PHONE = re.compile(r"(?:\+7|8)[\s\-()]*\d{3}[\s\-()]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}")
_IIN = re.compile(r"\b\d{12}\b")


def redact_line(t: str) -> tuple[str, bool]:
    """Returns (line, was_label). A label line («Орындаған: Аты Жөні») keeps the label only."""
    m = _LABEL_RE.match(t)
    if m:
        return (m.group(1) or m.group(2)) + ": " + MASK, True
    return t, False


def redact_inline(t: str, extra_names: list[str] | None = None) -> str:
    t = _EMAIL.sub(MASK, t)
    t = _PHONE.sub(MASK, t)
    t = _IIN.sub(MASK, t)
    for name in extra_names or []:
        name = name.strip()
        if len(name) >= 3:
            t = re.sub(re.escape(name), MASK, t, flags=re.I)
    return t


def redact_lines(lines: list[str], extra_names: list[str] | None = None) -> list[str]:
    out: list[str] = []
    after_label = False
    for t in lines:
        s = t.strip()
        if not s:
            continue
        new, is_label = redact_line(s)
        if is_label:
            out.append(new)
            # the name is on the next line only when nothing follows the label itself
            after_label = len(_LABEL_RE.sub("", s).strip(" :：")) < 2
            continue
        # the name is often on the next short line («Орындаған:» / «Иванов И.»)
        if after_label and len(s) < 40 and not s.isupper() and not re.search(r"\d{4}", s):
            after_label = False
            continue
        after_label = False
        out.append(redact_inline(s, extra_names))
    return out
