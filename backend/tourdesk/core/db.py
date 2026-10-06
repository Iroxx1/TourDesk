"""Database engine and session handling (synchronous SQLAlchemy 2.x + psycopg 3)."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from tourdesk.core.config import get_settings

log = logging.getLogger("tourdesk.db")

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def _normalise_url(url: str) -> str:
    # Accept plain postgres URLs and use the psycopg 3 driver
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


def get_engine() -> Engine:
    global _engine, _session_factory
    if _engine is None:
        settings = get_settings()
        _engine = create_engine(
            _normalise_url(settings.database_url),
            pool_pre_ping=True,
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
            pool_recycle=1800,
            future=True,
        )

        @event.listens_for(_engine, "handle_error")
        def _log_db_error(ctx) -> None:  # pragma: no cover - logging only
            if ctx.is_disconnect:
                log.warning("database connection lost", extra={"event": "db.disconnect"})
            else:
                log.error(
                    "database error: %s",
                    ctx.original_exception.__class__.__name__,
                    extra={"event": "db.error", "error": str(ctx.original_exception)[:500]},
                )

        _session_factory = sessionmaker(bind=_engine, expire_on_commit=False, autoflush=True)
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    if _session_factory is None:
        get_engine()
    assert _session_factory is not None
    return _session_factory


def dispose_engine() -> None:
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None


@contextmanager
def session_scope() -> Iterator[Session]:
    """Context manager for scripts/workers: commit on success, rollback on error."""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Iterator[Session]:
    """FastAPI dependency. Endpoints commit explicitly."""
    session = get_session_factory()()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def check_database() -> dict:
    """Return basic database health information."""
    engine = get_engine()
    with engine.connect() as conn:
        version = conn.execute(text("SHOW server_version")).scalar()
        size = conn.execute(text("SELECT pg_database_size(current_database())")).scalar()
        conns = conn.execute(
            text("SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()")
        ).scalar()
        revision = None
        try:
            revision = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        except Exception:  # table missing before first migration
            conn.rollback()
    return {
        "ok": True,
        "server_version": version,
        "size_bytes": int(size or 0),
        "connections": int(conns or 0),
        "migration_revision": revision,
    }
