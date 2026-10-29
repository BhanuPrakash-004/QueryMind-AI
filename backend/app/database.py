"""SQLAlchemy engine and session management.

The runtime engine is deliberately separate from the administrative engine.
Runtime access never falls back to the admin connection.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine.url import make_url
from sqlalchemy.orm import Session

from .config import get_settings

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def normalize_database_url(raw_url: str) -> str:
    """Return a SQLAlchemy URL configured for psycopg 3 and encrypted transport."""
    if not raw_url or not raw_url.strip():
        raise ValueError("database URL is empty")

    url = make_url(raw_url.strip())
    if url.drivername in {"postgres", "postgresql"}:
        url = url.set(drivername="postgresql+psycopg")

    if url.get_backend_name() == "postgresql":
        query = dict(url.query)
        if "sslmode" not in query and (url.host or "") not in _LOCAL_HOSTS:
            query["sslmode"] = "require"
        if query:
            url = url.set(query=query)

    return url.render_as_string(hide_password=False)


def _create_engine(raw_url: str) -> Engine:
    url = normalize_database_url(raw_url)
    options: dict[str, object] = {"pool_pre_ping": True}
    if url.startswith("postgresql"):
        options.update(
            pool_size=2,
            max_overflow=3,
            pool_timeout=10,
            pool_recycle=1800,
        )
    return create_engine(url, **options)


@lru_cache
def get_admin_engine() -> Engine:
    settings = get_settings()
    return _create_engine(settings.require_database_admin_url())


@lru_cache
def get_runtime_engine() -> Engine:
    settings = get_settings()
    return _create_engine(settings.require_database_url())


@contextmanager
def runtime_session() -> Iterator[Session]:
    """Yield a read-only session using the restricted runtime role."""
    engine = get_runtime_engine()
    with Session(engine) as session:
        if engine.dialect.name == "postgresql":
            session.execute(text("SET TRANSACTION READ ONLY"))
            session.execute(text("SET LOCAL statement_timeout = '10s'"))
        yield session


def reset_engines() -> None:
    """Clear cached engines (used by tests after changing configuration)."""
    get_admin_engine.cache_clear()
    get_runtime_engine.cache_clear()
