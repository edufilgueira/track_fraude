from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, Field

from server.dependencies import get_store_repo, get_templates
from server.services.frame_extract import extract_frame_jpeg
from server.services.video_storage import raw_video_path, raw_video_relpath

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


def _jpeg_frame_response(
    jpeg: bytes,
    *,
    width: int,
    height: int,
    duration_sec: float,
    video_path: str | None = None,
) -> Response:
    headers = {
        "X-Frame-Width": str(width),
        "X-Frame-Height": str(height),
        "X-Video-Duration": str(round(duration_sec, 2)),
        "Cache-Control": "no-store",
    }
    if video_path:
        headers["X-Video-Path"] = video_path
    return Response(content=jpeg, media_type="image/jpeg", headers=headers)


def _extract_storage_frame(camera_id: str, date: str, seconds: float) -> Response:
    video_path = raw_video_path(date=date, camera_id=camera_id)
    if not video_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Vídeo não encontrado: {raw_video_relpath(date=date, camera_id=camera_id)}",
        )
    try:
        jpeg, width, height, duration_sec = extract_frame_jpeg(video_path, seconds=seconds)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _jpeg_frame_response(
        jpeg,
        width=width,
        height=height,
        duration_sec=duration_sec,
        video_path=raw_video_relpath(date=date, camera_id=camera_id),
    )


def _video_duration_sec(video_path: Path) -> float | None:
    import cv2

    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        return None
    try:
        fps = float(capture.get(cv2.CAP_PROP_FPS) or 0)
        total_frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        if fps > 0 and total_frames > 0:
            return round(total_frames / fps, 2)
    finally:
        capture.release()
    return None


@router.get("/{store_db_id}/cameras/{camera_db_id}/roi-editor", response_class=HTMLResponse)
async def roi_editor_page(
    request: Request,
    store_db_id: int,
    camera_db_id: int,
    date: str | None = Query(default=None, description="Data da gravação YYYY-MM-DD"),
) -> HTMLResponse:
    store, camera, _repo = _get_camera_or_404(store_db_id, camera_db_id)
    default_video_date = (date or "2026-05-22").strip()
    video_path = raw_video_path(date=default_video_date, camera_id=camera.camera_id)
    video_available = video_path.exists()
    video_duration = _video_duration_sec(video_path) if video_available else None
    templates = get_templates()
    return templates.TemplateResponse(
        request,
        "cameras/roi_editor.html",
        {
            "store": store,
            "camera": camera,
            "default_video_date": default_video_date,
            "video_available": video_available,
            "video_duration": video_duration,
            "video_relpath": raw_video_relpath(
                date=default_video_date, camera_id=camera.camera_id
            ),
        },
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

    return _jpeg_frame_response(jpeg, width=width, height=height, duration_sec=duration_sec)


@router.get("/{store_db_id}/cameras/{camera_db_id}/frame-preview")
async def frame_preview(
    store_db_id: int,
    camera_db_id: int,
    date: str = Query(..., description="YYYY-MM-DD"),
    seconds: float = Query(0.0, ge=0),
) -> Response:
    """Preview JPEG via URL (img src) — lê data/raw/video/{date}/{camera}.mp4."""
    _store, camera, _repo = _get_camera_or_404(store_db_id, camera_db_id)
    return _extract_storage_frame(camera.camera_id, date, seconds)


@router.post("/{store_db_id}/cameras/{camera_db_id}/frame-from-storage")
async def frame_from_storage(
    store_db_id: int,
    camera_db_id: int,
    date: str = Form(...),
    seconds: float = Form(0.0),
) -> Response:
    """Extrai frame de data/raw/video/{date}/{camera_id}.mp4 (sem upload)."""
    _store, camera, _repo = _get_camera_or_404(store_db_id, camera_db_id)
    return _extract_storage_frame(camera.camera_id, date, seconds)
