from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from edge_controller.config import Settings, get_settings
from edge_controller.models import ConfigRevision, ProxyRoute
from edge_controller.services.caddy_renderer import config_checksum, render_routes_caddyfile


@dataclass(frozen=True)
class CaddyActionResult:
    ok: bool
    status: str
    message: str
    revision_id: int | None = None


@dataclass(frozen=True)
class SystemStatus:
    status: str
    dirty: bool
    desired_checksum: str
    last_applied_at: datetime | None
    last_applied_revision_id: int | None
    message: str


def get_system_status(db: Session) -> SystemStatus:
    desired_config = render_current_routes(db)
    desired_checksum = config_checksum(desired_config)
    latest_applied = db.scalars(
        select(ConfigRevision)
        .where(ConfigRevision.status == "applied")
        .order_by(ConfigRevision.applied_at.desc().nullslast(), ConfigRevision.id.desc())
        .limit(1)
    ).first()

    dirty = latest_applied is None or latest_applied.checksum != desired_checksum
    status = "Pending changes" if dirty else "Applied"
    message = "Changes are waiting to be applied." if dirty else "Runtime config matches database state."

    return SystemStatus(
        status=status,
        dirty=dirty,
        desired_checksum=desired_checksum,
        last_applied_at=latest_applied.applied_at if latest_applied else None,
        last_applied_revision_id=latest_applied.id if latest_applied else None,
        message=message,
    )


def render_current_routes(db: Session) -> str:
    routes = list(db.scalars(select(ProxyRoute).order_by(ProxyRoute.domain)))
    return render_routes_caddyfile(routes)


def validate_routes(db: Session, settings: Settings | None = None) -> CaddyActionResult:
    settings = settings or get_settings()
    rendered = render_current_routes(db)
    checksum = config_checksum(rendered)
    revision = _create_revision(db, rendered, checksum, status="rendered", message="Rendered candidate config.")

    try:
        _ensure_parent(settings.caddy_candidate_path)
        settings.caddy_candidate_path.write_text(rendered, encoding="utf-8")
        _run_caddy_validate(settings, settings.caddy_candidate_path)
    except Exception as exc:
        revision.status = "failed"
        revision.message = f"Validation failed: {exc}"
        db.commit()
        return CaddyActionResult(False, "failed", revision.message, revision.id)

    revision.status = "validated"
    revision.message = "Candidate config validated successfully."
    db.commit()
    return CaddyActionResult(True, "validated", revision.message, revision.id)


def apply_routes(db: Session, settings: Settings | None = None) -> CaddyActionResult:
    settings = settings or get_settings()
    rendered = render_current_routes(db)
    checksum = config_checksum(rendered)
    revision = _create_revision(db, rendered, checksum, status="rendered", message="Rendered candidate config.")

    backup_path: Path | None = None
    previous_config = _read_if_exists(settings.caddy_routes_path)

    try:
        _ensure_parent(settings.caddy_candidate_path)
        settings.caddy_candidate_path.write_text(rendered, encoding="utf-8")
        _run_caddy_validate(settings, settings.caddy_candidate_path)

        backup_path = _backup_current_routes(settings)
        _ensure_parent(settings.caddy_routes_path)
        shutil.move(str(settings.caddy_candidate_path), str(settings.caddy_routes_path))

        _run_caddy_validate(settings, settings.caddy_config_path)
        if settings.caddy_reload_enabled:
            _run_caddy_reload(settings)

    except Exception as exc:
        _restore_previous_routes(settings, previous_config, backup_path)
        if settings.caddy_reload_enabled and previous_config is not None:
            try:
                _run_caddy_reload(settings)
            except Exception:
                pass
        revision.status = "failed"
        revision.message = f"Apply failed and previous config was restored: {exc}"
        db.commit()
        return CaddyActionResult(False, "failed", revision.message, revision.id)

    revision.status = "applied"
    revision.message = "Config applied and Caddy reloaded successfully."
    revision.applied_at = datetime.now(UTC)
    db.commit()
    return CaddyActionResult(True, "applied", revision.message, revision.id)


def rollback_to_revision(db: Session, revision_id: int, settings: Settings | None = None) -> CaddyActionResult:
    settings = settings or get_settings()
    target_revision = db.get(ConfigRevision, revision_id)
    if target_revision is None:
        return CaddyActionResult(False, "failed", f"Revision {revision_id} was not found.")

    rendered = target_revision.rendered_config
    checksum = config_checksum(rendered)
    rollback_revision = _create_revision(
        db,
        rendered,
        checksum,
        status="rendered",
        message=f"Rollback candidate from revision {revision_id}.",
    )
    backup_path: Path | None = None
    previous_config = _read_if_exists(settings.caddy_routes_path)

    try:
        _ensure_parent(settings.caddy_candidate_path)
        settings.caddy_candidate_path.write_text(rendered, encoding="utf-8")
        _run_caddy_validate(settings, settings.caddy_candidate_path)

        backup_path = _backup_current_routes(settings)
        shutil.move(str(settings.caddy_candidate_path), str(settings.caddy_routes_path))
        _run_caddy_validate(settings, settings.caddy_config_path)
        if settings.caddy_reload_enabled:
            _run_caddy_reload(settings)
    except Exception as exc:
        _restore_previous_routes(settings, previous_config, backup_path)
        rollback_revision.status = "failed"
        rollback_revision.message = f"Rollback failed and previous config was restored: {exc}"
        db.commit()
        return CaddyActionResult(False, "failed", rollback_revision.message, rollback_revision.id)

    rollback_revision.status = "rolled_back"
    rollback_revision.message = f"Rolled back to revision {revision_id}."
    rollback_revision.applied_at = datetime.now(UTC)
    db.commit()
    return CaddyActionResult(True, "rolled_back", rollback_revision.message, rollback_revision.id)


def _create_revision(db: Session, rendered: str, checksum: str, *, status: str, message: str) -> ConfigRevision:
    revision_no = (db.scalar(select(func.max(ConfigRevision.revision_no))) or 0) + 1
    revision = ConfigRevision(
        revision_no=revision_no,
        rendered_config=rendered,
        checksum=checksum,
        status=status,
        message=message,
    )
    db.add(revision)
    db.flush()
    return revision


def _run_caddy_validate(settings: Settings, config_path: Path) -> None:
    _run_command(
        [
            settings.caddy_binary,
            "validate",
            "--config",
            str(config_path),
            "--adapter",
            "caddyfile",
        ],
        settings,
    )


def _run_caddy_reload(settings: Settings) -> None:
    _run_command(
        [
            settings.caddy_binary,
            "reload",
            "--config",
            str(settings.caddy_config_path),
            "--adapter",
            "caddyfile",
            "--address",
            settings.caddy_admin_address,
        ],
        settings,
    )


def _run_command(args: list[str], settings: Settings) -> None:
    completed = subprocess.run(
        args,
        capture_output=True,
        check=False,
        text=True,
        timeout=settings.caddy_command_timeout_seconds,
    )
    if completed.returncode != 0:
        output = "\n".join(part for part in [completed.stdout.strip(), completed.stderr.strip()] if part)
        raise RuntimeError(output or f"command failed: {' '.join(args)}")


def _backup_current_routes(settings: Settings) -> Path | None:
    if not settings.caddy_routes_path.exists():
        return None

    settings.caddy_backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    backup_path = settings.caddy_backup_dir / f"routes.{stamp}.caddy"
    shutil.copy2(settings.caddy_routes_path, backup_path)
    return backup_path


def _restore_previous_routes(settings: Settings, previous_config: str | None, backup_path: Path | None) -> None:
    if backup_path is not None and backup_path.exists():
        shutil.copy2(backup_path, settings.caddy_routes_path)
        return

    if previous_config is not None:
        _ensure_parent(settings.caddy_routes_path)
        settings.caddy_routes_path.write_text(previous_config, encoding="utf-8")
    elif settings.caddy_routes_path.exists():
        settings.caddy_routes_path.unlink()


def _read_if_exists(path: Path) -> str | None:
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
