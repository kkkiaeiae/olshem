"""Runtime AI configuration (provider, key, base URL, model chains), stored in the database.

* The key never leaves the server: the API only shows its last 4 characters.
* Switching provider without giving a new key drops the old key (a Gemini key is never sent
  to an OpenAI-compatible endpoint, and vice versa).
* "Reset" deletes the stored config, and the environment variables apply again."""
from __future__ import annotations

import json
import logging
import re

from sqlmodel import Session

from ..config import settings
from ..core import llm
from ..models.entities import Setting

log = logging.getLogger("olshem.ai_settings")
KEY = "ai_config"
MODEL_RE = re.compile(r"^[A-Za-z0-9._:/@+-]{1,100}$")


def mask(key: str | None) -> str | None:
    return f"…{key[-4:]}" if key and len(key) >= 8 else ("…" if key else None)


def _from_row(raw: str) -> llm.AIConfig | None:
    try:
        d = json.loads(raw)
        return llm.AIConfig(provider=d["provider"], api_key=d.get("api_key") or None,
                            base_url=d.get("base_url") or None,
                            models={k: list(v) for k, v in (d.get("models") or {}).items()}, source="db")
    except Exception:  # noqa: BLE001 — a broken row must not stop the app
        log.exception("stored ai_config is unreadable, ignoring it")
        return None


def load(s: Session) -> llm.AIConfig | None:
    row = s.get(Setting, KEY)
    return _from_row(row.value) if row else None


def apply_stored(s: Session) -> None:
    """Called at start-up: activate the stored config, if any."""
    cfg = load(s)
    llm.configure(cfg)
    if cfg:
        log.info("AI config from database: provider=%s, key=%s", cfg.provider, mask(cfg.api_key))


def default_models(provider: str) -> dict[str, list[str]]:
    preset = llm.PRESETS[provider]["models"]
    return {k: list(v) for k, v in (preset or settings.models).items()}


def clean_models(models: dict[str, list[str]] | None, provider: str) -> dict[str, list[str]]:
    base = default_models(provider)
    out: dict[str, list[str]] = {}
    for st in llm.STAGES:
        chain = [m.strip() for m in (models or {}).get(st, []) if m and m.strip()]
        seen: list[str] = []
        for m in chain:
            if not MODEL_RE.match(m):
                raise ValueError(f"«{m}» — модель атауы дұрыс емес")
            if m not in seen:
                seen.append(m)
        if len(seen) > 6:
            raise ValueError(f"{st}: ең көбі 6 модель")
        out[st] = seen or base[st]
    return out


def clean_base_url(provider: str, base_url: str | None) -> str | None:
    if provider == "gemini":
        return None
    url = (base_url or "").strip() or llm.OPENAI_DEFAULT_URL
    if not re.match(r"^https?://[^\s/]+", url):
        raise ValueError("base_url http:// немесе https:// деп басталуы керек")
    return url.rstrip("/")


def build(provider: str, api_key: str | None, base_url: str | None,
          models: dict[str, list[str]] | None, previous: llm.AIConfig) -> llm.AIConfig:
    """Validated config from user input. An empty key keeps the previous key only when the
    provider (and, for OpenAI-compatible, the endpoint) did not change."""
    if provider not in llm.PRESETS:
        raise ValueError("provider: gemini немесе openai")
    url = clean_base_url(provider, base_url)
    key = (api_key or "").strip() or None
    if key is None and previous.provider == provider and (provider == "gemini" or previous.base_url == url):
        key = previous.api_key
    return llm.AIConfig(provider=provider, api_key=key, base_url=url,
                        models=clean_models(models, provider), source="db")


def save(s: Session, cfg: llm.AIConfig) -> llm.AIConfig:
    row = s.get(Setting, KEY) or Setting(key=KEY, value="")
    row.value = json.dumps({"provider": cfg.provider, "api_key": cfg.api_key, "base_url": cfg.base_url,
                            "models": cfg.models})
    s.add(row); s.commit()
    llm.configure(cfg)
    log.info("AI config saved: provider=%s, key=%s, models=%s", cfg.provider, mask(cfg.api_key), cfg.models)
    return cfg


def reset(s: Session) -> llm.AIConfig:
    row = s.get(Setting, KEY)
    if row:
        s.delete(row); s.commit()
    llm.configure(None)
    return llm.current()
