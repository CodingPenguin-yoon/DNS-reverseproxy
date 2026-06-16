from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from edge_controller.models import DnsRecord, ProxyRoute
from edge_controller.schemas import ProxyRouteCreate, ProxyRouteUpdate
from edge_controller.services.audit import record_audit


def list_proxy_routes(db: Session) -> list[ProxyRoute]:
    return list(db.scalars(select(ProxyRoute).order_by(ProxyRoute.domain)))


def get_proxy_route(db: Session, route_id: int) -> ProxyRoute | None:
    return db.get(ProxyRoute, route_id)


def create_proxy_route(db: Session, payload: ProxyRouteCreate) -> ProxyRoute:
    route = ProxyRoute(**payload.model_dump())
    db.add(route)
    _commit_or_raise(db)
    record_audit(db, action="create", target_type="proxy_route", target_id=route.id, status="ok")
    db.commit()
    db.refresh(route)
    return route


def update_proxy_route(db: Session, route: ProxyRoute, payload: ProxyRouteUpdate) -> ProxyRoute:
    for field, value in payload.model_dump().items():
        setattr(route, field, value)
    _commit_or_raise(db)
    record_audit(db, action="update", target_type="proxy_route", target_id=route.id, status="ok")
    db.commit()
    db.refresh(route)
    return route


def delete_proxy_route(db: Session, route: ProxyRoute) -> None:
    route_id = route.id
    db.delete(route)
    db.flush()
    record_audit(db, action="delete", target_type="proxy_route", target_id=route_id, status="ok")
    db.commit()


def toggle_proxy_route(db: Session, route: ProxyRoute) -> ProxyRoute:
    route.enabled = not route.enabled
    db.flush()
    record_audit(db, action="toggle", target_type="proxy_route", target_id=route.id, status="ok")
    db.commit()
    db.refresh(route)
    return route


def list_dns_records(db: Session) -> list[DnsRecord]:
    return list(db.scalars(select(DnsRecord).order_by(DnsRecord.fqdn, DnsRecord.record_type)))


def _commit_or_raise(db: Session) -> None:
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise
