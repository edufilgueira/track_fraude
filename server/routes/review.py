from __future__ import annotations

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from server.auth import get_current_user_id
from server.dependencies import (
    get_group_repo,
    get_project_root,
    get_review_repo,
    get_store_repo,
    get_templates,
)
from server.services.review_loader import (
    get_alert_from_index,
    has_review_evidence,
    list_alert_media_files,
    list_review_dates,
    load_review_index,
    safe_review_media_path,
)
from track_fraude_core.db.review_repository import (
    REVIEW_STATUS_CONFIRMED,
    REVIEW_STATUS_DISMISSED,
    REVIEW_STATUS_PENDING,
)

router = APIRouter(prefix="/stores", tags=["review"])

REVIEW_STATUS_LABELS = {
    REVIEW_STATUS_PENDING: "Pendente",
    REVIEW_STATUS_CONFIRMED: "Confirmado",
    REVIEW_STATUS_DISMISSED: "Falso positivo",
}


def _load_store_context(store_db_id: int):
    store_repo = get_store_repo()
    store = store_repo.get_store(store_db_id)
    if not store:
        raise HTTPException(status_code=404, detail="Loja não encontrada")
    group = get_group_repo().get_group(store.group_db_id)
    if not group:
        raise HTTPException(status_code=404, detail="Grupo não encontrado")
    return store, group


def _format_rules(alert: dict) -> str:
    rule_ids = alert.get("rule_ids") or [alert.get("rule_id")]
    return ", ".join(str(rule_id) for rule_id in rule_ids if rule_id)


def _format_lane(alert: dict) -> str:
    session = alert.get("checkout_session") or {}
    lane = session.get("lane_id")
    return f"Caixa {lane}" if lane is not None else "—"


def _timeline_bounds(alert: dict) -> tuple[str, str]:
    timeline = alert.get("store_timeline") or []
    if not timeline:
        return "—", "—"
    times = [str(item.get("t", "")) for item in timeline if item.get("t")]
    if not times:
        return "—", "—"
    return times[0].replace("T", " ")[:19], times[-1].replace("T", " ")[:19]


@router.get("/{store_db_id}/review", response_class=HTMLResponse)
async def review_dates(request: Request, store_db_id: int) -> HTMLResponse:
    store, group = _load_store_context(store_db_id)
    project_root = get_project_root()
    dates = list_review_dates(project_root, store, group_code=group.group_code)

    if len(dates) == 1:
        return RedirectResponse(
            url=f"/stores/{store_db_id}/review/{dates[0]}",
            status_code=302,
        )

    templates = get_templates()
    return templates.TemplateResponse(
        request,
        "review/dates.html",
        {
            "store": store,
            "group": group,
            "dates": dates,
            "message": request.query_params.get("msg"),
        },
    )


@router.get("/{store_db_id}/review/{date}", response_class=HTMLResponse)
async def review_list(request: Request, store_db_id: int, date: str) -> HTMLResponse:
    store, group = _load_store_context(store_db_id)
    project_root = get_project_root()

    try:
        review_index = load_review_index(
            project_root, store, group_code=group.group_code, date=date
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    review_repo = get_review_repo()
    decisions = review_repo.list_decisions_for_date(store_db_id, date)
    alerts = []
    for alert in review_index.get("alerts") or []:
        alert_id = str(alert.get("alert_id"))
        decision = decisions.get(alert_id)
        status = decision.status if decision else REVIEW_STATUS_PENDING
        t_start, t_end = _timeline_bounds(alert)
        alerts.append(
            {
                "alert_id": alert_id,
                "rules": _format_rules(alert),
                "score": alert.get("suspicion_score"),
                "severity": alert.get("severity"),
                "lane": _format_lane(alert),
                "t_start": t_start,
                "t_end": t_end,
                "summary": alert.get("summary") or "",
                "review_status": status,
                "review_label": REVIEW_STATUS_LABELS.get(status, status),
            }
        )

    alerts.sort(key=lambda item: float(item["score"] or 0), reverse=True)

    templates = get_templates()
    return templates.TemplateResponse(
        request,
        "review/list.html",
        {
            "store": store,
            "group": group,
            "date": date,
            "alerts": alerts,
            "alert_count": len(alerts),
            "message": request.query_params.get("msg"),
        },
    )


@router.get("/{store_db_id}/review/{date}/{alert_id}", response_class=HTMLResponse)
async def review_detail(
    request: Request, store_db_id: int, date: str, alert_id: str
) -> HTMLResponse:
    store, group = _load_store_context(store_db_id)
    project_root = get_project_root()

    try:
        review_index = load_review_index(
            project_root, store, group_code=group.group_code, date=date
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    alert = get_alert_from_index(review_index, alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="Alerta não encontrado")

    review_repo = get_review_repo()
    decision = review_repo.get_decision(store_db_id, date, alert_id)
    current_status = decision.status if decision else REVIEW_STATUS_PENDING

    summary_path = (
        project_root
        / "data/processed"
        / group.group_code
        / store.store_id
        / date
        / "review"
        / alert_id
        / "summary.txt"
    )
    summary_text = ""
    if summary_path.is_file():
        summary_text = summary_path.read_text(encoding="utf-8")

    media_files = list_alert_media_files(alert)
    media_urls = {
        filename: f"/stores/{store_db_id}/review/{date}/media/{alert_id}/{filename}"
        for filename in media_files
    }

    templates = get_templates()
    return templates.TemplateResponse(
        request,
        "review/detail.html",
        {
            "store": store,
            "group": group,
            "date": date,
            "alert": alert,
            "alert_id": alert_id,
            "rules": _format_rules(alert),
            "lane": _format_lane(alert),
            "summary_text": summary_text,
            "media_urls": media_urls,
            "timeline_json": alert.get("store_timeline") or [],
            "pos_matches": alert.get("pos_matches") or [],
            "current_status": current_status,
            "current_note": decision.note if decision else "",
            "status_labels": REVIEW_STATUS_LABELS,
            "message": request.query_params.get("msg"),
        },
    )


@router.get("/{store_db_id}/review/{date}/media/{alert_id}/{filename}")
async def review_media(
    store_db_id: int, date: str, alert_id: str, filename: str
) -> FileResponse:
    store, group = _load_store_context(store_db_id)
    project_root = get_project_root()
    try:
        media_path = safe_review_media_path(
            project_root,
            store,
            group_code=group.group_code,
            date=date,
            alert_id=alert_id,
            filename=filename,
        )
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return FileResponse(
        path=str(media_path),
        media_type="video/mp4",
        content_disposition_type="inline",
    )


@router.post("/{store_db_id}/review/{date}/{alert_id}")
async def review_decision(
    request: Request,
    store_db_id: int,
    date: str,
    alert_id: str,
    status: str = Form(...),
    note: str = Form(""),
) -> RedirectResponse:
    if status not in {REVIEW_STATUS_CONFIRMED, REVIEW_STATUS_DISMISSED}:
        raise HTTPException(status_code=400, detail="Status inválido")

    _load_store_context(store_db_id)
    user_id = get_current_user_id(request)

    review_repo = get_review_repo()
    review_repo.save_decision(
        store_db_id=store_db_id,
        date=date,
        alert_id=alert_id,
        status=status,
        reviewer_user_id=user_id,
        note=note,
    )

    return RedirectResponse(
        url=f"/stores/{store_db_id}/review/{date}/{alert_id}?msg=Decisão+salva",
        status_code=303,
    )
