import warnings

with warnings.catch_warnings():
    warnings.filterwarnings("ignore", message=".*starlette.testclient.*")
    from fastapi.testclient import TestClient

from fatball.api.app import create_app


def _client(settings, static_dir):
    return TestClient(create_app(settings, static_dir=static_dir), client=("127.0.0.1", 5000))


def test_spa_fallback_serves_index_for_page_paths(settings, tmp_path):
    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text("<html>gallery</html>")
    (static / "assets" / "app.js").write_text("console.log(1)")
    c = _client(settings, static)
    for path in ("/", "/visit/3", "/birds"):
        r = c.get(path)
        assert r.status_code == 200
        assert "gallery" in r.text
    assert c.get("/assets/app.js").text == "console.log(1)"


def test_api_404_stays_json(settings, tmp_path):
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<html>gallery</html>")
    c = _client(settings, static)
    r = c.get("/api/nope")
    assert r.status_code == 404
    assert r.json() == {"detail": "Not Found"}
    r = c.get("/media/missing.jpg")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/json")


def test_unbuilt_gallery_explains_how_to_build(settings, tmp_path):
    c = _client(settings, tmp_path / "missing")
    r = c.get("/birds")
    assert r.status_code == 503
    assert "The gallery isn't built yet. Run: npm --prefix web ci && npm --prefix web run build" in r.text
