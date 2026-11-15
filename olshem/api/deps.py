"""Identity. For the demo the role is chosen on the start page and sent as the X-Role header.

SmartENU integration point: replace `current_user` with OIDC/SAML validation of the SmartENU
token (Authorization: Bearer …) and map the ENU account to User(id, role, name). Nothing else
in the code depends on how the user was authenticated."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from fastapi import Depends, Header, HTTPException

Role = Literal["teacher", "student"]


@dataclass
class User:
    id: str
    role: Role
    name: str = ""


def current_user(x_role: str | None = Header(default=None, description="Демо: teacher | student. SmartENU SSO-мен ауыстырылады."),
                 x_user: str | None = Header(default=None)) -> User:
    role: Role = "teacher" if (x_role or "").lower() == "teacher" else "student"
    return User(id=x_user or f"demo-{role}", role=role)


def require_teacher(u: User = Depends(current_user)) -> User:
    if u.role != "teacher":
        raise HTTPException(403, "Бұл әрекет тек оқытушыға рұқсат етілген")
    return u


def require_admin(u: User = Depends(require_teacher),
                  x_admin_token: str | None = Header(default=None, description="ADMIN_TOKEN орнатылса міндетті")) -> User:
    """Changing the AI provider / key / endpoint. Fails closed: the demo roles (X-Role) are self-declared,
    so without ADMIN_TOKEN anybody could point the pipeline at their own endpoint and receive every
    student's work. Hence editing is disabled unless the server sets ADMIN_TOKEN, and then it is required."""
    import hmac

    from ..config import settings
    if not settings.admin_token:
        raise HTTPException(403, "Серверде ADMIN_TOKEN орнатылмаған: қауіпсіздік үшін ЖИ баптауларын интерфейстен "
                                 "өзгерту өшірулі. Әкімші ADMIN_TOKEN орта айнымалысын орнатуы керек.")
    if not hmac.compare_digest((x_admin_token or "").encode(), settings.admin_token.encode()):
        raise HTTPException(403, "Әкімші токені қате немесе берілмеген (X-Admin-Token)")
    return u
