from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, Field

from server.dependencies import get_store_repo, get_templates
from server.services.frame_extract import extract_frame_jpeg

router = APIRouter(prefix="/stores", tags=["cameras"])

MAX_UPLOAD_BYTES = 500 * 1024 * 1024
ALLOWED_EXTENSIONS = {".mp4", ".avi", ".mkv", ".mov", ".webm", ".m4v"}


class RoiPayload(BaseModel):
    ocr_x: int = Field(ge=0)
    ocr_y: int = Field(ge=0)
    ocr_width: int = Field(ge=1)
    ocr_height: int = Field(ge=1)


def _get_camera_or_404(store_db_id: int, camera_db_id: int):
    repo = get_store_repo()
    store = repo.get_store(store_db_id)
    camera = repo.get_camera(camera_db_id)
    if not store or not camera or camera.store_db_id != store_db_id:
        raise HTTPException(status_code=404, detail="Câmera não encontrada")
    return store, camera, repo


@router.get("/{store_db_id}/cameras/{camera_db_id}/roi-editor", response_class=HTMLResponse)
async def roi_editor_page(
    request: Request,
    store_db_id: int,
    camera_db_id: int,
) -> HTMLResponse:
    store, camera, _repo = _get_camera_or_404(store_db_id, camera_db_id)
    templates = get_templates()
    return templates.TemplateResponse(
        request,
        "cameras/roi_editor.html",
        {"store": store, "camera": camera},
    )


@router.post("/{store_db_id}/cameras/{camera_db_id}/roi")
async def save_camera_roi(
    store_db_id: int,
    camera_db_id: int,
    payload: RoiPayload,
) -> JSONResponse:
    _store, _camera, repo = _get_camera_or_404(store_db_id, camera_db_id)
    updated = repo.update_camera(
        camera_db_id,
        ocr_x=payload.ocr_x,
        ocr_y=payload.ocr_y,
        ocr_width=payload.ocr_width,
        ocr_height=payload.ocr_height,
    )
    assert updated is not None
    return JSONResponse(
        {
            "ok": True,
            "roi": {
                "ocr_x": updated.ocr_x,
                "ocr_y": updated.ocr_y,
                "ocr_width": updated.ocr_width,
                "ocr_height": updated.ocr_height,
            },
        }
    )


@router.post("/{store_db_id}/cameras/{camera_db_id}/frame-upload")
async def upload_camera_frame(
    store_db_id: int,
    camera_db_id: int,
    video: UploadFile = File(...),
    seconds: float = Form(0.0),
) -> Response:
    """Extrai frame no servidor (fallback para codecs que o navegador não reproduz)."""
    _get_camera_or_404(store_db_id, camera_db_id)

    suffix = Path(video.filename or "video.mp4").suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Formato de vídeo não suportado")

    content = await video.read()
    if not content:
        raise HTTPException(status_code=400, detail="Arquivo vazio")
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Arquivo maior que 500 MB")

    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix or ".mp4", delete=False) as tmp:
            tmp.write(content)
            tmp_path = Path(tmp.name)

        jpeg, width, height, duration_sec = extract_frame_jpeg(tmp_path, seconds=seconds)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)

    return Response(
        content=jpeg,
        media_type="image/jpeg",
        headers={
            "X-Frame-Width": str(width),
            "X-Frame-Height": str(height),
            "X-Video-Duration": str(round(duration_sec, 2)),
            "Cache-Control": "no-store",
        },
    )
