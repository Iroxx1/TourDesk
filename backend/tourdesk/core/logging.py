"""Structured logging.

Every process (api, worker, scheduler, cli) logs to stdout and – if enabled – to
``<data_dir>/logs/<role>.log`` as JSON lines. Logger names define the category:

* ``tourdesk.http``      access log (webserver)
* ``tourdesk.api``       API / application
* ``tourdesk.auth``      logins, logouts, password changes
* ``tourdesk.audit``     admin actions (also persisted in ``audit_logs``)
* ``tourdesk.crawler``   crawler (plus human readable ``crawler.log``)
* ``tourdesk.scheduler`` scheduler
* ``tourdesk.db``        database errors
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import sys
from datetime import UTC, datetime
from pathlib import Path

from tourdesk.core.config import get_settings

_STANDARD_ATTRS = set(
    logging.LogRecord("", 0, "", 0, "", (), None).__dict__.keys()
) | {"message", "asctime", "taskName"}

LOG_FILES = ("api", "worker", "scheduler", "cli", "crawler")


class JsonFormatter(logging.Formatter):
    def __init__(self, role: str) -> None:
        super().__init__()
        self.role = role

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "role": self.role,
            "msg": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key in _STANDARD_ATTRS or key.startswith("_"):
                continue
            try:
                json.dumps(value)
            except TypeError:
                value = str(value)
            payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


class TextFormatter(logging.Formatter):
    def __init__(self) -> None:
        super().__init__("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S")


class CrawlerSummaryFormatter(logging.Formatter):
    """Plain formatter for the human readable crawler log."""

    def format(self, record: logging.LogRecord) -> str:
        return record.getMessage()


_configured_role: str | None = None


def setup_logging(role: str) -> None:
    """Configure logging for a process role. Safe to call multiple times."""
    global _configured_role
    if _configured_role == role:
        return
    settings = get_settings()
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
    root.setLevel(settings.log_level.upper())

    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(JsonFormatter(role) if settings.log_format == "json" else TextFormatter())
    root.addHandler(stream)

    if settings.log_to_file:
        try:
            log_dir = settings.log_dir
            log_dir.mkdir(parents=True, exist_ok=True)
            fh = logging.handlers.RotatingFileHandler(
                log_dir / f"{role}.log", maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
            )
            fh.setFormatter(JsonFormatter(role))
            root.addHandler(fh)

            summary = logging.getLogger("tourdesk.crawler.summary")
            summary.propagate = False
            for handler in list(summary.handlers):
                summary.removeHandler(handler)
            if role in ("worker", "cli"):
                sh = logging.handlers.RotatingFileHandler(
                    log_dir / "crawler.log", maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
                )
                sh.setFormatter(CrawlerSummaryFormatter())
                summary.addHandler(sh)
        except OSError as exc:  # pragma: no cover - read-only filesystems
            root.warning("file logging disabled: %s", exc)

    # quieter third-party loggers
    for noisy in ("httpx", "httpcore", "urllib3", "PIL", "multipart"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").handlers = []
    logging.getLogger("uvicorn.access").propagate = False
    _configured_role = role


def tail_log(name: str, lines: int = 200, level: str | None = None, contains: str | None = None) -> list[dict]:
    """Return the last ``lines`` entries of a log file (used by the admin log viewer)."""
    if name not in LOG_FILES:
        raise ValueError("unknown log file")
    path: Path = get_settings().log_dir / f"{name}.log"
    if not path.is_file():
        return []
    # read the tail efficiently
    with path.open("rb") as fh:
        fh.seek(0, 2)
        size = fh.tell()
        block = min(size, max(64 * 1024, lines * 1024))
        fh.seek(size - block)
        data = fh.read().decode("utf-8", errors="replace")
    raw_lines = data.splitlines()
    if block < size and raw_lines:
        raw_lines = raw_lines[1:]  # first line may be partial
    out: list[dict] = []
    wanted_levels = None
    if level:
        order = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        level = level.upper()
        if level in order:
            wanted_levels = set(order[order.index(level) :])
    for line in reversed(raw_lines):
        if not line.strip():
            continue
        if name == "crawler":
            entry = {"msg": line}
        else:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                entry = {"msg": line}
        if wanted_levels and entry.get("level") and entry.get("level") not in wanted_levels:
            continue
        if contains and contains.lower() not in line.lower():
            continue
        out.append(entry)
        if len(out) >= lines:
            break
    out.reverse()
    return out
