from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from edge_controller import crud
from edge_controller.database import get_db
from edge_controller.models import ConfigRevision
from edge_controller.schemas import ConfigActionResult, ConfigRevisionRead, ProxyRouteCreate, ProxyRouteRead, ProxyRouteUpdate
from edge_controller.services.caddy_manager import apply_routes, get_system_status, render_current_routes, rollback_to_revision, validate_routes

router = APIRouter(prefix="/api")


@router.get("/proxy-routes", response_model=list[ProxyRouteRead])
def list_routes(db: Session = Depends(get_db)) -> list[ProxyRouteRead]:
    return crud.list_proxy_routes(db)


@router.post("/proxy-routes", response_model=ProxyRouteRead, status_code=status.HTTP_201_CREATED)
def create_route(payload: ProxyRouteCreate, db: Session = Depends(get_db)) -> ProxyRouteRead:
    try:
        return crud.create_proxy_route(db, payload)
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="route name or domain already exists") from exc


@router.put("/proxy-routes/{route_id}", response_model=ProxyRouteRead)
def update_route(route_id: int, payload: ProxyRouteUpdate, db: Session = Depends(get_db)) -> ProxyRouteRead:
    route = crud.get_proxy_route(db, route_id)
    if route is None:
        raise HTTPException(status_code=404, detail="proxy route not found")
    try:
        return crud.update_proxy_route(db, route, payload)
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="route name or domain already exists") from exc


@router.delete("/proxy-routes/{route_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_route(route_id: int, db: Session = Depends(get_db)) -> Response:
    route = crud.get_proxy_route(db, route_id)
    if route is None:
        raise HTTPException(status_code=404, detail="proxy route not found")
    crud.delete_proxy_route(db, route)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/dns-records")
def list_dns_records(db: Session = Depends(get_db)) -> list[dict[str, object]]:
    return [
        {
            "id": record.id,
            "name": record.name,
            "fqdn": record.fqdn,
            "record_type": record.record_type,
            "value": record.value,
            "ttl": record.ttl,
            "enabled": record.enabled,
            "sync_status": record.sync_status,
        }
        for record in crud.list_dns_records(db)
    ]


@router.post("/config/render")
def render_config(db: Session = Depends(get_db)) -> dict[str, str]:
    return {"config": render_current_routes(db)}


@router.post("/config/validate", response_model=ConfigActionResult)
def validate_config(db: Session = Depends(get_db)) -> ConfigActionResult:
    return ConfigActionResult(**validate_routes(db).__dict__)


@router.post("/config/apply", response_model=ConfigActionResult)
def apply_config(db: Session = Depends(get_db)) -> ConfigActionResult:
    return ConfigActionResult(**apply_routes(db).__dict__)


@router.post("/config/rollback/{revision_id}", response_model=ConfigActionResult)
def rollback_config(revision_id: int, db: Session = Depends(get_db)) -> ConfigActionResult:
    return ConfigActionResult(**rollback_to_revision(db, revision_id).__dict__)


@router.get("/system/status")
def system_status(db: Session = Depends(get_db)) -> dict[str, object]:
    status_info = get_system_status(db)
    return {
        "status": status_info.status,
        "dirty": status_info.dirty,
        "desired_checksum": status_info.desired_checksum,
        "last_applied_at": status_info.last_applied_at,
        "last_applied_revision_id": status_info.last_applied_revision_id,
        "message": status_info.message,
    }


@router.get("/config/revisions", response_model=list[ConfigRevisionRead])
def list_revisions(db: Session = Depends(get_db)) -> list[ConfigRevision]:
    return list(db.query(ConfigRevision).order_by(ConfigRevision.id.desc()).limit(25))
