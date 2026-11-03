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
