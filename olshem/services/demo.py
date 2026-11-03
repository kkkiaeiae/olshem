"""Demo mode: a safety net for the live defence. When it is ON, works whose file hash matches
a cached sample are answered from the cache, and requirement files that match the cached
ПОӘК return the cached checklist. Everything served this way is labelled «Демо режимі»."""
from __future__ import annotations

import functools
import hashlib
import json
import pathlib

from sqlmodel import Session

from ..config import settings
from ..models.entities import Setting


@functools.lru_cache(maxsize=1)
def work_cache() -> dict[str, dict]:
    out = {}
    for f in (settings.demo_dir / "cache").glob("*.json"):
        d = json.loads(f.read_text(encoding="utf-8"))
        out[d["sha256"]] = d
    return out


@functools.lru_cache(maxsize=1)
def checklist_cache() -> dict[str, dict]:
    """sha256 of the demo requirements PDF -> demo checklist."""
    req = settings.demo_dir / "talaptar.pdf"
    cl = settings.demo_dir / "checklist.json"
    if not (req.exists() and cl.exists()):
        return {}
    return {hashlib.sha256(req.read_bytes()).hexdigest(): json.loads(cl.read_text(encoding="utf-8"))}


def demo_checklist() -> dict:
    return json.loads((settings.demo_dir / "checklist.json").read_text(encoding="utf-8"))


def is_demo_mode(s: Session) -> bool:
    row = s.get(Setting, "demo_mode")
    return settings.demo_mode_default if row is None else row.value == "1"


def set_demo_mode(s: Session, on: bool) -> None:
    row = s.get(Setting, "demo_mode") or Setting(key="demo_mode", value="0")
    row.value = "1" if on else "0"
    s.add(row)
    s.commit()


def sha256(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()
