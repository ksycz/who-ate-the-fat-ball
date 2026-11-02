import warnings
from datetime import datetime, timedelta

import pytest

with warnings.catch_warnings():
    # Starlette 1.x prefers httpx2 for TestClient; httpx still works and is the dev dependency we have.
    warnings.filterwarnings("ignore", message=".*starlette.testclient.*")
    from fastapi.testclient import TestClient

from fatball import secrets as camera_secrets
from fatball.api.app import create_app
from fatball.config import Settings
from fatball.library import repo
from fatball.library.db import connect

LOCAL = ("127.0.0.1", 5000)
LAN = ("192.168.1.50", 5000)
NOW = datetime(2026, 10, 31, 15, 0, 0).astimezone()


class Clock:
    def __init__(self, t=NOW):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, **kw):
        self.t += timedelta(**kw)


@pytest.fixture
def settings(tmp_path):
    s = Settings(data_dir=tmp_path)
    s.media_dir.mkdir()
    return s


@pytest.fixture
def conn(settings):
    c = connect(settings.db_path)
    yield c
    c.close()


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def stored_passwords(monkeypatch):
    saved = []
    monkeypatch.setattr(camera_secrets, "set_password", saved.append)
    return saved


@pytest.fixture
def app(settings, conn, clock, stored_passwords):
    return create_app(settings, now=clock)  # opens its own connection per request


@pytest.fixture
def make_client(app):
    def make(client=LOCAL):
        return TestClient(app, client=client, base_url="http://localhost")

    return make


@pytest.fixture
def local(make_client):
    return make_client(LOCAL)


@pytest.fixture
def lan(make_client):
    return make_client(LAN)


@pytest.fixture
def cam(conn):
    return repo.upsert_camera(conn, "feeder", None, None)

