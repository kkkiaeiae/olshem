"""Unified LLM layer.

* one call signature for every pipeline stage, the model is chosen per stage;
* 503 / timeouts -> retry the same model with back-off; 429 / 404 / 403 -> go straight
  to the next model of the chain (retrying cannot help with quota or a missing model);
* models that the start-up probe found unavailable are moved to the end of the chain;
* output is forced to JSON and validated with pydantic, so the rest of the system never
  sees free-form text.
"""
from __future__ import annotations

import logging
import pathlib
import threading
import time
from typing import Any, Type, TypeVar

from pydantic import BaseModel

from ..config import settings

log = logging.getLogger("olshem.llm")
T = TypeVar("T", bound=BaseModel)

MIME = {".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg", ".webp": "image/webp"}


class LLMUnavailable(RuntimeError):
    """Raised when no model of a stage could answer. Message is human readable (Kazakh)."""


_client = None
_client_lock = threading.Lock()


def client():
    global _client
    if not settings.gemini_api_key:
        raise LLMUnavailable("GEMINI_API_KEY орнатылмаған — ЖИ кезеңдері қолжетімсіз.")
    with _client_lock:
        if _client is None:
            from google import genai
            _client = genai.Client(api_key=settings.gemini_api_key)
    return _client


def file_part(path: str | pathlib.Path):
    from google.genai import types
    p = pathlib.Path(path)
    return types.Part.from_bytes(data=p.read_bytes(), mime_type=MIME[p.suffix.lower()])


def bytes_part(data: bytes, mime: str):
    from google.genai import types
    return types.Part.from_bytes(data=data, mime_type=mime)


def _code(e: Exception) -> int | None:
    c = getattr(e, "code", None) or getattr(e, "status_code", None)
    if isinstance(c, int):
        return c
    head = str(e)[:16]
    for k in (400, 403, 404, 429, 500, 503, 504):
        if str(k) in head:
            return k
    return None


# ---------------- model availability probe ----------------
_probe: dict[str, dict[str, Any]] = {}
_probe_at = 0.0
_probe_lock = threading.Lock()


def probe_models(force: bool = False, ttl: int = 900) -> dict[str, dict[str, Any]]:
    """Send a 1-token request to every configured model; cache the result for `ttl` seconds."""
    global _probe_at
    if not settings.gemini_api_key:
        return {m: {"status": "no_key"} for m in sorted({m for c in settings.models.values() for m in c})}
    with _probe_lock:
        if _probe and not force and time.time() - _probe_at < ttl:
            return dict(_probe)
        from google.genai import types
        res: dict[str, dict[str, Any]] = {}
        for m in sorted({m for c in settings.models.values() for m in c}):
            t0 = time.time()
            try:
                client().models.generate_content(
                    model=m, contents="ok",
                    config=types.GenerateContentConfig(max_output_tokens=4, temperature=0,
                                                       http_options=types.HttpOptions(timeout=20_000)))
                res[m] = {"status": "ok", "latency_s": round(time.time() - t0, 2)}
            except Exception as e:  # noqa: BLE001
                c = _code(e)
                res[m] = {"status": {429: "quota", 404: "not_found", 403: "forbidden", 503: "overloaded"}.get(c, "error"),
                          "code": c, "detail": str(e)[:120]}
        _probe.clear(); _probe.update(res); _probe_at = time.time()
        log.info("model probe: %s", {k: v["status"] for k, v in res.items()})
        return dict(res)


def chain(stage: str) -> list[str]:
    """Configured chain reordered by the probe: answering models first, then the overloaded or
    unknown ones (they may recover), and models with no quota / not found last."""
    models = list(settings.models[stage])

    def rank(m: str) -> int:
        st = _probe.get(m, {}).get("status")
        return 0 if st == "ok" else 2 if st in ("quota", "not_found", "forbidden") else 1
    return sorted(models, key=rank)  # stable: keeps the configured order inside each group


def call_json(stage: str, contents: list, schema: Type[T], system: str | None = None,
              retries: int = 2) -> tuple[T, str]:
    """Run the stage's model chain; return (validated object, model name)."""
    from google.genai import types
    last: Exception | None = None
    tried: list[str] = []
    for model in chain(stage):
        for attempt in range(retries):
            try:
                t0 = time.time()
                r = client().models.generate_content(
                    model=model, contents=contents,
                    config=types.GenerateContentConfig(
                        system_instruction=system, temperature=0.2,
                        response_mime_type="application/json", response_schema=schema,
                        http_options=types.HttpOptions(timeout=settings.llm_timeout_s[stage] * 1000)))
                obj = schema.model_validate_json(r.text)
                log.info("[%s] %s ok in %.1fs", stage, model, time.time() - t0)
                return obj, model
            except LLMUnavailable:
                raise
            except Exception as e:  # noqa: BLE001
                last = e
                c = _code(e)
                log.warning("[%s] %s attempt %d failed (%s): %s", stage, model, attempt + 1, c, str(e)[:200])
                if c in (429, 404, 403, 400):
                    break
                time.sleep(2 + 2 * attempt)
        tried.append(model)
    raise LLMUnavailable(
        f"ЖИ модельдері жауап бермеді ({', '.join(tried)}). Соңғы қате: {str(last)[:160]}")
