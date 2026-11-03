"""Өлшем — жазбаша жұмыстарды ЖИ арқылы алдын ала тексеру жүйесі.

Run:  uvicorn olshem.main:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .api import assignments, submissions, system
from .config import ROOT, settings
from .core import llm
from .models.db import init_db
from .services import jobs, seed

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("olshem")
WEB = ROOT / "olshem" / "web"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    seed.seed_if_empty()
    jobs.resume_unfinished()
    if settings.probe_on_start and settings.gemini_api_key:
        threading.Thread(target=llm.probe_models, daemon=True).start()
    yield


DESCRIPTION = """
**Өлшем** — «Әр жұмысқа — бір өлшем.»

Оқытушы талаптарын (ПОӘК, силлабус, мәтін) тексеру тізіміне айналдырып, студенттердің жазбаша
жұмыстарын сол тізім бойынша алдын ала тексеретін жүйе.

Кезеңдер: ① талаптар → тізім (ЖИ) · ② рәсімдеу (бағдарлама) · ③ қолжазба OCR (ЖИ) ·
④ мазмұн (ЖИ) + ④b дәйексөздерді тексеру (бағдарлама).

Ұзақ тапсырмалар фонда орындалады: `POST` → `202` → `GET /api/submissions/{id}` (немесе `/events` SSE).

Демо кезінде рөл `X-Role: teacher|student` тақырыбымен беріледі; SmartENU-да ол SSO токенімен ауыстырылады.
"""

app = FastAPI(title="Өлшем API", version=__version__, description=DESCRIPTION, lifespan=lifespan,
              openapi_tags=[{"name": "Тапсырмалар", "description": "Пәндер, тапсырмалар, тексеру тізімі, статистика"},
                            {"name": "Жұмыстар", "description": "Студент жұмыстары, тексеру барысы, есеп"},
                            {"name": "Жүйе", "description": "Күйі, модельдер, демо режимі"}])


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "same-origin")
    return resp


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, exc: RequestValidationError):
    msgs = [f"{'.'.join(str(x) for x in e.get('loc', [])[1:])}: {e.get('msg')}" for e in exc.errors()]
    return JSONResponse(status_code=422, content={"detail": "Деректер дұрыс емес — " + "; ".join(msgs)})


@app.exception_handler(Exception)
async def unhandled(_: Request, exc: Exception):
    log.exception("unhandled error")
    return JSONResponse(status_code=500, content={"detail": "Серверде күтпеген қате шықты. Қайталап көріңіз."})


app.include_router(assignments.router)
app.include_router(submissions.router)
app.include_router(system.router)
app.mount("/static", StaticFiles(directory=WEB / "static"), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(WEB / "index.html", headers={"Cache-Control": "no-cache"})
