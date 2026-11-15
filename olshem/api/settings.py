"""AI provider settings: which provider, key, endpoint and model chains the pipeline uses.
The key is stored only on the server and is never returned (only its last 4 characters)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from ..config import settings
from ..core import llm
from ..models.db import get_session
from ..models.schemas import AIPreset, AISettingsIn, AISettingsOut, AITestModel, AITestOut, StageModels
from ..services import ai_settings, ratelimit
from .deps import User, require_admin, require_teacher

router = APIRouter(prefix="/api/settings", tags=["Жүйе"])


def _out(cfg: llm.AIConfig) -> AISettingsOut:
    models = {st: list((cfg.models or settings.models).get(st) or settings.models[st]) for st in llm.STAGES}
    presets = [AIPreset(key=k, label=p["label"], provider=p["provider"], base_url=p["base_url"],
                        models=StageModels(**ai_settings.default_models(k))) for k, p in llm.PRESETS.items()]
    return AISettingsOut(provider=cfg.provider, base_url=cfg.base_url, models=StageModels(**models),
                         key_set=bool(cfg.api_key), key_hint=ai_settings.mask(cfg.api_key), source=cfg.source,
                         admin_token_required=bool(settings.admin_token),
                         editable=bool(settings.admin_token), presets=presets)


def _build(body: AISettingsIn) -> llm.AIConfig:
    try:
        return ai_settings.build(body.provider, body.api_key, body.base_url,
                                 body.models.model_dump() if body.models else None, llm.current())
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


@router.get("/ai", response_model=AISettingsOut, summary="ЖИ провайдерінің баптаулары (кілтсіз)")
def get_ai(_: User = Depends(require_teacher)):
    return _out(llm.current())


@router.put("/ai", response_model=AISettingsOut, summary="ЖИ провайдерін / кілтін / модельдерін сақтау")
def put_ai(body: AISettingsIn, s: Session = Depends(get_session), _: User = Depends(require_admin)):
    cfg = _build(body)
    if not cfg.configured:
        raise HTTPException(422, "API кілтін енгізіңіз (провайдер ауысқанда бұрынғы кілт сақталмайды)")
    ai_settings.save(s, cfg)
    return _out(cfg)


@router.delete("/ai", response_model=AISettingsOut, summary="Әдепкі баптауларға (орта айнымалылары) қайту")
def reset_ai(s: Session = Depends(get_session), _: User = Depends(require_admin)):
    return _out(ai_settings.reset(s))


@router.post("/ai/test", response_model=AITestOut,
             summary="Баптауларды сақтамай тексеру: әр модельге шағын сұрау жібереді")
def test_ai(body: AISettingsIn, _: User = Depends(require_admin),
            __: None = Depends(ratelimit.limit("ai_test"))):
    cfg = _build(body)
    if not cfg.configured:
        raise HTTPException(422, "API кілтін енгізіңіз")
    stages_of: dict[str, list[str]] = {}
    for st in llm.STAGES:
        for m in cfg.models[st]:
            stages_of.setdefault(m, []).append(st)
    res = llm.probe_with(cfg, list(stages_of))
    out = [AITestModel(model=m, stages=stages_of[m], **res[m]) for m in stages_of]
    ok = all(any(res[m]["status"] == "ok" for m in cfg.models[st]) for st in llm.STAGES)
    return AITestOut(ok=ok, provider=cfg.provider, results=out)
