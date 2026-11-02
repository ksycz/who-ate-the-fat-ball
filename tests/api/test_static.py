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


def _installable_static(tmp_path):
    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text("<html>gallery</html>")
    (static / "manifest.webmanifest").write_text('{"name": "Who Ate the Fat Ball?"}')
    (static / "sw.js").write_text("self.addEventListener('fetch', () => {})")
    (static / "favicon.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>")
    (static / "icon-192.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    return static


def test_manifest_served_with_manifest_type(settings, tmp_path):
    r = _client(settings, _installable_static(tmp_path)).get("/manifest.webmanifest")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/manifest+json")
    assert r.json()["name"] == "Who Ate the Fat Ball?"


def test_sw_not_cached(settings, tmp_path):
    r = _client(settings, _installable_static(tmp_path)).get("/sw.js")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-cache"
    assert "javascript" in r.headers["content-type"]


def test_root_files_are_served_as_files_not_the_gallery(settings, tmp_path):
    c = _client(settings, _installable_static(tmp_path))
    assert c.get("/favicon.svg").headers["content-type"].startswith("image/svg+xml")
    r = c.get("/icon-192.png")
    assert r.headers["content-type"] == "image/png"
    assert r.content.startswith(b"\x89PNG")


def test_missing_root_file_and_traversal_fall_back_to_the_gallery(settings, tmp_path):
    static = _installable_static(tmp_path)
    (tmp_path / "secret.png").write_bytes(b"secret")
    c = _client(settings, static)
    assert "gallery" in c.get("/nothing.png").text
    assert "gallery" in c.get("/..%2Fsecret.png").text
    assert b"secret" not in c.get("/../secret.png").content


def test_index_is_never_cached(settings, tmp_path):
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<html>gallery</html>")
    r = _client(settings, static).get("/birds")
    assert r.headers["cache-control"] == "no-cache"


def test_nul_in_path_is_404_not_500(settings, tmp_path):
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<html>gallery</html>")
    assert _client(settings, static).get("/%00").status_code == 404
