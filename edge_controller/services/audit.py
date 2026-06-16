from __future__ import annotations

from sqlalchemy.orm import Session

from edge_controller.models import AuditLog


def record_audit(
    db: Session,
    *,
    action: str,
    target_type: str,
    target_id: int | None,
    status: str,
    message: str | None = None,
) -> None:
    db.add(
        AuditLog(
            action=action,
            target_type=target_type,
            target_id=target_id,
            status=status,
            message=message,
        )
    )
