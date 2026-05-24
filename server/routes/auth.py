from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from server.auth import get_current_user_id, login_user, logout_user
from server.dependencies import get_templates, get_user_repo

router = APIRouter(tags=["auth"])


@router.get("/login", response_class=HTMLResponse)
async def login_form(request: Request) -> HTMLResponse:
    if get_current_user_id(request) is not None:
        return RedirectResponse(url="/groups", status_code=302)
    templates = get_templates()
    return templates.TemplateResponse(
        request,
        "auth/login.html",
        {"error": request.query_params.get("error")},
    )


@router.post("/login")
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
) -> RedirectResponse:
    user_repo = get_user_repo()
    user = user_repo.authenticate(username, password)
    if user is None:
        return RedirectResponse(url="/login?error=Credenciais+inválidas", status_code=303)
    login_user(request, user.id)
    return RedirectResponse(url="/groups", status_code=303)


@router.get("/logout")
async def logout(request: Request) -> RedirectResponse:
    logout_user(request)
    return RedirectResponse(url="/login", status_code=302)
