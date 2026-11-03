import pytest

from fatball.library import repo

from .test_visits_api import add_visit, sure


@pytest.fixture(autouse=True)
def catalog(conn):
    repo.ensure_catalog(conn)


def test_bulk_needs_editor(lan, conn, cam):
    _, v = add_visit(conn, cam, 0, sure())
    r = lan.post("/api/visits/bulk", json={"visit_ids": [v], "is_favourite": True})
    assert r.status_code == 403


def test_bulk_returns_token_and_count(local, conn, cam):
    _, a = add_visit(conn, cam, 0, sure())
    _, b = add_visit(conn, cam, 1000, sure())
    r = local.post("/api/visits/bulk", json={"visit_ids": [a, b], "category": "other"})
    assert r.status_code == 200 and r.json()["changed"] == 2
    cat = lambda v: conn.execute("SELECT category FROM visit WHERE id = ?", (v,)).fetchone()[0]
    assert cat(a) == cat(b) == "other"
    assert local.post(f"/api/undo/{r.json()['undo_token']}").status_code == 204
    assert cat(a) == cat(b) == "birds"


def test_bulk_unknown_id_is_404(local, conn, cam):
    _, a = add_visit(conn, cam, 0, sure())
    assert local.post("/api/visits/bulk", json={"visit_ids": [a, 999], "is_favourite": True}).status_code == 404


def test_bulk_validation(local, conn, cam):
    _, a = add_visit(conn, cam, 0, sure())
    assert local.post("/api/visits/bulk", json={"visit_ids": list(range(1, 502)), "is_favourite": True}).status_code == 422
    assert local.post("/api/visits/bulk", json={"visit_ids": [a]}).status_code == 422
    assert local.post("/api/visits/bulk", json={"visit_ids": [], "is_favourite": True}).status_code == 422
    assert local.post("/api/visits/bulk", json={"visit_ids": [a], "category": "nope"}).status_code == 422
