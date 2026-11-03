"""End-to-end smoke test through the HTTP API with the LLM stages mocked."""
import time

import pytest
from fastapi.testclient import TestClient

from olshem.core import pipeline, requirements
from olshem.core.requirements import Checklist
from olshem.core.review import Review
from olshem.services import jobs
from olshem.services.synthetic import Spec, make_work

T = {"X-Role": "teacher"}


@pytest.fixture(scope="module")
def client():
    from olshem.main import app
    with TestClient(app) as c:
        yield c


def wait(client, url, done, timeout=120):
    t0 = time.time()
    while time.time() - t0 < timeout:
        d = client.get(url, headers=T).json()
        if done(d):
            return d
        time.sleep(0.5)
    raise AssertionError(f"timeout: {d}")


def test_full_flow(client, checklist, monkeypatch, tmp_path):
    monkeypatch.setattr(jobs, "extract_checklist",
                        lambda files, text: (Checklist.model_validate(checklist), "mock-extract"))
    quote = "Деректер базасы ұйымның ақпаратын бір жерде сақтап"

    def fake_review(text, images, cl, fmt, *a, **k):
        assert "Синтетикалық Студент" not in text  # anonymised before the LLM
        ai = [r for r in cl["rules"] if r["check"] == "ai" and r.get("enabled", True)]
        return Review(summary_kk="Жақсы", content_feedback=[], suggested_score=80, score_reasoning="-",
                      teacher_attention=[], ai_rules=[{"id": r["id"], "status": "сәйкес", "found": "бар",
                                                       "evidence": [{"quote": quote, "location": "КІРІСПЕ"}],
                                                       "suggestion": ""} for r in ai]), "mock-judge"
    monkeypatch.setattr(pipeline, "review_work", fake_review)

    # health + docs
    assert client.get("/api/health").status_code == 200
    assert "/api/assignments/{aid}/checklist" in client.get("/openapi.json").json()["paths"]

    # students cannot create assignments
    r = client.post("/api/assignments", data={"title": "x", "course_name": "y", "requirement_text": "z"})
    assert r.status_code == 403

    r = client.post("/api/assignments", headers=T, data={"title": "Курстық жұмыс", "type": "курстық",
                    "course_name": "ДБ", "requirement_text": "Times New Roman 14"})
    assert r.status_code == 201, r.text
    aid = r.json()["id"]
    a = wait(client, f"/api/assignments/{aid}", lambda d: d["checklist_status"] != "extracting")
    assert a["checklist_status"] == "ready" and not a["checklist_confirmed"]

    work = make_work(tmp_path / "w.docx", Spec(body_paras=40))
    # cannot submit before the teacher confirms
    with open(work, "rb") as f:
        assert client.post(f"/api/assignments/{aid}/submissions", files={"files": ("w.docx", f)}).status_code == 409

    cl = a["checklist"]
    cl["rules"][0]["optional"] = True
    r = client.put(f"/api/assignments/{aid}/checklist", headers=T, json={"checklist": cl, "confirm": True})
    assert r.status_code == 200 and r.json()["checklist_confirmed"]

    # bad uploads
    assert client.post(f"/api/assignments/{aid}/submissions", files={"files": ("x.exe", b"MZ")}).status_code == 415
    assert client.post(f"/api/assignments/{aid}/submissions", files={"files": ("x.docx", b"not a zip")}).status_code == 415

    with open(work, "rb") as f:
        r = client.post(f"/api/assignments/{aid}/submissions", files={"files": ("w.docx", f)},
                        data={"student_label": "Тест"})
    assert r.status_code == 202, r.text
    sid = r.json()["id"]
    s = wait(client, f"/api/submissions/{sid}", lambda d: d["status"] in ("done", "error"))
    assert s["status"] == "done", s
    assert s["ai_score"] == 80 and s["model_used"] == "mock-judge"
    assert 0 <= s["compliance_pct"] <= 100
    rep = client.get(f"/api/submissions/{sid}/report")
    assert rep.status_code == 200 and "Талаптар бойынша тексеру" in rep.text and "жұмыста бар" in rep.text

    st = client.get(f"/api/assignments/{aid}/stats", headers=T).json()
    assert st["submissions_done"] == 1 and st["avg_ai_score"] == 80

    assert client.delete(f"/api/submissions/{sid}", headers=T).status_code == 204
    assert client.get(f"/api/submissions/{sid}").status_code == 404


def test_ai_failure_still_gives_report(client, checklist, monkeypatch, tmp_path):
    """When every model fails the submission ends as done + readable ai_error, never hangs."""
    r = client.post("/api/assignments", headers=T, data={"title": "БӨЖ", "type": "БӨЖ", "course_name": "ДБ",
                                                         "requirement_text": "x"})
    aid = r.json()["id"]
    wait(client, f"/api/assignments/{aid}", lambda d: d["checklist_status"] != "extracting")
    client.put(f"/api/assignments/{aid}/checklist", headers=T, json={"checklist": checklist, "confirm": True})
    work = make_work(tmp_path / "w.docx", Spec(body_paras=30))
    with open(work, "rb") as f:
        sid = client.post(f"/api/assignments/{aid}/submissions", files={"files": ("w.docx", f)}).json()["id"]
    s = wait(client, f"/api/submissions/{sid}", lambda d: d["status"] in ("done", "error"))
    assert s["status"] == "done" and "GEMINI_API_KEY" in s["ai_error"]
    assert s["ai_score"] is None and s["compliance_pct"] is not None
