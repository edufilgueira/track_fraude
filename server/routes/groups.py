from __future__ import annotations

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from server.dependencies import get_group_repo, get_project_root, get_store_repo, get_templates
from server.services.pipeline_status import processing_maps
from server.services.review_loader import has_review_evidence

router = APIRouter(prefix="/groups", tags=["groups"])


@router.get("", response_class=HTMLResponse)
async def list_groups(request: Request) -> HTMLResponse:
    repo = get_group_repo()
    groups = repo.list_groups()
    store_repo = get_store_repo()
    store_counts = {group.id: store_repo.list_stores(group_db_id=group.id) for group in groups}
    processing_groups, _, _, group_runs = processing_maps()
    templates = get_templates()
    return templates.TemplateResponse(
        request,
        "groups/list.html",
        {
            "groups": groups,
            "store_counts": {gid: len(stores) for gid, stores in store_counts.items()},
            "processing_groups": processing_groups,
            "group_runs": group_runs,
            "message": request.query_params.get("msg"),
        },
    )


@router.get("/new", response_class=HTMLResponse)
async def new_group_form(request: Request) -> HTMLResponse:
    templates = get_templates()
    return templates.TemplateResponse(
        request,
        "groups/form.html",
        {"group": None, "action": "/groups"},
    )


@router.post("")
async def create_group(
    group_code: str = Form(...),
    name: str = Form(...),
    active: str | None = Form(None),
) -> RedirectResponse:
    repo = get_group_repo()
    if repo.get_group_by_code(group_code.strip()):
        raise HTTPException(status_code=400, detail="Código do grupo já existe")
    group = repo.create_group(
        group_code=group_code,
        name=name,
        active=active == "on",
    )
    return RedirectResponse(
        url=f"/groups/{group.id}?msg=Grupo+cadastrado",
        status_code=303,
    )


@router.get("/{group_db_id}", response_class=HTMLResponse)
async def group_detail(request: Request, group_db_id: int) -> HTMLResponse:
    group_repo = get_group_repo()
    group = group_repo.get_group(group_db_id)
    if not group:
        raise HTTPException(status_code=404, detail="Grupo não encontrado")

    store_repo = get_store_repo()
    stores = store_repo.list_stores(group_db_id=group_db_id)
    project_root = get_project_root()
    _, processing_stores, store_runs, _ = processing_maps()
    store_has_review = {
        store.id: has_review_evidence(project_root, store, group_code=group.group_code)
        for store in stores
    }
    templates = get_templates()
    return templates.TemplateResponse(
        request,
        "groups/detail.html",
        {
            "group": group,
            "stores": stores,
            "processing_stores": processing_stores,
            "store_runs": store_runs,
            "store_has_review": store_has_review,
            "message": request.query_params.get("msg"),
        },
    )


@router.get("/{group_db_id}/edit", response_class=HTMLResponse)
async def edit_group_form(request: Request, group_db_id: int) -> HTMLResponse:
    repo = get_group_repo()
    group = repo.get_group(group_db_id)
    if not group:
        raise HTTPException(status_code=404, detail="Grupo não encontrado")
    templates = get_templates()
    return templates.TemplateResponse(
        request,
        "groups/form.html",
        {"group": group, "action": f"/groups/{group_db_id}/edit"},
    )


@router.post("/{group_db_id}/edit")
async def update_group(
    group_db_id: int,
    group_code: str = Form(...),
    name: str = Form(...),
    active: str | None = Form(None),
) -> RedirectResponse:
    repo = get_group_repo()
    existing = repo.get_group_by_code(group_code.strip())
    if existing and existing.id != group_db_id:
        raise HTTPException(status_code=400, detail="Código do grupo já em uso")
    repo.update_group(
        group_db_id,
        group_code=group_code.strip(),
        name=name.strip(),
        active=active == "on",
    )
    return RedirectResponse(
        url=f"/groups/{group_db_id}?msg=Grupo+atualizado",
        status_code=303,
    )


@router.post("/{group_db_id}/delete")
async def delete_group(group_db_id: int) -> RedirectResponse:
    repo = get_group_repo()
    try:
        repo.delete_group(group_db_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RedirectResponse(url="/groups?msg=Grupo+removido", status_code=303)


@router.get("/{group_db_id}/stores/new", response_class=HTMLResponse)
async def new_store_in_group(request: Request, group_db_id: int) -> HTMLResponse:
    group = get_group_repo().get_group(group_db_id)
    if not group:
        raise HTTPException(status_code=404, detail="Grupo não encontrado")
    templates = get_templates()
    return templates.TemplateResponse(
        request,
        "stores/form.html",
        {
            "group": group,
            "store": None,
            "action": f"/groups/{group_db_id}/stores",
        },
    )


@router.post("/{group_db_id}/stores")
async def create_store_in_group(
    group_db_id: int,
    store_id: str = Form(...),
    name: str = Form(...),
    street: str = Form(""),
    number: str = Form(""),
    neighborhood: str = Form(""),
    city: str = Form(""),
    state: str = Form(""),
    cep: str = Form(""),
    timezone: str = Form("America/Sao_Paulo"),
    ocr_sample_interval_sec: int = Form(30),
    ocr_min_confidence: float = Form(0.5),
    active: str | None = Form(None),
) -> RedirectResponse:
    group_repo = get_group_repo()
    group = group_repo.get_group(group_db_id)
    if not group:
        raise HTTPException(status_code=404, detail="Grupo não encontrado")

    store_repo = get_store_repo()
    if store_repo.get_store_by_code(store_id.strip(), group_db_id=group_db_id):
        raise HTTPException(
            status_code=400,
            detail="Código da loja já existe neste grupo",
        )

    store = store_repo.create_store(
        group_db_id=group_db_id,
        store_id=store_id,
        name=name,
        street=street,
        number=number,
        neighborhood=neighborhood,
        city=city,
        state=state,
        cep=cep,
        timezone=timezone,
        ocr_sample_interval_sec=ocr_sample_interval_sec,
        ocr_min_confidence=ocr_min_confidence,
        active=active == "on",
    )
    return RedirectResponse(
        url=f"/stores/{store.id}?msg=Loja+cadastrada",
        status_code=303,
    )
