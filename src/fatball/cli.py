"""The `fatball` command: serve, setup and demo."""

import argparse
import getpass
import ipaddress
import logging
import tempfile
import threading
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path

from fatball import demo, secrets
from fatball.api import auth as auth_mod
from fatball.camera import discovery
from fatball.config import Settings
from fatball.ingest.processor import Processor
from fatball.ingest.watcher import CAMERA_NAME, Watcher
from fatball.library import db, repo

log = logging.getLogger("fatball")

PROCESS_INTERVAL_S = 2.0
PIN_ATTEMPTS = 3


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fatball", description="Who Ate the Fat Ball? Bird-feeder camera app.")
    sub = parser.add_subparsers(dest="command", required=True, metavar="{serve,demo,setup}")
    serve = sub.add_parser("serve", help="run the camera watcher, the converter and the web app")
    serve.add_argument("--host", default="0.0.0.0", help="address to listen on (default: all, for the LAN)")
    serve.add_argument("--port", type=int, default=8080)
    demo_p = sub.add_parser("demo", help="try the app with a fake camera full of generated clips")
    demo_p.add_argument("--port", type=int, default=8080)
    sub.add_parser("setup", help="set the camera password, the edit PIN and (optionally) the camera IP")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "setup":
        return run_setup(Settings.load())
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if args.command == "serve":
        serve(Settings.load(), host=args.host, port=args.port)
    else:
        run_demo(port=args.port)
    return 0


# serve and demo share this
def processor_loop(processor, stop: threading.Event, interval_s: float = PROCESS_INTERVAL_S) -> None:
    """Convert downloaded clips until `stop` is set; one failing pass never stops the loop."""
    while not stop.is_set():
        try:
            processor.process_pending()
        except Exception:
            log.exception("processing pass failed; retrying")
        stop.wait(interval_s)


def _urls(host: str, port: int) -> list[str]:
    urls = [f"http://localhost:{port}"]
    if host in ("0.0.0.0", "::"):
        lan = discovery.local_ipv4()
        if lan:
            urls.insert(0, f"http://{lan}:{port}")
    elif host not in ("127.0.0.1", "localhost", "::1"):
        urls.insert(0, f"http://{host}:{port}")
    return urls


def serve(settings: Settings, *, host: str, port: int, watcher_options: dict | None = None,
          banner: str = "") -> None:
    """Run the watcher and the processor in background threads and the API in this one until Ctrl-C."""
    import uvicorn

    from fatball.api.app import create_app

    settings.data_dir.mkdir(parents=True, exist_ok=True)
    # One connection per thread: sqlite3 connections are not safe for concurrent use.
    watcher_conn, processor_conn, api_conn = (db.connect(settings.db_path) for _ in range(3))
    stop = threading.Event()
    watcher = Watcher(settings, watcher_conn, sleep=stop.wait, **(watcher_options or {}))
    processor = Processor(settings, processor_conn)
    threads = [
        threading.Thread(target=watcher.run_forever, name="watcher", daemon=True),
        threading.Thread(target=processor_loop, args=(processor, stop), name="processor", daemon=True),
    ]
    for t in threads:
        t.start()

    if banner:
        print(banner)
    urls = _urls(host, port)
    print("Open " + " or ".join(urls))
    print(f"Set up from this Mac at http://localhost:{port} (setup only works locally). Ctrl-C stops.")

    # proxy_headers=False: we never sit behind a proxy, so X-Forwarded-For must not make a client "local".
    config = uvicorn.Config(create_app(settings, api_conn), host=host, port=port, proxy_headers=False)
    try:
        uvicorn.Server(config).run()
    except KeyboardInterrupt:
        pass
    finally:
        watcher.stop()
        stop.set()
        for t in threads:
            t.join(timeout=15)
        for c in (watcher_conn, processor_conn, api_conn):
            c.close()
        print("Stopped.")


DEMO_BANNER = """
  Who Ate the Fat Ball? - DEMO
  ----------------------------
  This is a demo with a pretend camera and {n} generated test-pattern clips over {days} days.
  Nothing here is real footage, the real camera is not contacted and nothing is kept: the demo's
  data lives in a temporary folder that is deleted when you stop it.
"""


def run_demo(*, port: int, n_clips: int = 12, days: int = 2) -> None:
    print("Generating demo clips...")
    with tempfile.TemporaryDirectory(prefix="fatball-demo-") as tmp, \
            demo.build_demo_camera(n_clips=n_clips, days=days) as cam:
        settings = Settings(data_dir=Path(tmp), camera_port=cam.port)
        conn = db.connect(settings.db_path)
        repo.upsert_camera(conn, CAMERA_NAME, None, "127.0.0.1")
        conn.close()
        serve(settings, host="0.0.0.0", port=port, watcher_options=demo.watcher_options(),
              banner=DEMO_BANNER.format(n=n_clips, days=days))


# setup
def run_setup(
    settings: Settings,
    *,
    input_fn: Callable[[str], str] = input,
    getpass_fn: Callable[[str], str] = getpass.getpass,
    get_password: Callable[[], str | None] = secrets.get_password,
    set_password: Callable[[str], None] = secrets.set_password,
) -> int:
    """Interactive setup on the Mac itself: writes the database and the Keychain directly. Never echoes secrets."""
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    conn = db.connect(settings.db_path)
    try:
        while True:
            ip = input_fn("Camera IP address (blank = keep / find it automatically): ").strip()
            if not ip:
                break
            try:
                ipaddress.ip_address(ip)
            except ValueError:
                print("That is not an IP address (for example 192.168.1.40). Try again.")
                continue
            repo.upsert_camera(conn, CAMERA_NAME, None, ip)
            print("Camera IP saved.")
            break

        password = getpass_fn("Camera password (blank = keep the current one): ")
        if password:
            set_password(password)
            print("Camera password saved in the Keychain.")
        elif get_password() is None:
            answer = input_fn("No camera password is stored. Does the camera have no password? [y/N] ")
            if answer.strip().lower() in ("y", "yes"):
                set_password("")
                print("Saved: the camera has no password.")
            else:
                print("No camera password stored yet; run `fatball setup` again to add it.")
        else:
            print("Camera password unchanged.")

        for _ in range(PIN_ATTEMPTS):
            pin = getpass_fn("Edit PIN, 4 digits (blank = keep the current one): ")
            if not pin:
                print("Edit PIN unchanged.")
                break
            if auth_mod.valid_pin_format(pin):
                auth_mod.Auth(conn, lambda: datetime.now().astimezone(), threading.Lock()).set_edit_pin(pin)
                print("Edit PIN saved.")
                break
            print("The edit PIN must be exactly 4 digits.")
        else:
            print("Edit PIN not changed.")
            return 2
    finally:
        conn.close()
    return 0
