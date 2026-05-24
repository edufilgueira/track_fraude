from __future__ import annotations

from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse

SESSION_USER_KEY = "user_id"


def login_user(request: Request, user_id: int) -> None:
    request.session[SESSION_USER_KEY] = user_id


def logout_user(request: Request) -> None:
    request.session.pop(SESSION_USER_KEY, None)


def get_current_user_id(request: Request) -> int | None:
    value = request.session.get(SESSION_USER_KEY)
    return int(value) if value is not None else None


def require_login(request: Request) -> int:
    user_id = get_current_user_id(request)
    if user_id is None:
        raise HTTPException(
            status_code=307,
            headers={"Location": "/login"},
        )
    return user_id


def redirect_if_not_logged_in(request: Request) -> RedirectResponse | None:
    if get_current_user_id(request) is None:
        return RedirectResponse(url="/login", status_code=302)
    return None
