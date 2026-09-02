"""Request-scoped dependencies."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator

from fastapi import Depends, Request

from lbos.db.connection import connect
from lbos.settings import Settings


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_conn(settings: Settings = Depends(get_settings)) -> Iterator[sqlite3.Connection]:
    """One connection per request, always closed."""
    conn = connect(settings.db_path)
    try:
        yield conn
    finally:
        conn.close()
