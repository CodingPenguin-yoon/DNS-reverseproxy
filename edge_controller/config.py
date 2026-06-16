from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Edge Controller"
    database_url: str = "postgresql+psycopg://edge:edge_password@postgres:5432/edge_controller"

    dns_zone: str = "home.arpa"
    dns_wildcard: str = "*.home.arpa"
    edge_ip: str = "192.168.2.10"
    technitium_status: str = "Not configured"

    caddy_binary: str = "caddy"
    caddy_admin_address: str = "http://caddy:2019"
    caddy_config_path: Path = Path("/etc/caddy/Caddyfile")
    caddy_routes_path: Path = Path("/etc/caddy/generated/routes.caddy")
    caddy_candidate_path: Path = Path("/etc/caddy/generated/routes.caddy.candidate")
    caddy_backup_dir: Path = Path("/app/caddy/backups")
    caddy_command_timeout_seconds: int = Field(default=15, ge=1)
    caddy_reload_enabled: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
