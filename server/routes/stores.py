from __future__ import annotations

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from server.dependencies import get_group_repo, get_store_repo, get_templates
from track_fraude_core.db.camera_roles import CAMERA_ROLE_LABELS, CAMERA_ROLE_SUPPORT

router = APIRouter(prefix="/stores", tags=["stores"])


@router.get("", response_class=HTMLResponse)
async def list_stores_redirect() -> RedirectResponse:
    return RedirectResponse(url="/groups", status_code=302)


@router.get("/new", response_class=HTMLResponse)
async def new_store_redirect() -> RedirectResponse:
    return RedirectResponse(url="/groups?msg=Cadastre+lojas+dentro+de+um+grupo", status_code=302)


@router.get("/{store_db_id}", response_class=HTMLResponse)
async def store_detail(request: Request, store_db_id: int) -> HTMLResponse:
    store_repo = get_store_repo()
    store = store_repo.get_store(store_db_id)
    if not store:
        raise HTTPException(status_code=404, detail="Loja não encontrada")

    group = get_group_repo().get_group(store.group_db_id)
    cameras = store_repo.list_cameras(store_db_id)
    templates = get_templates()
    return templates.TemplateResponse(
        request,
        "stores/detail.html",
        {
            "store": store,
            "group": group,
            "cameras": cameras,
            "role_labels": CAMERA_ROLE_LABELS,
            "message": request.query_params.get("msg"),
        },
    )


@router.get("/{store_db_id}/rules", response_class=HTMLResponse)
async def store_rules_form(request: Request, store_db_id: int) -> HTMLResponse:
    store_repo = get_store_repo()
    store = store_repo.get_store(store_db_id)
    if not store:
        raise HTTPException(status_code=404, detail="Loja não encontrada")

    group = get_group_repo().get_group(store.group_db_id)
    templates = get_templates()
    return templates.TemplateResponse(
        request,
        "stores/rules.html",
        {
            "store": store,
            "group": group,
            "message": request.query_params.get("msg"),
        },
    )


@router.post("/{store_db_id}/rules")
async def update_store_rules(
    store_db_id: int,
    r1_min_checkout_duration_sec: float = Form(...),
    pos_match_delta_sec: int = Form(...),
    t_return_sec: float = Form(...),
    carry_confidence_threshold: float = Form(...),
    r3_visual_margin: int = Form(...),
    r4_min_items: int = Form(...),
    r4_fast_duration_sec: float = Form(...),
    r5_cancelled_delta_sec: int = Form(...),
    vid_stride: int = Form(...),
    buffer_before_sec: float = Form(...),
    buffer_after_sec: float = Form(...),
    checkout_buffer_before_sec: float = Form(...),
    checkout_buffer_after_sec: float = Form(...),
    enable_r4: str | None = Form(None),
) -> RedirectResponse:
    store_repo = get_store_repo()
    store = store_repo.get_store(store_db_id)
    if not store:
        raise HTTPException(status_code=404, detail="Loja não encontrada")

    if not (1 <= r1_min_checkout_duration_sec <= 3600):
        raise HTTPException(status_code=400, detail="Tempo mínimo R1 inválido (1–3600 s)")
    if pos_match_delta_sec < 0:
        raise HTTPException(status_code=400, detail="Delta POS inválido")
    if not (0 <= carry_confidence_threshold <= 1):
        raise HTTPException(status_code=400, detail="Confiança visual inválida (0–1)")
    if not (1 <= vid_stride <= 60):
        raise HTTPException(status_code=400, detail="vid_stride inválido (1–60)")

    store_repo.update_store(
        store_db_id,
        r1_min_checkout_duration_sec=float(r1_min_checkout_duration_sec),
        pos_match_delta_sec=int(pos_match_delta_sec),
        t_return_sec=float(t_return_sec),
        carry_confidence_threshold=float(carry_confidence_threshold),
        r3_visual_margin=int(r3_visual_margin),
        r4_min_items=int(r4_min_items),
        r4_fast_duration_sec=float(r4_fast_duration_sec),
        r5_cancelled_delta_sec=int(r5_cancelled_delta_sec),
        vid_stride=int(vid_stride),
        buffer_before_sec=float(buffer_before_sec),
        buffer_after_sec=float(buffer_after_sec),
        checkout_buffer_before_sec=float(checkout_buffer_before_sec),
        checkout_buffer_after_sec=float(checkout_buffer_after_sec),
        enable_r4=enable_r4 == "on",
    )
    return RedirectResponse(
        url=f"/stores/{store_db_id}/rules?msg=Regras+atualizadas",
        status_code=303,
    )


@router.get("/{store_db_id}/edit", response_class=HTMLResponse)
async def edit_store_form(request: Request, store_db_id: int) -> HTMLResponse:
    store_repo = get_store_repo()
    store = store_repo.get_store(store_db_id)
    if not store:
        raise HTTPException(status_code=404, detail="Loja não encontrada")

    group = get_group_repo().get_group(store.group_db_id)
    templates = get_templates()
    return templates.TemplateResponse(
        request,
        "stores/form.html",
        {
            "group": group,
            "store": store,
            "action": f"/stores/{store_db_id}/edit",
        },
    )


@router.post("/{store_db_id}/edit")
async def update_store(
    store_db_id: int,
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
    store_repo = get_store_repo()
    store = store_repo.get_store(store_db_id)
    if not store:
        raise HTTPException(status_code=404, detail="Loja não encontrada")

    existing = store_repo.get_store_by_code(
        store_id.strip(),
        group_db_id=store.group_db_id,
    )
    if existing and existing.id != store_db_id:
        raise HTTPException(status_code=400, detail="Código da loja já em uso neste grupo")

    store_repo.update_store(
        store_db_id,
        store_id=store_id.strip(),
        name=name.strip(),
        street=street,
        number=number,
        neighborhood=neighborhood,
        city=city,
        state=state,
        cep=cep,
        timezone=timezone.strip(),
        ocr_sample_interval_sec=ocr_sample_interval_sec,
        ocr_min_confidence=ocr_min_confidence,
        active=active == "on",
    )
    return RedirectResponse(
        url=f"/stores/{store_db_id}?msg=Loja+atualizada",
        status_code=303,
    )


@router.post("/{store_db_id}/delete")
async def delete_store(store_db_id: int) -> RedirectResponse:
    store_repo = get_store_repo()
    store = store_repo.get_store(store_db_id)
    if not store:
        raise HTTPException(status_code=404, detail="Loja não encontrada")
    group_id = store.group_db_id
    store_repo.delete_store(store_db_id)
    return RedirectResponse(
        url=f"/groups/{group_id}?msg=Loja+removida",
        status_code=303,
    )


@router.get("/{store_db_id}/cameras/new", response_class=HTMLResponse)
async def new_camera_form(request: Request, store_db_id: int) -> HTMLResponse:
    store_repo = get_store_repo()
    store = store_repo.get_store(store_db_id)
    if not store:
        raise HTTPException(status_code=404, detail="Loja não encontrada")
    templates = get_templates()
    return templates.TemplateResponse(
        request,
        "cameras/form.html",
        {
            "store": store,
            "camera": None,
            "action": f"/stores/{store_db_id}/cameras",
            "role_labels": CAMERA_ROLE_LABELS,
            "default_role": CAMERA_ROLE_SUPPORT,
        },
    )


@router.post("/{store_db_id}/cameras")
async def create_camera(
    store_db_id: int,
    camera_id: str = Form(...),
    description: str = Form(""),
    camera_role: str = Form(CAMERA_ROLE_SUPPORT),
    ocr_x: int = Form(10),
    ocr_y: int = Form(10),
    ocr_width: int = Form(420),
    ocr_height: int = Form(50),
) -> RedirectResponse:
    store_repo = get_store_repo()
    store = store_repo.get_store(store_db_id)
    if not store:
        raise HTTPException(status_code=404, detail="Loja não encontrada")
    store_repo.create_camera(
        store_db_id=store_db_id,
        camera_id=camera_id,
        description=description,
        camera_role=camera_role,
        ocr_x=ocr_x,
        ocr_y=ocr_y,
        ocr_width=ocr_width,
        ocr_height=ocr_height,
    )
    return RedirectResponse(
        url=f"/stores/{store_db_id}?msg=Câmera+cadastrada",
        status_code=303,
    )


@router.get("/{store_db_id}/cameras/{camera_db_id}/edit", response_class=HTMLResponse)
async def edit_camera_form(
    request: Request,
    store_db_id: int,
    camera_db_id: int,
) -> HTMLResponse:
    store_repo = get_store_repo()
    store = store_repo.get_store(store_db_id)
    camera = store_repo.get_camera(camera_db_id)
    if not store or not camera or camera.store_db_id != store_db_id:
        raise HTTPException(status_code=404, detail="Câmera não encontrada")
    templates = get_templates()
    return templates.TemplateResponse(
        request,
        "cameras/form.html",
        {
            "store": store,
            "camera": camera,
            "action": f"/stores/{store_db_id}/cameras/{camera_db_id}/edit",
            "role_labels": CAMERA_ROLE_LABELS,
            "default_role": CAMERA_ROLE_SUPPORT,
        },
    )


@router.post("/{store_db_id}/cameras/{camera_db_id}/edit")
async def update_camera(
    store_db_id: int,
    camera_db_id: int,
    camera_id: str = Form(...),
    description: str = Form(""),
    camera_role: str = Form(CAMERA_ROLE_SUPPORT),
    ocr_x: int = Form(10),
    ocr_y: int = Form(10),
    ocr_width: int = Form(420),
    ocr_height: int = Form(50),
) -> RedirectResponse:
    store_repo = get_store_repo()
    camera = store_repo.get_camera(camera_db_id)
    if not camera or camera.store_db_id != store_db_id:
        raise HTTPException(status_code=404, detail="Câmera não encontrada")
    store_repo.update_camera(
        camera_db_id,
        camera_id=camera_id.strip(),
        description=description.strip(),
        camera_role=camera_role,
        ocr_x=ocr_x,
        ocr_y=ocr_y,
        ocr_width=ocr_width,
        ocr_height=ocr_height,
    )
    return RedirectResponse(
        url=f"/stores/{store_db_id}?msg=Câmera+atualizada",
        status_code=303,
    )


@router.post("/{store_db_id}/cameras/{camera_db_id}/delete")
async def delete_camera(store_db_id: int, camera_db_id: int) -> RedirectResponse:
    store_repo = get_store_repo()
    camera = store_repo.get_camera(camera_db_id)
    if not camera or camera.store_db_id != store_db_id:
        raise HTTPException(status_code=404, detail="Câmera não encontrada")
    store_repo.delete_camera(camera_db_id)
    return RedirectResponse(
        url=f"/stores/{store_db_id}?msg=Câmera+removida",
        status_code=303,
    )
