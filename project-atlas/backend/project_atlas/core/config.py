"""Configuration loaded from ATLAS_* environment variables with safe defaults.

Configuration is validated at startup; invalid combinations raise ConfigError
rather than silently running in an unsafe state.
"""

from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse


class ConfigError(ValueError):
    pass


def _bool(value: str | None, default: bool) -> bool:
    if value is None or value == "":
        return default
    v = value.strip().lower()
    if v in {"1", "true", "yes", "on"}:
        return True
    if v in {"0", "false", "no", "off"}:
        return False
    raise ConfigError(f"Invalid boolean value: {value!r}")


def _int(value: str | None, default: int) -> int:
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ConfigError(f"Invalid integer value: {value!r}") from exc


LAN_NETWORKS = [ipaddress.ip_network(n) for n in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16", "fc00::/7", "fe80::/10")]


def is_lan_address(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """RFC 1918 / RFC 4193 / link-local only (not documentation or other special ranges)."""
    return any(ip.version == n.version and ip in n for n in LAN_NETWORKS)


def is_local_host(host: str) -> bool:
    """True for 'localhost', loopback, and RFC1918/ULA/link-local private addresses."""
    if not host:
        return False
    if host in {"localhost", "localhost.localdomain"}:
        return True
    try:
        ip = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return False
    return ip.is_loopback or is_lan_address(ip)


@dataclass
class Settings:
    app_name: str = "Project Atlas"
    env: str = "development"
    offline_mode: bool = True
    host: str = "127.0.0.1"
    port: int = 8000
    database_url: str = ""
    storage_dir: Path = Path("./atlas-workspace")
    backup_dir: Path = Path("./atlas-backups")
    ai_enabled: bool = False
    ai_base_url: str = ""
    model_dir: Path = Path("./models")
    telemetry_enabled: bool = False
    log_level: str = "INFO"
    session_ttl_minutes: int = 480
    max_upload_mb: int = 200
    jobs_inline: bool = False
    allow_lan: bool = False
    tls_terminated: bool = False
    query_timeout_seconds: int = 20
    query_row_limit: int = 5000
    graph_node_limit: int = 2000
    frontend_dist: Path | None = None
    backup_interval_hours: float = 0.0
    backup_retention: int = 10
    backup_passphrase_file: Path | None = None
    retention_enforce_hours: float = 0.0
    extra: dict = field(default_factory=dict)

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        db_name = {"production": "atlas_prod", "test": "atlas_test"}.get(self.env, "atlas_dev")
        return f"sqlite:///{(self.storage_dir / f'{db_name}.sqlite3').resolve()}"

    @property
    def is_sqlite(self) -> bool:
        return self.resolved_database_url.startswith("sqlite")

    @property
    def files_dir(self) -> Path:
        return self.storage_dir / "files"

    @property
    def derived_dir(self) -> Path:
        return self.storage_dir / "derived"

    @property
    def exports_dir(self) -> Path:
        return self.storage_dir / "exports"

    def ensure_dirs(self) -> None:
        for d in (self.storage_dir, self.backup_dir, self.files_dir, self.derived_dir, self.exports_dir):
            d.mkdir(parents=True, exist_ok=True)

    def validate(self) -> None:
        if self.env not in {"development", "test", "production"}:
            raise ConfigError("ATLAS_ENV must be development, test or production")
        if not (1 <= self.port <= 65535):
            raise ConfigError("ATLAS_PORT out of range")
        if self.telemetry_enabled:
            raise ConfigError("Telemetry is not implemented; ATLAS_TELEMETRY_ENABLED must be false")
        if not is_local_host(self.host) and self.host not in {"0.0.0.0", "::"}:
            raise ConfigError(f"ATLAS_HOST {self.host!r} must be loopback or a private address")
        if self.host in {"0.0.0.0", "::"} or not _is_loopback(self.host):
            if not self.allow_lan:
                raise ConfigError(
                    "Binding to a non-loopback address requires ATLAS_ALLOW_LAN=true (private LAN profile)"
                )
            if self.env == "production" and not self.tls_terminated:
                raise ConfigError(
                    "LAN production deployments require TLS; set ATLAS_TLS_TERMINATED=true once a TLS proxy is configured"
                )
        if self.ai_base_url:
            parsed = urlparse(self.ai_base_url)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                raise ConfigError("ATLAS_AI_BASE_URL must be an http(s) URL")
            if self.offline_mode and not is_local_host(parsed.hostname):
                raise ConfigError("Offline mode only permits a loopback/private AI endpoint")
        if self.ai_enabled and not self.ai_base_url:
            raise ConfigError("ATLAS_AI_ENABLED=true requires ATLAS_AI_BASE_URL")
        if self.max_upload_mb <= 0 or self.session_ttl_minutes <= 0:
            raise ConfigError("Upload and session limits must be positive")


def _is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False


def read_env_file(path: Path) -> dict[str, str]:
    """Minimal .env parser: KEY=VALUE lines, '#' comment lines, optional surrounding quotes."""
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            v = v[1:-1]
        out[k.strip()] = v
    return out


def load_settings(env: dict[str, str] | None = None) -> Settings:
    """Load settings from ``env`` or, by default, ``ATLAS_ENV_FILE``/``./.env`` overlaid by the process environment."""
    if env is None:
        env_file = Path(os.environ.get("ATLAS_ENV_FILE", ".env"))
        e = {**(read_env_file(env_file) if env_file.is_file() else {}), **os.environ}
    else:
        e = env
    frontend = e.get("ATLAS_FRONTEND_DIST")
    s = Settings(
        app_name=e.get("ATLAS_APP_NAME", "Project Atlas"),
        env=e.get("ATLAS_ENV", "development"),
        offline_mode=_bool(e.get("ATLAS_OFFLINE_MODE"), True),
        host=e.get("ATLAS_HOST", "127.0.0.1"),
        port=_int(e.get("ATLAS_PORT"), 8000),
        database_url=e.get("ATLAS_DATABASE_URL", ""),
        storage_dir=Path(e.get("ATLAS_STORAGE_DIR") or "./atlas-workspace"),
        backup_dir=Path(e.get("ATLAS_BACKUP_DIR") or "./atlas-backups"),
        ai_enabled=_bool(e.get("ATLAS_AI_ENABLED"), False),
        ai_base_url=e.get("ATLAS_AI_BASE_URL", ""),
        model_dir=Path(e.get("ATLAS_MODEL_DIR") or "./models"),
        telemetry_enabled=_bool(e.get("ATLAS_TELEMETRY_ENABLED"), False),
        log_level=e.get("ATLAS_LOG_LEVEL", "INFO").upper(),
        session_ttl_minutes=_int(e.get("ATLAS_SESSION_TTL_MINUTES"), 480),
        max_upload_mb=_int(e.get("ATLAS_MAX_UPLOAD_MB"), 200),
        jobs_inline=_bool(e.get("ATLAS_JOBS_INLINE"), False),
        allow_lan=_bool(e.get("ATLAS_ALLOW_LAN"), False),
        tls_terminated=_bool(e.get("ATLAS_TLS_TERMINATED"), False),
        query_timeout_seconds=_int(e.get("ATLAS_QUERY_TIMEOUT_SECONDS"), 20),
        query_row_limit=_int(e.get("ATLAS_QUERY_ROW_LIMIT"), 5000),
        graph_node_limit=_int(e.get("ATLAS_GRAPH_NODE_LIMIT"), 2000),
        frontend_dist=Path(frontend) if frontend else None,
        backup_interval_hours=float(e.get("ATLAS_BACKUP_INTERVAL_HOURS") or 0),
        backup_retention=_int(e.get("ATLAS_BACKUP_RETENTION"), 10),
        backup_passphrase_file=Path(e["ATLAS_BACKUP_PASSPHRASE_FILE"]) if e.get("ATLAS_BACKUP_PASSPHRASE_FILE") else None,
        retention_enforce_hours=float(e.get("ATLAS_RETENTION_ENFORCE_HOURS") or 0),
    )
    s.validate()
    return s
