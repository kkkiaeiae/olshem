from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlmodel import Session

from .. import __version__
from ..config import settings
from ..core import llm
from ..core.format_checker import soffice_available
from ..models.db import get_session
from ..models.schemas import DemoModeIn, HealthOut, ModelStatus
from ..services import demo
from .deps import User, require_teacher

router = APIRouter(prefix="/api", tags=["Жүйе"])


@router.get("/health", response_model=HealthOut, summary="Жүйе күйі және ЖИ модельдерінің қолжетімділігі")
def health(refresh: bool = False, s: Session = Depends(get_session)):
    probe = llm.probe_models(force=True) if refresh else dict(llm._probe) or {
        m: {"status": "no_key" if not settings.gemini_api_key else "unknown"}
        for m in sorted({m for c in settings.models.values() for m in c})}
    ai_ok = bool(settings.gemini_api_key) and any(v.get("status") == "ok" for v in probe.values())
    return HealthOut(
        status="ok" if ai_ok and soffice_available() else "degraded", version=__version__,
        demo_mode=demo.is_demo_mode(s), ai_configured=bool(settings.gemini_api_key),
        libreoffice=soffice_available(), models={k: ModelStatus(**v) for k, v in probe.items()},
        stage_chains={k: llm.chain(k) for k in settings.models})


@router.get("/demo-mode", response_model=DemoModeIn, summary="Демо режимі қосулы ма")
def get_demo(s: Session = Depends(get_session)):
    return DemoModeIn(enabled=demo.is_demo_mode(s))


@router.put("/demo-mode", response_model=DemoModeIn, summary="Демо режимін қосу/өшіру (қорғаудағы сақтандыру)")
def put_demo(body: DemoModeIn, s: Session = Depends(get_session), _: User = Depends(require_teacher)):
    demo.set_demo_mode(s, body.enabled)
    return DemoModeIn(enabled=demo.is_demo_mode(s))
