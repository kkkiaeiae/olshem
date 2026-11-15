"""Unified LLM layer.

* one call signature for every pipeline stage, the model is chosen per stage;
* two kinds of provider: ``gemini`` (google-genai, PDFs and images sent natively) and ``openai``
  (any OpenAI-compatible Chat Completions API: OpenAI, DeepSeek, OpenRouter, Qwen/DashScope,
  a local Ollama / vLLM). In OpenAI mode images go as data URLs and PDFs as extracted text;
* the active provider/key/models can be changed at runtime (``configure``) — see
  services/ai_settings.py; by default everything comes from environment variables;
* 503 / timeouts -> retry the same model with back-off; 400/401/403/404/429 -> go straight
  to the next model of the chain (retrying cannot help with quota or a missing model);
* models that the probe found unavailable are moved to the end of the chain;
* output is forced to JSON and validated with pydantic, so the rest of the system never
  sees free-form text.
"""
from __future__ import annotations

import base64
import copy
import io
import json
import logging
import pathlib
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Literal, Type, TypeVar
from urllib.parse import urlparse

from pydantic import BaseModel

from ..config import settings

log = logging.getLogger("olshem.llm")
T = TypeVar("T", bound=BaseModel)

MIME = {".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg", ".webp": "image/webp"}
STAGES = ("extract", "ocr", "judge")
Provider = Literal["gemini", "openai"]
PDF_TEXT_LIMIT = 60_000


class LLMUnavailable(RuntimeError):
    """Raised when no model of a stage could answer. Message is human readable (Kazakh)."""


# ---------------------------------------------------------------- provider-neutral content
@dataclass
class Blob:
    """A file handed to the model. Converted to the provider's format only at call time."""
    data: bytes
    mime: str
    name: str = ""


def file_part(path: str | pathlib.Path) -> Blob:
    p = pathlib.Path(path)
    return Blob(p.read_bytes(), MIME[p.suffix.lower()], p.name)


def bytes_part(data: bytes, mime: str) -> Blob:
    return Blob(data, mime)


def pdf_text(data: bytes, limit: int = PDF_TEXT_LIMIT) -> str:
    """Text layer of a PDF (for providers that cannot read PDFs). Scanned PDFs yield little text."""
    import pdfplumber
    out: list[str] = []
    size = 0
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for i, page in enumerate(pdf.pages, 1):
            t = (page.extract_text() or "").strip()
            if t:
                out.append(f"[{i}-бет]\n{t}")
                size += len(t)
            if size >= limit:
                break
    text = "\n\n".join(out)[:limit]
    return text or "[PDF-те мәтін қабаты жоқ (сканерленген болуы мүмкін) — мазмұнын оқу мүмкін болмады]"


# ---------------------------------------------------------------- runtime configuration
@dataclass
class AIConfig:
    provider: Provider = "gemini"
    api_key: str | None = None
    base_url: str | None = None
    models: dict[str, list[str]] = field(default_factory=dict)
    source: Literal["env", "db"] = "env"

    def needs_key(self) -> bool:
        if self.provider == "gemini":
            return True
        host = (urlparse(self.base_url or "").hostname or "").lower()
        return host not in ("localhost", "127.0.0.1", "::1")

    @property
    def configured(self) -> bool:
        return bool(self.api_key) or not self.needs_key()


OPENAI_DEFAULT_URL = "https://api.openai.com/v1"
PRESETS: dict[str, dict[str, Any]] = {
    "gemini": {"label": "Google Gemini", "provider": "gemini", "base_url": None,
               "models": None},  # None -> the env/config default chains
    "openai": {"label": "OpenAI", "provider": "openai", "base_url": OPENAI_DEFAULT_URL,
               "models": {"extract": ["gpt-4o-mini"], "ocr": ["gpt-4o"], "judge": ["gpt-4o", "gpt-4o-mini"]}},
}


def env_config() -> AIConfig:
    # `models` is the very dict from settings, so env overrides (and tests) apply directly
    return AIConfig(provider="gemini", api_key=settings.gemini_api_key, base_url=None,
                    models=settings.models, source="env")


_cfg: AIConfig | None = None
_client = None
_client_lock = threading.Lock()


def current() -> AIConfig:
    return _cfg or env_config()


def configure(cfg: AIConfig | None) -> None:
    """Switch provider/key/models at runtime (None -> back to environment defaults)."""
    global _cfg, _client
    with _client_lock:
        _cfg = cfg
        _client = None
    with _probe_lock:
        _probe.clear()


def is_configured() -> bool:
    return current().configured


def stage_models() -> dict[str, list[str]]:
    m = current().models or settings.models
    return {st: list(m.get(st) or settings.models[st]) for st in STAGES}


def all_models() -> list[str]:
    return sorted({x for c in stage_models().values() for x in c})


# ---------------------------------------------------------------- Gemini
# google-genai 3.x switched its default from v1beta to v1, where the `*-latest` aliases and some
# preview models do not exist (404) and requests time out (504). Pin the version explicitly.
GEMINI_API_VERSION = "v1beta"


def new_gemini_client(api_key: str):
    from google import genai
    from google.genai import types
    return genai.Client(api_key=api_key, http_options=types.HttpOptions(api_version=GEMINI_API_VERSION))


def client():
    """google-genai client for the active Gemini config."""
    cfg = current()
    if not cfg.api_key:
        raise LLMUnavailable("GEMINI_API_KEY орнатылмаған — ЖИ кезеңдері қолжетімсіз.")
    global _client
    with _client_lock:
        if _client is None:
            _client = new_gemini_client(cfg.api_key)
    return _client


def _gemini_contents(contents: list) -> list:
    from google.genai import types
    return [types.Part.from_bytes(data=c.data, mime_type=c.mime) if isinstance(c, Blob) else c
            for c in contents]


def _gemini_call(cli, model: str, contents: list, schema: Type[T] | None, system: str | None,
                 timeout_s: float, max_tokens: int | None = None) -> str:
    from google.genai import types
    cfg = types.GenerateContentConfig(
        system_instruction=system, temperature=0.2 if schema else 0,
        http_options=types.HttpOptions(timeout=int(timeout_s * 1000)))
    if schema is not None:
        cfg.response_mime_type, cfg.response_schema = "application/json", schema
    if max_tokens:
        cfg.max_output_tokens = max_tokens
    r = cli.models.generate_content(model=model, contents=_gemini_contents(contents), config=cfg)
    return r.text or ""


# ---------------------------------------------------------------- OpenAI-compatible
class HTTPError(Exception):
    def __init__(self, code: int | None, msg: str):
        super().__init__(f"{code} {msg}")
        self.code = code


def _openai_content(contents: list) -> list[dict]:
    out: list[dict] = []
    for c in contents:
        if isinstance(c, Blob):
            if c.mime.startswith("image/"):
                url = f"data:{c.mime};base64,{base64.b64encode(c.data).decode()}"
                out.append({"type": "image_url", "image_url": {"url": url}})
            elif c.mime == "application/pdf":
                out.append({"type": "text", "text": f"[PDF {c.name}]\n{pdf_text(c.data)}"})
        else:
            out.append({"type": "text", "text": str(c)})
    return out


def _strip_fences(s: str) -> str:
    s = s.strip()
    m = re.match(r"^```(?:json)?\s*(.*?)\s*```$", s, re.S)
    return m.group(1) if m else s


def _openai_call(cfg: AIConfig, model: str, contents: list, schema: Type[T] | None, system: str | None,
                 timeout_s: float, max_tokens: int | None = None) -> str:
    import httpx
    sys_txt = system or ""
    if schema is not None:
        sys_txt += ("\n\nReturn ONLY one JSON object (no markdown) that validates against this JSON Schema:\n"
                    + json.dumps(schema.model_json_schema(), ensure_ascii=False))
    body: dict[str, Any] = {"model": model, "messages": ([{"role": "system", "content": sys_txt.strip()}] if sys_txt.strip() else [])
                            + [{"role": "user", "content": _openai_content(contents)}]}
    if schema is not None:
        body["response_format"] = {"type": "json_object"}
        body["temperature"] = 0.2
    if max_tokens:
        body["max_tokens"] = max_tokens
    headers = {"Content-Type": "application/json"}
    if cfg.api_key:
        headers["Authorization"] = f"Bearer {cfg.api_key}"
    url = (cfg.base_url or OPENAI_DEFAULT_URL).rstrip("/") + "/chat/completions"
    try:
        r = httpx.post(url, json=body, headers=headers, timeout=timeout_s)
    except httpx.TimeoutException as e:
        raise HTTPError(None, f"timeout: {e}") from e
    except httpx.HTTPError as e:
        raise HTTPError(None, f"connection error: {e}") from e
    if r.status_code >= 400:
        raise HTTPError(r.status_code, r.text[:300])
    try:
        return r.json()["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, ValueError) as e:
        raise HTTPError(None, f"unexpected response: {r.text[:200]}") from e


# ---------------------------------------------------------------- one call, any provider
def _raw_call(cfg: AIConfig, model: str, contents: list, schema, system, timeout_s, max_tokens=None,
              gemini_client=None) -> str:
    if cfg.provider == "openai":
        if not cfg.configured:
            raise LLMUnavailable("ЖИ провайдерінің API кілті орнатылмаған — ЖИ кезеңдері қолжетімсіз.")
        return _openai_call(cfg, model, contents, schema, system, timeout_s, max_tokens)
    cli = gemini_client or client()
    return _gemini_call(cli, model, contents, schema, system, timeout_s, max_tokens)


def _code(e: Exception) -> int | None:
    c = getattr(e, "code", None) or getattr(e, "status_code", None)
    if isinstance(c, int):
        return c
    head = str(e)[:16]
    for k in (400, 401, 403, 404, 429, 500, 503, 504):
        if str(k) in head:
            return k
    return None


# ---------------------------------------------------------------- model availability probe
_probe: dict[str, dict[str, Any]] = {}
_probe_at = 0.0
_probe_lock = threading.Lock()
_STATUS = {429: "quota", 404: "not_found", 403: "forbidden", 401: "unauthorized", 503: "overloaded"}


def probe_with(cfg: AIConfig, models: list[str]) -> dict[str, dict[str, Any]]:
    """Send a tiny request to each model with the given config (used by the probe and by the
    settings «Тексеру» button, which tests a draft config without saving it)."""
    if not cfg.configured:
        return {m: {"status": "no_key"} for m in models}
    gem = None
    if cfg.provider == "gemini":
        gem = new_gemini_client(cfg.api_key)
    res: dict[str, dict[str, Any]] = {}
    for m in models:
        t0 = time.time()
        try:
            _raw_call(cfg, m, ["ok"], None, None, 20, max_tokens=4, gemini_client=gem)
            res[m] = {"status": "ok", "latency_s": round(time.time() - t0, 2)}
        except Exception as e:  # noqa: BLE001
            c = _code(e)
            res[m] = {"status": _STATUS.get(c, "error"), "code": c, "detail": str(e)[:160]}
    return res


def probe_models(force: bool = False, ttl: int = 900) -> dict[str, dict[str, Any]]:
    """Probe every configured model of the active config; cache the result for `ttl` seconds."""
    global _probe_at
    cfg = current()
    if not cfg.configured:
        return {m: {"status": "no_key"} for m in all_models()}
    with _probe_lock:
        if _probe and not force and time.time() - _probe_at < ttl:
            return dict(_probe)
    res = probe_with(cfg, all_models())
    with _probe_lock:
        _probe.clear(); _probe.update(res); _probe_at = time.time()
    log.info("model probe (%s): %s", cfg.provider, {k: v["status"] for k, v in res.items()})
    return dict(res)


def probe_snapshot() -> dict[str, dict[str, Any]]:
    with _probe_lock:
        return copy.deepcopy(_probe)


def chain(stage: str) -> list[str]:
    """Configured chain reordered by the probe: answering models first, then the overloaded or
    unknown ones (they may recover), and models with no quota / not found last."""
    models = stage_models()[stage]

    def rank(m: str) -> int:
        st = _probe.get(m, {}).get("status")
        return 0 if st == "ok" else 2 if st in ("quota", "not_found", "forbidden", "unauthorized") else 1
    return sorted(models, key=rank)  # stable: keeps the configured order inside each group


def call_json(stage: str, contents: list, schema: Type[T], system: str | None = None,
              retries: int = 2) -> tuple[T, str]:
    """Run the stage's model chain; return (validated object, model name)."""
    cfg = current()
    last: Exception | None = None
    tried: list[str] = []
    for model in chain(stage):
        for attempt in range(retries):
            try:
                t0 = time.time()
                text = _raw_call(cfg, model, contents, schema, system, settings.llm_timeout_s[stage])
                obj = schema.model_validate_json(_strip_fences(text))
                log.info("[%s] %s/%s ok in %.1fs", stage, cfg.provider, model, time.time() - t0)
                return obj, model
            except LLMUnavailable:
                raise
            except Exception as e:  # noqa: BLE001
                last = e
                c = _code(e)
                log.warning("[%s] %s attempt %d failed (%s): %s", stage, model, attempt + 1, c, str(e)[:200])
                if c in (429, 404, 403, 401, 400):
                    break
                time.sleep(2 + 2 * attempt)
        tried.append(model)
    raise LLMUnavailable(
        f"ЖИ модельдері жауап бермеді ({', '.join(tried)}). Соңғы қате: {str(last)[:160]}")
