from __future__ import annotations

from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from edge_controller import crud
from edge_controller.config import get_settings
from edge_controller.database import get_db
from edge_controller.models import ConfigRevision
from edge_controller.schemas import ProxyRouteCreate, ProxyRouteUpdate
from edge_controller.services.caddy_manager import apply_routes, get_system_status, rollback_to_revision, validate_routes

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parents[1] / "templates"))


@router.get("/", response_class=HTMLResponse)
def index() -> RedirectResponse:
    return RedirectResponse(url="/proxy-routes", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/proxy-routes", response_class=HTMLResponse)
def proxy_routes(
    request: Request,
    edit_id: int | None = Query(default=None),
    message: str | None = Query(default=None),
    error: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    edit_route = crud.get_proxy_route(db, edit_id) if edit_id is not None else None
    return templates.TemplateResponse(
        request,
        "proxy_routes.html",
        {
            "active_tab": "proxy",
            "routes": crud.list_proxy_routes(db),
            "edit_route": edit_route,
            "status": get_system_status(db),
            "revisions": _recent_revisions(db),
            "message": message,
            "error": error,
        },
    )


@router.post("/proxy-routes")
def create_proxy_route(
    name: str = Form(...),
    domain: str = Form(...),
    target_scheme: str = Form(...),
    target_host: str = Form(...),
    target_port: int = Form(...),
    tls_insecure_skip_verify: bool = Form(False),
    enabled: bool = Form(False),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    try:
        payload = ProxyRouteCreate(
            name=name,
            domain=domain,
            target_scheme=target_scheme,
            target_host=target_host,
            target_port=target_port,
            tls_insecure_skip_verify=tls_insecure_skip_verify,
            enabled=enabled,
        )
        crud.create_proxy_route(db, payload)
    except (ValidationError, IntegrityError) as exc:
        return _redirect("/proxy-routes", error=_friendly_error(exc))
    return _redirect("/proxy-routes", message="Proxy route created.")


@router.post("/proxy-routes/{route_id}")
def update_proxy_route(
    route_id: int,
    name: str = Form(...),
    domain: str = Form(...),
    target_scheme: str = Form(...),
    target_host: str = Form(...),
    target_port: int = Form(...),
    tls_insecure_skip_verify: bool = Form(False),
    enabled: bool = Form(False),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    route = crud.get_proxy_route(db, route_id)
    if route is None:
        raise HTTPException(status_code=404, detail="proxy route not found")
    try:
        payload = ProxyRouteUpdate(
            name=name,
            domain=domain,
            target_scheme=target_scheme,
            target_host=target_host,
            target_port=target_port,
            tls_insecure_skip_verify=tls_insecure_skip_verify,
            enabled=enabled,
        )
        crud.update_proxy_route(db, route, payload)
    except (ValidationError, IntegrityError) as exc:
        return _redirect(f"/proxy-routes?edit_id={route_id}", error=_friendly_error(exc))
    return _redirect("/proxy-routes", message="Proxy route updated.")


@router.post("/proxy-routes/{route_id}/toggle")
def toggle_proxy_route(route_id: int, db: Session = Depends(get_db)) -> RedirectResponse:
    route = crud.get_proxy_route(db, route_id)
    if route is None:
        raise HTTPException(status_code=404, detail="proxy route not found")
    crud.toggle_proxy_route(db, route)
    return _redirect("/proxy-routes", message="Proxy route toggled.")


@router.post("/proxy-routes/{route_id}/delete")
def delete_proxy_route(route_id: int, db: Session = Depends(get_db)) -> RedirectResponse:
    route = crud.get_proxy_route(db, route_id)
    if route is None:
        raise HTTPException(status_code=404, detail="proxy route not found")
    crud.delete_proxy_route(db, route)
    return _redirect("/proxy-routes", message="Proxy route deleted.")


@router.get("/dns-records", response_class=HTMLResponse)
def dns_records(
    request: Request,
    message: str | None = Query(default=None),
    error: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    settings = get_settings()
    return templates.TemplateResponse(
        request,
        "dns_records.html",
        {
            "active_tab": "dns",
            "status": get_system_status(db),
            "records": crud.list_dns_records(db),
            "dns_zone": settings.dns_zone,
            "dns_wildcard": settings.dns_wildcard,
            "edge_ip": settings.edge_ip,
            "technitium_status": settings.technitium_status,
            "message": message,
            "error": error,
        },
    )


@router.post("/config/validate")
def validate_config(db: Session = Depends(get_db)) -> RedirectResponse:
    result = validate_routes(db)
    key = "message" if result.ok else "error"
    return _redirect("/proxy-routes", **{key: result.message})


@router.post("/config/apply")
def apply_config(db: Session = Depends(get_db)) -> RedirectResponse:
    result = apply_routes(db)
    key = "message" if result.ok else "error"
    return _redirect("/proxy-routes", **{key: result.message})


@router.post("/config/rollback/{revision_id}")
def rollback_config(revision_id: int, db: Session = Depends(get_db)) -> RedirectResponse:
    result = rollback_to_revision(db, revision_id)
    key = "message" if result.ok else "error"
    return _redirect("/proxy-routes", **{key: result.message})


def _recent_revisions(db: Session) -> list[ConfigRevision]:
    return list(db.query(ConfigRevision).order_by(ConfigRevision.id.desc()).limit(8))


def _redirect(path: str, **params: str) -> RedirectResponse:
    clean = {key: value for key, value in params.items() if value}
    target = f"{path}?{urlencode(clean)}" if clean else path
    return RedirectResponse(url=target, status_code=status.HTTP_303_SEE_OTHER)


def _friendly_error(exc: Exception) -> str:
    if isinstance(exc, IntegrityError):
        return "Route name or domain already exists."
    if isinstance(exc, ValidationError):
        return "; ".join(error["msg"] for error in exc.errors())
    return str(exc)
