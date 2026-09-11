from __future__ import annotations

import sqlite3
import warnings
from datetime import date
from pathlib import Path

import pytest

from lbos.db.bootstrap import open_db, prepare
from lbos.settings import Settings

# Third-party deprecation notices are noise in this suite; lbos's own are
# escalated to errors by the filterwarnings setting in pyproject.toml.
warnings.filterwarnings("ignore", category=DeprecationWarning)

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
    """A client that looks like the shop's own laptop.

    TestClient reports its host as "testclient" by default, which the remote-client
    guard correctly treats as another machine on the network. Real browser traffic
    from the laptop arrives from loopback, so the tests must say so.
    """
    from fastapi.testclient import TestClient

    from lbos.main import create_app

    with TestClient(
        create_app(settings), follow_redirects=False, client=("127.0.0.1", 51000)
    ) as test_client:
        yield test_client


@pytest.fixture
def phone_client(settings: Settings):
    """A client that looks like a phone elsewhere on the Wi-Fi."""
    from fastapi.testclient import TestClient

    from lbos.main import create_app

    linked = settings.model_copy(update={"phone_link_enabled": True})
    with TestClient(
        create_app(linked), follow_redirects=False, client=("192.168.1.77", 51001)
    ) as test_client:
        yield test_client
