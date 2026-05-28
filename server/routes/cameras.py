from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, Field

from server.dependencies import get_store_repo, get_templates
from server.services.editor_frame_storage import (
    editor_frame_exists,
    editor_frame_jpeg_path,
    editor_frame_url,
    load_editor_frame_meta,
    save_editor_frame,
)
from server.services.frame_extract import extract_frame_jpeg
from server.services.video_storage import copy_raw_video, raw_video_path, raw_video_relpath
from track_fraude_core.db.camera_roles import (
    CAMERA_ROLE_CHECKOUT,
    CAMERA_ROLE_ENTRANCE,
    CAMERA_ROLE_LABELS,
)

router = APIRouter(prefix="/stores", tags=["cameras"])

MAX_UPLOAD_BYTES = 500 * 1024 * 1024
ALLOWED_EXTENSIONS = {".mp4", ".avi", ".mkv", ".mov", ".webm", ".m4v"}


class RoiPayload(BaseModel):
    ocr_x: int = Field(ge=0)
    ocr_y: int = Field(ge=0)
    ocr_width: int = Field(ge=1)
    ocr_height: int = Field(ge=1)


class ZonePayload(BaseModel):
    zone_type: str
    zone_id: str
    polygon: list[list[float]]
    label: str = ""
    lane_id: int | None = None
    entry_vector: list[float] | None = None


class EntryVectorPayload(BaseModel):
    zone_id: str
    entry_vector: list[float]


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
    editor_frame_url_value: str | None = None,
) -> Response:
    headers = {
        "X-Frame-Width": str(width),
        "X-Frame-Height": str(height),
        "X-Video-Duration": str(round(duration_sec, 2)),
        "Cache-Control": "no-store",
    }
    if video_path:
        headers["X-Video-Path"] = video_path
    if editor_frame_url_value:
        headers["X-Editor-Frame-Url"] = editor_frame_url_value
        headers["X-Editor-Frame-Saved"] = "true"
    return Response(content=jpeg, media_type="image/jpeg", headers=headers)


def _editor_frame_page_context(store_db_id: int, camera_db_id: int, camera_id: str) -> dict:
    saved = editor_frame_exists(
        store_db_id=store_db_id,
        camera_db_id=camera_db_id,
        camera_id=camera_id,
    )
    meta = (
        load_editor_frame_meta(
            store_db_id=store_db_id,
            camera_db_id=camera_db_id,
            camera_id=camera_id,
        )
        if saved
        else None
    )
    return {
        "saved_frame_available": saved,
        "saved_frame_url": editor_frame_url(store_db_id=store_db_id, camera_db_id=camera_db_id)
        if saved
        else None,
        "saved_frame_meta": meta,
    }


def _persist_editor_frame(
    *,
    store_db_id: int,
    camera_db_id: int,
    camera_id: str,
    jpeg: bytes,
    width: int,
    height: int,
    duration_sec: float,
    source: str,
    video_date: str | None = None,
    seconds: float | None = None,
    video_relpath: str | None = None,
) -> Response:
    save_editor_frame(
        store_db_id=store_db_id,
        camera_db_id=camera_db_id,
        camera_id=camera_id,
        jpeg=jpeg,
        width=width,
        height=height,
        source=source,
        video_date=video_date,
        seconds=seconds,
        video_relpath=video_relpath,
        duration_sec=duration_sec,
    )

    return _jpeg_frame_response(
        jpeg,
        width=width,
        height=height,
        duration_sec=duration_sec,
        video_path=video_relpath,
        editor_frame_url_value=editor_frame_url(
            store_db_id=store_db_id, camera_db_id=camera_db_id
        ),
    )


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
            **_editor_frame_page_context(store_db_id, camera_db_id, camera.camera_id),
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
    date: str | None = Form(default=None),
) -> Response:
    """Extrai frame no servidor (fallback para codecs que o navegador não reproduz)."""
    _store, camera, _repo = _get_camera_or_404(store_db_id, camera_db_id)

    suffix = Path(video.filename or "video.mp4").suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Formato de vídeo não suportado")

    content = await video.read()
    if not content:
        raise HTTPException(status_code=400, detail="Arquivo vazio")
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Arquivo maior que 500 MB")

    video_date = date.strip() if date else None
    video_relpath: str | None = None

    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix or ".mp4", delete=False) as tmp:
            tmp.write(content)
            tmp_path = Path(tmp.name)

        jpeg, width, height, duration_sec = extract_frame_jpeg(tmp_path, seconds=seconds)

        if video_date:
            copy_raw_video(date=video_date, camera_id=camera.camera_id, source=tmp_path)
            video_relpath = raw_video_relpath(date=video_date, camera_id=camera.camera_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)

    return _persist_editor_frame(
        store_db_id=store_db_id,
        camera_db_id=camera_db_id,
        camera_id=camera.camera_id,
        jpeg=jpeg,
        width=width,
        height=height,
        duration_sec=duration_sec,
        source="upload",
        video_date=video_date,
        seconds=seconds,
        video_relpath=video_relpath,
    )


@router.get("/{store_db_id}/cameras/{camera_db_id}/editor-frame")
async def get_editor_frame(
    store_db_id: int,
    camera_db_id: int,
) -> Response:
    """Frame JPEG persistido no servidor (acessível de qualquer dispositivo)."""
    _store, camera, _repo = _get_camera_or_404(store_db_id, camera_db_id)
    if not editor_frame_exists(
        store_db_id=store_db_id,
        camera_db_id=camera_db_id,
        camera_id=camera.camera_id,
    ):
        raise HTTPException(status_code=404, detail="Nenhum frame salvo para esta câmera")
    jpeg_path = editor_frame_jpeg_path(
        store_db_id=store_db_id, camera_db_id=camera_db_id
    )
    jpeg = jpeg_path.read_bytes()
    meta = load_editor_frame_meta(
        store_db_id=store_db_id,
        camera_db_id=camera_db_id,
        camera_id=camera.camera_id,
    ) or {}
    return _jpeg_frame_response(
        jpeg,
        width=int(meta.get("width") or 0),
        height=int(meta.get("height") or 0),
        duration_sec=float(meta.get("duration_sec") or 0),
        editor_frame_url_value=editor_frame_url(
            store_db_id=store_db_id, camera_db_id=camera_db_id
        ),
    )


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
    """Extrai frame do vídeo local e salva no servidor (o MP4 original é mantido)."""
    _store, camera, _repo = _get_camera_or_404(store_db_id, camera_db_id)
    video_path = raw_video_path(date=date, camera_id=camera.camera_id)
    if not video_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Vídeo não encontrado: {raw_video_relpath(date=date, camera_id=camera.camera_id)}",
        )
    try:
        jpeg, width, height, duration_sec = extract_frame_jpeg(video_path, seconds=seconds)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    relpath = raw_video_relpath(date=date, camera_id=camera.camera_id)
    return _persist_editor_frame(
        store_db_id=store_db_id,
        camera_db_id=camera_db_id,
        camera_id=camera.camera_id,
        jpeg=jpeg,
        width=width,
        height=height,
        duration_sec=duration_sec,
        source="storage",
        video_date=date.strip(),
        seconds=seconds,
        video_relpath=relpath,
    )


def _zones_for_response(repo, camera_db_id: int) -> list[dict]:
    return [zone.to_dict() for zone in repo.list_camera_zones(camera_db_id)]


@router.get("/{store_db_id}/cameras/{camera_db_id}/zone-editor", response_class=HTMLResponse)
async def zone_editor_page(
    request: Request,
    store_db_id: int,
    camera_db_id: int,
    date: str | None = Query(default=None, description="Data da gravação YYYY-MM-DD"),
) -> HTMLResponse:
    store, camera, repo = _get_camera_or_404(store_db_id, camera_db_id)
    if camera.camera_role not in {CAMERA_ROLE_ENTRANCE, CAMERA_ROLE_CHECKOUT}:
        raise HTTPException(
            status_code=400,
            detail="Editor de zona disponível apenas para câmeras Entrada ou Caixa.",
        )

    default_video_date = (date or "2026-05-22").strip()
    video_path = raw_video_path(date=default_video_date, camera_id=camera.camera_id)
    video_available = video_path.exists()
    video_duration = _video_duration_sec(video_path) if video_available else None
    templates = get_templates()
    return templates.TemplateResponse(
        request,
        "cameras/zone_editor.html",
        {
            "store": store,
            "camera": camera,
            "role_label": CAMERA_ROLE_LABELS.get(camera.camera_role, camera.camera_role),
            "default_video_date": default_video_date,
            "video_available": video_available,
            "video_duration": video_duration,
            "video_relpath": raw_video_relpath(
                date=default_video_date, camera_id=camera.camera_id
            ),
            "existing_zones": _zones_for_response(repo, camera_db_id),
            **_editor_frame_page_context(store_db_id, camera_db_id, camera.camera_id),
        },
    )


@router.get("/{store_db_id}/cameras/{camera_db_id}/zones")
async def list_camera_zones(
    store_db_id: int,
    camera_db_id: int,
) -> JSONResponse:
    _store, _camera, repo = _get_camera_or_404(store_db_id, camera_db_id)
    return JSONResponse({"zones": _zones_for_response(repo, camera_db_id)})


@router.post("/{store_db_id}/cameras/{camera_db_id}/zones")
async def save_camera_zone(
    store_db_id: int,
    camera_db_id: int,
    payload: ZonePayload,
) -> JSONResponse:
    _store, camera, repo = _get_camera_or_404(store_db_id, camera_db_id)

    if camera.camera_role == CAMERA_ROLE_ENTRANCE and payload.zone_type != "portal":
        raise HTTPException(status_code=400, detail="Câmera Entrada usa zone_type=portal")
    if camera.camera_role == CAMERA_ROLE_CHECKOUT and payload.zone_type != "checkout_lane":
        raise HTTPException(
            status_code=400, detail="Câmera Caixa usa zone_type=checkout_lane"
        )
    if payload.zone_type == "checkout_lane" and payload.lane_id is None:
        raise HTTPException(status_code=400, detail="Informe lane_id para checkout")

    if len(payload.polygon) < 3:
        raise HTTPException(status_code=400, detail="Polígono precisa de ≥ 3 pontos")

    zone = repo.save_camera_zone(
        camera_db_id=camera_db_id,
        zone_type=payload.zone_type.strip(),
        zone_id=payload.zone_id.strip(),
        polygon=payload.polygon,
        label=payload.label.strip(),
        lane_id=payload.lane_id,
        entry_vector=payload.entry_vector,
        sort_order=payload.lane_id or 0,
    )
    return JSONResponse({"ok": True, "zone": zone.to_dict()})


@router.post("/{store_db_id}/cameras/{camera_db_id}/zones/entry-vector")
async def save_zone_entry_vector(
    store_db_id: int,
    camera_db_id: int,
    payload: EntryVectorPayload,
) -> JSONResponse:
    _store, camera, repo = _get_camera_or_404(store_db_id, camera_db_id)
    if camera.camera_role != CAMERA_ROLE_ENTRANCE:
        raise HTTPException(status_code=400, detail="Sentido de entrada só para câmera Entrada")

    zones = repo.list_camera_zones(camera_db_id)
    target = next((z for z in zones if z.zone_id == payload.zone_id.strip()), None)
    if target is None:
        raise HTTPException(status_code=404, detail="Zona portal não encontrada")

    if len(payload.entry_vector) != 2:
        raise HTTPException(status_code=400, detail="entry_vector deve ter 2 valores")

    zone = repo.save_camera_zone(
        camera_db_id=camera_db_id,
        zone_type=target.zone_type,
        zone_id=target.zone_id,
        polygon=target.polygon,
        label=target.label,
        lane_id=target.lane_id,
        entry_vector=[float(payload.entry_vector[0]), float(payload.entry_vector[1])],
        sort_order=0,
    )
    return JSONResponse({"ok": True, "zone": zone.to_dict()})


@router.delete("/{store_db_id}/cameras/{camera_db_id}/zones/{zone_id}")
async def delete_camera_zone(
    store_db_id: int,
    camera_db_id: int,
    zone_id: str,
) -> JSONResponse:
    _get_camera_or_404(store_db_id, camera_db_id)
    repo = get_store_repo()
    repo.delete_camera_zone(camera_db_id, zone_id)
    return JSONResponse({"ok": True})
