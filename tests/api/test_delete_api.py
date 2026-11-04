import pytest

from fatball.library import repo
from fatball.recognition.matcher import Verdict

from .test_visits_api import GREAT, add_visit, sure


@pytest.fixture(autouse=True)
def catalog(conn):
    repo.ensure_catalog(conn)


def empty():
    return Verdict("other", None, 0.9, [], "nothing", None)


def test_delete_needs_editor(lan, conn, cam):
    _, v = add_visit(conn, cam, 0, empty())
    assert lan.post("/api/visits/delete", json={"visit_ids": [v]}).status_code == 403


def test_delete_empty_visits(local, conn, cam):
    _, a = add_visit(conn, cam, 0, empty())
    _, b = add_visit(conn, cam, 1000, empty())
    r = local.post("/api/visits/delete", json={"visit_ids": [a, b]})
    assert r.status_code == 200 and r.json() == {"deleted": 2}
    assert conn.execute("SELECT COUNT(*) FROM visit").fetchone()[0] == 0


def test_delete_409_for_bird(local, conn, cam):
    _, e = add_visit(conn, cam, 0, empty())
    _, b = add_visit(conn, cam, 1000, sure(GREAT))
    r = local.post("/api/visits/delete", json={"visit_ids": [e, b]})
    assert r.status_code == 409 and r.json() == {"detail": "Only empty clips can be deleted"}
    assert conn.execute("SELECT COUNT(*) FROM visit").fetchone()[0] == 2


def test_delete_404_and_validation(local, conn, cam):
    _, e = add_visit(conn, cam, 0, empty())
    assert local.post("/api/visits/delete", json={"visit_ids": [e, 999]}).status_code == 404
    assert local.post("/api/visits/delete", json={"visit_ids": []}).status_code == 422
    assert local.post("/api/visits/delete", json={"visit_ids": list(range(1, 502))}).status_code == 422


def test_only_filter_over_the_api(local, conn, cam):
    _, e = add_visit(conn, cam, 0, empty())
    _, d = add_visit(conn, cam, 1000, Verdict("other", "Canis lupus familiaris", 0.9, [], "species", None))
    ids = lambda q: [v["id"] for v in local.get(f"/api/visits?{q}").json()["items"]]
    assert ids("category=other&only=empty") == [e]
    assert ids("category=other&only=dogs") == [d]
    assert local.get("/api/visits?category=birds&only=dogs").status_code == 422
    assert local.get("/api/visits?only=empty").status_code == 422
