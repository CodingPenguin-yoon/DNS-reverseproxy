from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from edge_controller.database import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class ProxyRoute(TimestampMixin, Base):
    __tablename__ = "proxy_routes"
    __table_args__ = (
        UniqueConstraint("name", name="uq_proxy_routes_name"),
        UniqueConstraint("domain", name="uq_proxy_routes_domain"),
        CheckConstraint("target_scheme IN ('http', 'https')", name="ck_proxy_routes_target_scheme"),
        CheckConstraint("target_port BETWEEN 1 AND 65535", name="ck_proxy_routes_target_port"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    domain: Mapped[str] = mapped_column(String(255), nullable=False)
    target_scheme: Mapped[str] = mapped_column(String(8), nullable=False, default="http")
    target_host: Mapped[str] = mapped_column(String(255), nullable=False)
    target_port: Mapped[int] = mapped_column(Integer, nullable=False)
    tls_insecure_skip_verify: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    @property
    def target(self) -> str:
        prefix = "https://" if self.target_scheme == "https" else "http://"
        return f"{prefix}{self.target_host}:{self.target_port}"


class DnsRecord(TimestampMixin, Base):
    __tablename__ = "dns_records"
    __table_args__ = (
        UniqueConstraint("fqdn", "record_type", name="uq_dns_records_fqdn_record_type"),
        CheckConstraint("ttl > 0", name="ck_dns_records_ttl_positive"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    fqdn: Mapped[str] = mapped_column(String(255), nullable=False)
    record_type: Mapped[str] = mapped_column(String(16), nullable=False, default="A")
    value: Mapped[str] = mapped_column(String(255), nullable=False)
    ttl: Mapped[int] = mapped_column(Integer, nullable=False, default=300)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sync_status: Mapped[str] = mapped_column(String(32), nullable=False, default="not_synced")


class ConfigRevision(Base):
    __tablename__ = "config_revisions"
    __table_args__ = (UniqueConstraint("revision_no", name="uq_config_revisions_revision_no"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    revision_no: Mapped[int] = mapped_column(Integer, nullable=False)
    rendered_config: Mapped[str] = mapped_column(Text, nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    target_type: Mapped[str] = mapped_column(String(80), nullable=False)
    target_id: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
