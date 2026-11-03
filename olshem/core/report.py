"""Kazakh HTML report: program checks + AI review in one page.

Two separate indicators, deliberately not mixed:
* «талаптарға сәйкестік %» — computed by the program from rule statuses;
* «мазмұн (ЖИ ұсынысы)»    — suggested by the model; the final grade belongs to the teacher.
"""
from __future__ import annotations

import datetime
import html
import re

from .scoring import compliance_pct, merge_rules

STATUS = {"сәйкес": ("ok", "✓ Сәйкес"), "ішінара": ("warn", "◐ Ішінара"),
          "сәйкес емес": ("bad", "✕ Сәйкес емес"), "тексерілмеді": ("na", "? Тексерілмеді")}
ORDER = ["сәйкес емес", "ішінара", "тексерілмеді", "сәйкес"]
SEV_ORDER = {"критикалық": 0, "маңызды": 1, "ұсыныс": 2}


ASTANA = datetime.timezone(datetime.timedelta(hours=5), "Астана")


def to_local(t: datetime.datetime | None) -> datetime.datetime:
    """Stored times are UTC; reports show Astana time (UTC+5)."""
    t = t or datetime.datetime.now(datetime.timezone.utc)
    if t.tzinfo is None:
        t = t.replace(tzinfo=datetime.timezone.utc)
    return t.astimezone(ASTANA)


def e(s) -> str:
    return html.escape(str(s if s is not None else ""))


CSS = """
:root{--bg:#f5f3ef;--card:#fff;--ink:#1f2633;--mute:#5f6b7a;--line:#e3dfd7;--brand:#24507a;--accent:#2b7a70;
--ok:#2c7a4b;--okbg:#e7f2eb;--warn:#8f6410;--warnbg:#faf0dc;--bad:#a8403a;--badbg:#f7e6e3;--na:#5f6b7a;--nabg:#edeff2;--hl:#fff3c4}
:root[data-theme=dark]{--bg:#13161c;--card:#1b1f27;--ink:#e6e8ec;--mute:#9ba4b3;--line:#2b303a;
--brand:#93b7dc;--accent:#72c0b4;--ok:#86cfa1;--okbg:#1c3125;--warn:#e2bf73;--warnbg:#352b17;--bad:#ee958c;--badbg:#38201f;--na:#a3aab6;--nabg:#252a33;--hl:#4a3f12}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#13161c;--card:#1b1f27;--ink:#e6e8ec;--mute:#9ba4b3;--line:#2b303a;
--brand:#93b7dc;--accent:#72c0b4;--ok:#86cfa1;--okbg:#1c3125;--warn:#e2bf73;--warnbg:#352b17;--bad:#ee958c;--badbg:#38201f;--na:#a3aab6;--nabg:#252a33;--hl:#4a3f12}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15.5px/1.6 "Segoe UI","Noto Sans","PT Sans",system-ui,sans-serif}
.wrap{max-width:1000px;margin:0 auto;padding:24px 16px 60px}
.embed .wrap{padding:0 0 10px}
.tools{display:flex;gap:8px;justify-content:flex-end;margin-bottom:10px}
.tools button{font:inherit;font-size:13px;background:var(--card);color:var(--ink);border:1px solid var(--line);border-radius:8px;padding:5px 12px;cursor:pointer}
.banner{border-radius:10px;padding:10px 16px;margin-bottom:12px;font-size:14px;border:1px solid var(--line)}
.banner.demo{background:var(--warnbg);color:var(--warn)}.banner.part{background:var(--nabg);color:var(--ink)}
header{display:flex;gap:22px;align-items:center;flex-wrap:wrap;background:var(--card);border:1px solid var(--line);border-radius:14px;padding:22px 24px}
.ring{--p:0;width:112px;height:112px;border-radius:50%;flex:none;display:grid;place-items:center;
background:conic-gradient(var(--accent) calc(var(--p)*1%),var(--line) 0)}
.ring.ai{background:conic-gradient(var(--brand) calc(var(--p)*1%),var(--line) 0)}
.ring>div{width:88px;height:88px;border-radius:50%;background:var(--card);display:grid;place-items:center;text-align:center}
.ring b{font-size:27px;line-height:1}.ring small{display:block;color:var(--mute);font-size:11px;line-height:1.25;margin-top:3px}
h1{font-size:20px;margin:0 0 4px;line-height:1.3}h2{font-size:17px;margin:34px 0 12px;color:var(--brand)}
.meta{color:var(--mute);font-size:13px}.pills{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}
.pill{padding:3px 10px;border-radius:99px;font-size:12.5px;font-weight:600;white-space:nowrap}
.ok{color:var(--ok);background:var(--okbg)}.warn{color:var(--warn);background:var(--warnbg)}.bad{color:var(--bad);background:var(--badbg)}.na{color:var(--na);background:var(--nabg)}
.summary{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--accent);border-radius:10px;padding:14px 18px;margin-top:16px}
.notice{margin-top:12px;font-size:13.5px;color:var(--mute);background:var(--card);border:1px dashed var(--line);border-radius:10px;padding:10px 16px}
.item{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin-bottom:10px}
.row{display:flex;justify-content:space-between;gap:10px;align-items:flex-start;flex-wrap:wrap}
.item h3{font-size:15px;margin:0;flex:1 1 300px;line-height:1.4}.found{margin:6px 0 0}
.src{font-size:11px;font-weight:700;letter-spacing:.04em;text-transform:uppercase;padding:2px 7px;border-radius:5px;border:1px solid var(--line);color:var(--mute)}
.sev{font-size:12px;color:var(--mute)}
ul.det{margin:8px 0 0;padding-left:18px;color:var(--mute);font-size:13.5px}
blockquote{margin:8px 0 0;padding:6px 12px;border-left:3px solid var(--line);color:var(--mute);font-size:13.5px}
blockquote .v{font-size:11.5px;font-weight:600;margin-left:6px}.v.y{color:var(--ok)}.v.n{color:var(--bad)}
.sugg{margin-top:8px;font-size:14px}.sugg b{color:var(--accent)}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:12px}
.fb h3{margin:0 0 8px;font-size:15px}.fb p{margin:4px 0;font-size:14px}
.attn{background:var(--warnbg);border-radius:10px;padding:14px 18px}.attn li{margin:4px 0}
.ocr{white-space:pre-wrap;background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px;font-size:14px;max-height:520px;overflow:auto}
.ocr mark{background:var(--hl);color:inherit;border-radius:3px;padding:0 2px}
footer{margin-top:36px;color:var(--mute);font-size:12.5px;text-align:center}
@media print{.tools{display:none}body{background:#fff}.item,header,.summary{break-inside:avoid}}
@media (max-width:560px){header{padding:16px}.ring{width:96px;height:96px}.ring>div{width:76px;height:76px}.ring b{font-size:22px}}
"""

TOOLS = '<div class="tools"><button onclick="olshemTheme()">◐ Тақырып</button><button onclick="print()">⎙ Басып шығару / PDF</button></div>'

THEME_JS = """<script>
(function(){try{var t=localStorage.getItem('olshem-theme');if(t)document.documentElement.dataset.theme=t;}catch(e){}})();
function olshemTheme(){var r=document.documentElement,d=r.dataset.theme||(matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light');
r.dataset.theme=d==='dark'?'light':'dark';try{localStorage.setItem('olshem-theme',r.dataset.theme)}catch(e){}}
</script>"""


def _ocr_html(ocr: dict) -> str:
    pages = ocr.get("pages", [])
    if not pages:
        return ""
    conf_cls = {"жоғары": "ok", "орташа": "warn", "төмен": "bad"}
    out = ["<h2>Қолжазбадан танылған мәтін (OCR)</h2>",
           "<p class='meta'>Сары түспен — ЖИ сенімсіз оқыған жерлер. Оқытушы түпнұсқа фотомен салыстырып көруі керек.</p>"]
    for p in pages:
        txt = e(p.get("text", ""))
        txt = re.sub(r"\[\?(.*?)\?\]", lambda m: f"<mark>{m.group(1) or '?'}</mark>", txt)
        txt = txt.replace("[?]", "<mark>?</mark>")
        c = p.get("confidence", "орташа")
        out.append(f"<div class='row' style='margin:10px 0 6px'><b>{e(p.get('page'))}-бет</b>"
                   f"<span class='pill {conf_cls.get(c, 'na')}'>сенімділік: {e(c)}</span></div>"
                   f"<div class='ocr'>{txt}</div>")
    return "".join(out)


def render(title: str, course: str, fmt_results: list[dict], review: dict | None, meta: dict,
           model: str | None, checklist: dict, *, demo: bool = False, ai_error: str | None = None,
           ocr: dict | None = None, checked_at: datetime.datetime | None = None,
           standalone: bool = True, embed: bool = False) -> str:
    review = review or {}
    rules = merge_rules(fmt_results, review, checklist)
    counts = {k: sum(1 for r in rules if r["status"] == k) for k in STATUS}
    rules.sort(key=lambda r: (r.get("optional", False), ORDER.index(r["status"]), SEV_ORDER.get(r.get("severity"), 1)))
    compliance = compliance_pct(rules)
    score = review.get("suggested_score")
    cit = review.get("citations") or {}

    def rule_html(r: dict) -> str:
        cls, lab = STATUS[r["status"]]
        det = "".join(f"<li>{e(d)}</li>" for d in r.get("details", []))
        ev = ""
        for x in r.get("evidence", []):
            v = x.get("verified")
            badge = "" if v is None else (f"<span class='v y'>✓ жұмыста бар</span>" if v
                                          else "<span class='v n'>✕ жұмыстан табылмады</span>")
            ev += f"<blockquote>«{e(x.get('quote'))}» — <i>{e(x.get('location'))}</i>{badge}</blockquote>"
        sg = (f"<div class='sugg'><b>Ұсыныс:</b> {e(r['suggestion'])}</div>"
              if r.get("suggestion") and r["status"] != "сәйкес" else "")
        opt = " · <i>міндетті емес</i>" if r.get("optional") else ""
        return (f"<div class='item'><div class='row'><h3>{e(r.get('text_kk') or r['id'])}</h3>"
                f"<span class='src'>{e(r['src'])}</span><span class='pill {cls}'>{lab}</span></div>"
                f"<div class='sev'>{e(r.get('severity', ''))} · {e(r.get('category', ''))}{opt}</div>"
                f"<p class='found'>{e(r.get('found'))}</p>{'<ul class=det>' + det + '</ul>' if det else ''}{ev}{sg}</div>")

    fb = "".join(
        f"<div class='item fb'><h3>{e(f['section'])}</h3><p><b style='color:var(--ok)'>＋</b> {e(f['strength'])}</p>"
        f"<p><b style='color:var(--bad)'>－</b> {e(f['issue'])}</p><p class='sugg'><b>Ұсыныс:</b> {e(f['suggestion'])}</p></div>"
        for f in review.get("content_feedback", []))
    attn = "".join(f"<li>{e(a)}</li>" for a in review.get("teacher_attention", []))
    pills = "".join(f"<span class='pill {STATUS[k][0]}'>{STATUS[k][1]}: {v}</span>" for k, v in counts.items() if v)
    when = to_local(checked_at).strftime("%d.%m.%Y %H:%M")
    facts = [f"{meta['pages']} бет" if meta.get("pages") else None,
             f"{meta['tables']} кесте" if meta.get("tables") is not None else None,
             f"{meta['images']} сурет" if meta.get("images") is not None else None,
             f"тексерілді {when}"]
    banners = ""
    if demo:
        banners += ("<div class='banner demo'><b>Демо режимі.</b> Бұл есеп алдын ала сақталған нәтижеден көрсетілді "
                    "(ЖИ сервисі қорғау кезінде қолжетімсіз болған жағдайға арналған).</div>")
    if ai_error:
        banners += (f"<div class='banner part'><b>ЖИ кезеңі орындалмады:</b> {e(ai_error)}<br>"
                    "Рәсімдеу талаптары бағдарламамен толық тексерілді; мазмұнды кейінірек қайта тексеруге болады.</div>")
    ring_ai = (f"<div class='ring ai' style='--p:{score}'><div><span><b>{score}</b><small>мазмұн<br>(ЖИ ұсынысы)</small></span></div></div>"
               if score is not None else
               "<div class='ring ai' style='--p:0'><div><span><b>—</b><small>мазмұн<br>бағаланбады</small></span></div></div>")
    ring_c = (f"<div class='ring' style='--p:{compliance}'><div><span><b>{compliance}%</b><small>талаптарға<br>сәйкестік</small></span></div></div>"
              if compliance is not None else "")
    cit_line = (f" Дәйексөздер жұмыс мәтінімен салыстырылды: {cit['verified']}/{cit['total']} табылды"
                + (f", {cit['downgraded']} тұжырым расталмағандықтан есептен шығарылды." if cit.get("downgraded") else ".")
                if cit.get("total") else "")
    summary = ""
    if review.get("summary_kk"):
        summary = (f"<div class='summary'><b>Қысқаша қорытынды.</b> {e(review.get('summary_kk'))}"
                   f"<div class='meta' style='margin-top:6px'>{e(review.get('score_reasoning'))}</div></div>")
    body = f"""<div class="wrap">
{'' if embed else TOOLS}
{banners}
<header>{ring_c}{ring_ai}
<div style="flex:1 1 380px"><div class="meta">{e(course)}</div><h1>{e(title)}</h1>
<div class="meta">{' · '.join(x for x in facts if x)}</div>
<div class="pills">{pills}</div></div></header>
{summary}
<div class="notice">ⓘ Бұл — <b>алдын ала</b> тексеру. Пайыз бағдарламамен есептелді; мазмұн бағасы — ЖИ-дің ұсынысы ғана.
Соңғы баға мен шешім — оқытушыда.{e(cit_line)}</div>
<h2>Талаптар бойынша тексеру ({len(rules)})</h2>{''.join(rule_html(r) for r in rules)}
{'<h2>Мазмұн бойынша пікір</h2><div class="grid">' + fb + '</div>' if fb else ''}
{'<h2>Оқытушының назарына</h2><div class="attn"><ul>' + attn + '</ul></div>' if attn else ''}
{_ocr_html(ocr) if ocr else ''}
<footer>«Бағдарлама» — рәсімдеу талаптары файлдан дәл өлшенді (LLM қатыспайды).
«ЖИ» — мазмұнды {e(model or '—')} моделі бағалады, әр тұжырым жұмыстағы дәйексөзбен тексерілді.<br>
Өлшем · «Әр жұмысқа — бір өлшем.»</footer></div>"""
    if not standalone:
        return body
    body_cls = "embed" if embed else ""
    return (f'<!doctype html><html lang="kk"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>Тексеру есебі — {e(title)}</title><style>{CSS}</style>{THEME_JS}</head><body class="{body_cls}">{body}</body></html>')
