from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

TOKEN_RE = re.compile(r"^[A-Za-z0-9._-]+$")
DOMAIN_RE = re.compile(r"^[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+$")


class ProxyRouteBase(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    domain: str = Field(min_length=3, max_length=255)
    target_scheme: Literal["http", "https"] = "http"
    target_host: str = Field(min_length=1, max_length=255)
    target_port: int = Field(ge=1, le=65535)
    tls_insecure_skip_verify: bool = False
    enabled: bool = True

    @field_validator("name", "target_host")
    @classmethod
    def validate_token(cls, value: str) -> str:
        value = value.strip()
        if not TOKEN_RE.fullmatch(value):
            raise ValueError("only letters, numbers, dots, underscores, and hyphens are allowed")
        return value

    @field_validator("domain")
    @classmethod
    def validate_domain(cls, value: str) -> str:
        value = value.strip().lower()
        if not DOMAIN_RE.fullmatch(value):
            raise ValueError("domain must be a fully qualified domain name")
        return value


class ProxyRouteCreate(ProxyRouteBase):
    pass


class ProxyRouteUpdate(ProxyRouteBase):
    pass


class ProxyRouteRead(ProxyRouteBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime


class DnsRecordRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    fqdn: str
    record_type: str
    value: str
    ttl: int
    enabled: bool
    sync_status: str
    created_at: datetime
    updated_at: datetime


class ConfigRevisionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    revision_no: int
    checksum: str
    status: str
    message: str | None
    created_at: datetime
    applied_at: datetime | None


class ConfigActionResult(BaseModel):
    ok: bool
    status: str
    message: str
    revision_id: int | None = None
