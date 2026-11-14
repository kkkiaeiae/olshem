"""v1.1: OpenAI-compatible provider, PDF -> text, AI settings API (masking, admin token, draft test),
syllabus-only assignments, resubmission comparison, rate limiting."""
import json
import types as pytypes

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel

from olshem.config import ROOT, settings
from olshem.core import llm
from olshem.models.db import session_scope
from olshem.models.entities import Assignment, Course, Submission
from olshem.services import ai_settings, jobs, ratelimit
from olshem.services.serializers import label_key

T = {"X-Role": "teacher"}
ADMIN = "test-admin-token"
TA = {**T, "X-Admin-Token": ADMIN}
PDF = ROOT / "demo" / "talaptar.pdf"


@pytest.fixture(scope="module")
def client():
    from olshem.main import app
    with TestClient(app) as c:
        yield c


class S(BaseModel):
    x: int


# ---------------------------------------------------------------- OpenAI-compatible provider
def test_openai_provider_fallback_and_content(monkeypatch):
    sent = []

    def post(url, json, headers, timeout):  # noqa: A002
        sent.append((url, json, headers))
        if json["model"] == "busy":
            return pytypes.SimpleNamespace(status_code=429, text="rate limited", json=lambda: {})
        body = {"choices": [{"message": {"content": '```json\n{"x": 5}\n```'}}]}
        return pytypes.SimpleNamespace(status_code=200, text="", json=lambda: body)

    import httpx
    monkeypatch.setattr(httpx, "post", post)
    llm.configure(llm.AIConfig(provider="openai", api_key="sk-test-1234", base_url="https://api.deepseek.com/v1",
                               models={"extract": ["busy", "good"], "ocr": ["good"], "judge": ["good"]}, source="db"))
    img = llm.bytes_part(b"\x89PNG....", "image/png")
    obj, model = llm.call_json("extract", ["hello", img, llm.file_part(PDF)], S, "SYS")
    assert obj.x == 5 and model == "good"
    assert [b["model"] for _, b, _ in sent] == ["busy", "good"]      # 429 -> next model, no retry
    url, body, headers = sent[-1]
    assert url == "https://api.deepseek.com/v1/chat/completions"
    assert headers["Authorization"] == "Bearer sk-test-1234"
    assert body["response_format"] == {"type": "json_object"}
    assert "JSON Schema" in body["messages"][0]["content"]
    parts = body["messages"][1]["content"]
    assert parts[1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert parts[2]["type"] == "text" and parts[2]["text"].startswith("[PDF talaptar.pdf]")


def test_openai_local_endpoint_needs_no_key():
    cfg = llm.AIConfig(provider="openai", base_url="http://localhost:11434/v1", models={}, source="db")
    assert cfg.configured
    assert not llm.AIConfig(provider="openai", base_url="https://api.openai.com/v1").configured


def test_pdf_text_extracts_text_layer():
    t = llm.pdf_text(PDF.read_bytes())
    assert "[1-бет]" in t and len(t) > 500
    assert len(llm.pdf_text(PDF.read_bytes(), limit=300)) <= 300


# ---------------------------------------------------------------- settings API
@pytest.fixture
def admin(monkeypatch):
    monkeypatch.setattr(settings, "admin_token", ADMIN)


def test_settings_locked_without_admin_token(client, monkeypatch):
    """Fail closed: with no ADMIN_TOKEN on the server nobody may change the provider / endpoint."""
    monkeypatch.setattr(settings, "admin_token", None)
    body = {"provider": "openai", "api_key": "sk-evil-00000000", "base_url": "https://evil.example/v1"}
    assert client.put("/api/settings/ai", headers=T, json=body).status_code == 403
    assert client.post("/api/settings/ai/test", headers=T, json=body).status_code == 403
    assert client.delete("/api/settings/ai", headers=T).status_code == 403
    d = client.get("/api/settings/ai", headers=T).json()
    assert d["editable"] is False and llm.current().source == "env"


def test_settings_mask_and_provider_switch(client, admin):
    r = client.get("/api/settings/ai", headers={"X-Role": "student"})
    assert r.status_code == 403
    r = client.put("/api/settings/ai", headers=TA, json={"provider": "openai", "api_key": "sk-secret-ABCD1234",
                                                        "base_url": "https://api.openai.com/v1"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["key_hint"] == "…1234" and d["source"] == "db" and "sk-secret" not in r.text
    assert d["models"]["judge"] == ["gpt-4o", "gpt-4o-mini"]                     # preset defaults
    assert llm.current().api_key == "sk-secret-ABCD1234"
    # same provider + endpoint, empty key -> keeps the key; models can be changed
    r = client.put("/api/settings/ai", headers=TA, json={"provider": "openai", "base_url": "https://api.openai.com/v1",
                                                        "models": {"extract": ["gpt-4o-mini"], "ocr": [], "judge": ["gpt-4o"]}})
    assert r.status_code == 200 and r.json()["key_hint"] == "…1234" and r.json()["models"]["judge"] == ["gpt-4o"]
    # switching provider without a new key must not carry the old key over
    r = client.put("/api/settings/ai", headers=TA, json={"provider": "gemini"})
    assert r.status_code == 422
    # stored in the DB and re-applied on start-up
    with session_scope() as s:
        llm.configure(None)
        ai_settings.apply_stored(s)
    assert llm.current().provider == "openai" and llm.current().models["judge"] == ["gpt-4o"]
    r = client.delete("/api/settings/ai", headers=TA)
    assert r.status_code == 200 and r.json()["source"] == "env" and r.json()["provider"] == "gemini"


def test_settings_validation(client, admin):
    bad = client.put("/api/settings/ai", headers=TA, json={"provider": "openai", "api_key": "k" * 20,
                                                          "base_url": "ftp://x"})
    assert bad.status_code == 422
    bad = client.put("/api/settings/ai", headers=TA, json={"provider": "gemini", "api_key": "k" * 20,
                                                          "models": {"extract": ["bad model name!"]}})
    assert bad.status_code == 422


def test_admin_token_required(client, monkeypatch):
    monkeypatch.setattr(settings, "admin_token", "s3cret-token")
    body = {"provider": "gemini", "api_key": "AIza-test-key-9999"}
    assert client.put("/api/settings/ai", headers=T, json=body).status_code == 403
    assert client.put("/api/settings/ai", headers={**T, "X-Admin-Token": "wrong"}, json=body).status_code == 403
    r = client.put("/api/settings/ai", headers={**T, "X-Admin-Token": "s3cret-token"}, json=body)
    assert r.status_code == 200 and r.json()["admin_token_required"] is True
    assert client.get("/api/settings/ai", headers=T).status_code == 200            # reading needs no token
    client.delete("/api/settings/ai", headers={**T, "X-Admin-Token": "s3cret-token"})


def test_draft_test_does_not_save(client, admin, monkeypatch):
    seen = {}

    def fake_probe(cfg, models):
        seen["cfg"] = cfg
        return {m: ({"status": "ok", "latency_s": 0.1} if m != "m-bad" else {"status": "quota", "code": 429})
                for m in models}
    monkeypatch.setattr(llm, "probe_with", fake_probe)
    r = client.post("/api/settings/ai/test", headers=TA, json={
        "provider": "openai", "api_key": "sk-draft-0000", "base_url": "https://openrouter.ai/api/v1",
        "models": {"extract": ["m-bad", "m-ok"], "ocr": ["m-ok"], "judge": ["m-bad"]}})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["ok"] is False                                   # judge has no working model
    assert {x["model"]: x["stages"] for x in d["results"]}["m-bad"] == ["extract", "judge"]
    assert seen["cfg"].api_key == "sk-draft-0000"
    assert llm.current().source == "env"                      # nothing saved


# ---------------------------------------------------------------- syllabus-only assignment
def test_assignment_from_syllabus_only(client, monkeypatch, checklist):
    got = {}

    def fake_extract(files, text, **k):
        got.update(files=files, text=text, **k)
        from olshem.core.requirements import Checklist
        return Checklist.model_validate(checklist), "mock"
    monkeypatch.setattr(jobs, "extract_checklist", fake_extract)
    r = client.post("/api/assignments", headers=T, data={"title": "БӨЖ-1", "type": "БӨЖ", "course_name": "Тест пәні"})
    assert r.status_code == 422 and "силлабус" in r.json()["detail"]
    with open(ROOT / "demo" / "syllabus.pdf", "rb") as f:
        r = client.post("/api/assignments", headers=T, data={"title": "БӨЖ-1", "type": "БӨЖ", "course_name": "Тест пәні"},
                        files={"syllabus_file": ("syllabus.pdf", f, "application/pdf")})
    assert r.status_code == 201, r.text
    import time
    for _ in range(50):
        a = client.get(f"/api/assignments/{r.json()['id']}").json()
        if a["checklist_status"] != "extracting":
            break
        time.sleep(0.1)
    assert a["checklist_status"] == "ready" and a["has_syllabus"]
    assert got["files"] == [] and got["syllabus"] is not None and got["syllabus"].suffix == ".pdf"


# ---------------------------------------------------------------- resubmission comparison
def _done(aid, label, statuses, minutes):
    import datetime as dt
    fmt = [{"id": rid, "text_kk": f"талап {rid}", "status": st, "found": "", "details": []} for rid, st in statuses.items()]
    from olshem.core.scoring import compliance_pct
    sub = Submission(assignment_id=aid, student_label=label, kind="docx", status="done", format_result_json=fmt,
                     review_json=None, compliance_pct=compliance_pct(fmt),
                     created_at=dt.datetime(2026, 11, 10, 10, minutes, tzinfo=dt.timezone.utc))
    return sub


def test_label_key_handles_kazakh_case_and_spaces():
    assert label_key("  ӘЛИХАН   Елюбаев ") == label_key("әлихан елюбаев")
    assert label_key("") == ""


def test_compare_previous(client):
    with session_scope() as s:
        c = Course(name="Салыстыру"); s.add(c); s.commit(); s.refresh(c)
        a = Assignment(course_id=c.id, title="t", checklist_json={"rules": []}, checklist_status="ready",
                       checklist_confirmed=True)
        s.add(a); s.commit(); s.refresh(a)
        v1 = _done(a.id, "Әлихан Е.", {"r1": "сәйкес емес", "r2": "ішінара", "r3": "сәйкес"}, 1)
        other = _done(a.id, "Басқа студент", {"r1": "сәйкес", "r2": "сәйкес", "r3": "сәйкес"}, 2)
        v2 = _done(a.id, "  әлихан   е. ", {"r1": "сәйкес", "r2": "ішінара", "r3": "сәйкес емес"}, 3)
        anon = _done(a.id, "", {"r1": "сәйкес"}, 4)
        for x in (v1, other, v2, anon):
            s.add(x)
        s.commit()
        ids = v1.id, v2.id, anon.id
    d = client.get(f"/api/submissions/{ids[1]}").json()
    p = d["previous"]
    assert p["id"] == ids[0] and p["fixed"] == 1 and p["new_problems"] == 1 and p["fixed_rules"] == ["талап r1"]
    assert client.get(f"/api/submissions/{ids[0]}").json()["previous"] is None    # first version
    assert client.get(f"/api/submissions/{ids[2]}").json()["previous"] is None    # no label -> no matching
    html = client.get(f"/api/submissions/{ids[1]}/report").text
    assert "Алдыңғы нұсқамен салыстыру" in html and "талап r1" in html


# ---------------------------------------------------------------- rate limiting
def test_rate_limit_window():
    for _ in range(3):
        ratelimit.hit("submit", "1.2.3.4", limit=3, window=60)
    with pytest.raises(HTTPException) as e:
        ratelimit.hit("submit", "1.2.3.4", limit=3, window=60)
    assert e.value.status_code == 429 and "Retry-After" in e.value.headers
    ratelimit.hit("submit", "5.6.7.8", limit=3, window=60)        # other IP is independent
    ratelimit.hit("assign", "1.2.3.4", limit=3, window=60)        # other action is independent


def test_client_ip_uses_trusted_proxy_hop(monkeypatch):
    req = pytypes.SimpleNamespace(headers={"x-forwarded-for": "6.6.6.6, 10.0.0.1, 203.0.113.9"},
                                  client=pytypes.SimpleNamespace(host="10.1.1.1"))
    monkeypatch.setattr(settings, "trust_proxy_hops", 1)
    assert ratelimit.client_ip(req) == "203.0.113.9"              # client-forged first entry ignored
    monkeypatch.setattr(settings, "trust_proxy_hops", 0)
    assert ratelimit.client_ip(req) == "10.1.1.1"


def test_submit_endpoint_is_rate_limited(client, monkeypatch):
    monkeypatch.setitem(settings.rate_limits, "assign", 2)
    codes = [client.post("/api/assignments", headers=T, data={"title": "x", "course_name": "y"}).status_code
             for _ in range(3)]
    assert codes == [422, 422, 429]                               # limit applies before validation
