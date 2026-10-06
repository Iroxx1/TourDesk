"""Application configuration (environment variables / ``.env``).

All settings use the prefix ``TOURDESK_``. Crawler behaviour that admins should be
able to change at runtime lives in the database (see ``services/app_settings.py``);
the values here are only the defaults for those.
"""

from __future__ import annotations

import ipaddress
import os
import secrets
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _detect_home() -> Path:
    env = os.environ.get("TOURDESK_HOME")
    if env:
        return Path(env).resolve()
    here = Path(__file__).resolve()
    # backend/tourdesk/core/config.py -> repository root
    for parent in here.parents:
        if (parent / "migrations").is_dir() and (parent / "backend").is_dir():
            return parent
    return Path.cwd().resolve()


HOME = _detect_home()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="TOURDESK_",
        env_file=(str(HOME / ".env"),),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: Literal["production", "development", "test"] = "production"

    # --- database -------------------------------------------------------------------
    database_url: str = "postgresql+psycopg://tourdesk:tourdesk@localhost:5432/tourdesk"
    db_pool_size: int = 10
    db_max_overflow: int = 10

    # --- web ------------------------------------------------------------------------
    host: str = "0.0.0.0"
    port: int = 8080
    public_url: str | None = None
    secret_key: SecretStr | None = None
    trusted_proxies: str = "127.0.0.1,::1"
    allowed_hosts: str = "*"
    cookie_secure: Literal["auto", "true", "false"] = "auto"
    enable_api_docs: bool = False
    frontend_dist: Path | None = None

    # --- sessions / auth ------------------------------------------------------------
    session_hours: int = 12
    session_remember_days: int = 30
    session_idle_days: int = 7
    password_min_length: int = 10
    login_max_attempts_per_ip: int = 20
    login_window_minutes: int = 15
    login_lockout_threshold: int = 5
    api_rate_limit_per_minute: int = 600
    allow_remote_setup: bool = False

    # --- paths ----------------------------------------------------------------------
    data_dir: Path = Field(default_factory=lambda: HOME / "data")

    # --- logging --------------------------------------------------------------------
    log_level: str = "INFO"
    log_format: Literal["json", "text"] = "json"
    log_to_file: bool = True

    # --- crawler defaults (overridable in the admin UI) -----------------------------
    crawler_interval_minutes: int = 60
    crawler_user_agent: str = "TourDeskBot/1.0 (+self-hosted concert monitor)"
    crawler_contact: str | None = None
    crawler_allow_private_networks: bool = False
    worker_threads: int = 3
    scheduler_tick_seconds: int = 30
    ticketmaster_api_key: SecretStr | None = None
    bandsintown_app_id: SecretStr | None = None
    songkick_api_key: SecretStr | None = None
    geocoder_enabled: bool = True
    geocoder_url: str = "https://nominatim.openstreetmap.org"

    @field_validator("data_dir", mode="before")
    @classmethod
    def _resolve_data_dir(cls, value: object) -> object:
        if isinstance(value, str) and value and not os.path.isabs(value):
            return (HOME / value).resolve()
        return value

    # ------------------------------------------------------------------ derived
    @property
    def is_production(self) -> bool:
        return self.env == "production"

    @property
    def media_dir(self) -> Path:
        return self.data_dir / "media"

    @property
    def log_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def backup_dir(self) -> Path:
        return self.data_dir / "backups"

    @property
    def home(self) -> Path:
        return HOME

    @property
    def migrations_dir(self) -> Path:
        return HOME / "migrations"

    @property
    def seed_dir(self) -> Path:
        return HOME / "database" / "seed"

    @property
    def wallpaper_dir(self) -> Path:
        return HOME / "frontend" / "public" / "wallpapers"

    @property
    def resolved_frontend_dist(self) -> Path | None:
        candidates = [self.frontend_dist] if self.frontend_dist else []
        candidates += [HOME / "frontend" / "dist", Path("/app/frontend/dist")]
        for c in candidates:
            if c and (c / "index.html").is_file():
                return c
        return None

    @property
    def trusted_proxy_networks(self) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
        nets = []
        for part in self.trusted_proxies.split(","):
            part = part.strip()
            if not part:
                continue
            if part == "*":
                nets.append(ipaddress.ip_network("0.0.0.0/0"))
                nets.append(ipaddress.ip_network("::/0"))
                continue
            try:
                nets.append(ipaddress.ip_network(part, strict=False))
            except ValueError:
                continue
        return nets

    @property
    def allowed_host_list(self) -> list[str]:
        return [h.strip() for h in self.allowed_hosts.split(",") if h.strip()]

    def get_secret_key(self) -> str:
        """Return the secret key; in non-production create and persist one on demand."""
        if self.secret_key and self.secret_key.get_secret_value():
            return self.secret_key.get_secret_value()
        key_file = self.data_dir / "secret_key"
        if key_file.is_file():
            return key_file.read_text().strip()
        if self.is_production:
            raise RuntimeError(
                "TOURDESK_SECRET_KEY ist nicht gesetzt. Bitte in der .env-Datei konfigurieren."
            )
        key_file.parent.mkdir(parents=True, exist_ok=True)
        key = secrets.token_urlsafe(48)
        key_file.write_text(key)
        try:
            key_file.chmod(0o600)
        except OSError:
            pass
        return key


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()
