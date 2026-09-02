from __future__ import annotations

import sqlite3
import warnings
from datetime import date
from pathlib import Path

import pytest

warnings.filterwarnings("ignore", category=DeprecationWarning)

from lbos.db.bootstrap import open_db, prepare
from lbos.settings import Settings

TODAY = date(2026, 9, 2)  # a Wednesday


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=str(tmp_path / "data"),
        scheduler_enabled=False,
        llm_enabled=False,
        ocr_enabled=False,
        timezone="Asia/Dhaka",
    )


@pytest.fixture
def conn(settings: Settings) -> sqlite3.Connection:
    prepare(settings)
    connection = open_db(settings)
    yield connection
    connection.close()


@pytest.fixture
def client(settings: Settings):
    from fastapi.testclient import TestClient

    from lbos.main import create_app

    with TestClient(create_app(settings), follow_redirects=False) as test_client:
        yield test_client
