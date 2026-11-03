"""Application settings. Everything comes from environment variables (or a local .env);
secrets are never stored in code or in the repository."""
from __future__ import annotations

import os
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _load_env() -> None:
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env()


def _bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


def _list(name: str, default: list[str]) -> list[str]:
    raw = os.environ.get(name)
    return [m.strip() for m in raw.split(",") if m.strip()] if raw else default


class Settings:
    app_name = "Өлшем"
    tagline = "Әр жұмысқа — бір өлшем."
    gemini_api_key: str | None = os.environ.get("GEMINI_API_KEY") or None
    data_dir = pathlib.Path(os.environ.get("DATA_DIR", ROOT / "data"))
    demo_dir = ROOT / "demo"
    max_upload_mb = int(os.environ.get("MAX_UPLOAD_MB", "20"))
    max_photos = int(os.environ.get("MAX_PHOTOS", "12"))
    demo_mode_default = _bool("DEMO_MODE", False)
    seed_demo = _bool("SEED_DEMO", True)
    probe_on_start = _bool("PROBE_MODELS_ON_START", True)
    max_parallel_jobs = int(os.environ.get("MAX_PARALLEL_JOBS", "2"))
    # Stage -> ordered model chain (first = primary, others = fallbacks).
    # Measured 2026-11-03 on the free tier: 3.5-flash stable; 3.8-flash / flash-latest often 503;
    # Pro models 429 (no free quota). Override with env vars without touching code.
    models = {
        "extract": _list("MODELS_EXTRACT", ["gemini-3.5-flash", "gemini-3.8-flash", "gemini-3.1-flash-lite"]),
        "ocr": _list("MODELS_OCR", ["gemini-3.5-flash", "gemini-3.8-flash", "gemini-3.1-flash-lite"]),
        "judge": _list("MODELS_JUDGE", ["gemini-pro-latest", "gemini-3.8-flash", "gemini-3.5-flash", "gemini-flash-latest"]),
    }
    llm_timeout_s = {"extract": 90, "ocr": 90, "judge": 150}

    @property
    def upload_dir(self) -> pathlib.Path:
        p = self.data_dir / "uploads"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def db_url(self) -> str:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        return os.environ.get("DATABASE_URL", f"sqlite:///{self.data_dir / 'olshem.db'}")


settings = Settings()
