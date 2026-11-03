"""Safe upload handling: size limit, extension + magic-byte check, random file names.
Files stay on the server's local disk only."""
from __future__ import annotations

import hashlib
import pathlib
import uuid

from fastapi import HTTPException, UploadFile

from ..config import settings

MAGIC = {
    ".docx": (b"PK\x03\x04",),
    ".pdf": (b"%PDF",),
    ".jpg": (b"\xff\xd8\xff",), ".jpeg": (b"\xff\xd8\xff",),
    ".png": (b"\x89PNG",),
    ".webp": (b"RIFF",),
}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp"}


def _err(msg: str, code: int = 400) -> HTTPException:
    return HTTPException(status_code=code, detail=msg)


async def save_upload(f: UploadFile, allowed: set[str]) -> tuple[pathlib.Path, str, str]:
    """Returns (stored path, original name, sha256)."""
    name = pathlib.Path(f.filename or "file").name
    ext = pathlib.Path(name).suffix.lower()
    if ext not in allowed:
        raise _err(f"«{name}»: бұл файл түрі қабылданбайды. Рұқсат: {', '.join(sorted(allowed))}", 415)
    limit = settings.max_upload_mb * 1024 * 1024
    data = bytearray()
    while chunk := await f.read(1024 * 1024):
        data += chunk
        if len(data) > limit:
            raise _err(f"«{name}» тым үлкен: шегі {settings.max_upload_mb} МБ", 413)
    if not data:
        raise _err(f"«{name}» бос файл")
    if not any(bytes(data[:8]).startswith(m) for m in MAGIC[ext]):
        raise _err(f"«{name}» мазмұны {ext} форматына сәйкес емес", 415)
    if ext == ".webp" and data[8:12] != b"WEBP":
        raise _err(f"«{name}» мазмұны .webp форматына сәйкес емес", 415)
    path = settings.upload_dir / f"{uuid.uuid4().hex}{ext}"
    path.write_bytes(bytes(data))
    return path, name, hashlib.sha256(data).hexdigest()


def stored(name: str | None) -> pathlib.Path | None:
    """Resolve a stored file name; refuses anything outside the upload dir."""
    if not name:
        return None
    p = (settings.upload_dir / pathlib.Path(name).name).resolve()
    return p if p.exists() else None


def delete(names: list[str]) -> None:
    for n in names:
        p = stored(n)
        if p:
            p.unlink(missing_ok=True)
