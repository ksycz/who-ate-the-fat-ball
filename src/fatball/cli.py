"""The `fatball` command: serve, setup, set-camera-password and demo."""

import argparse
import csv
import getpass
import ipaddress
import logging
import signal
import sqlite3
import tempfile
import threading
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path

from fatball import demo, secrets
from fatball.api import auth as auth_mod
from fatball.camera import discovery
from fatball.camera.client import CameraError, CameraUnreachable, WrongPassword, XMClient
from fatball.config import Settings
from fatball.ingest.processor import Processor, recognize_and_group
from fatball.ingest.watcher import CAMERA_NAME, CAMERA_USER, Watcher
from fatball.library import db, repo
from fatball.recognition import qos
from fatball.recognition.catalog import DOG
from fatball.recognition.detector import MODEL_FILENAME
from fatball.recognition.features import feature_print
from fatball.recognition.recognizer import Recognizer

log = logging.getLogger("fatball")

PROCESS_INTERVAL_S = 2.0
PIN_ATTEMPTS = 3
MIN_CAMERA_PASSWORD = 6


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fatball", description="Who Ate the Fat Ball? Bird-feeder camera app.")
    sub = parser.add_subparsers(dest="command", required=True, metavar="{serve,demo,setup,set-camera-password,examples-import}")
    serve = sub.add_parser("serve", help="run the camera watcher, the converter and the web app")
    serve.add_argument("--host", default="0.0.0.0", help="address to listen on (default: all, for the LAN)")
    serve.add_argument("--port", type=int, default=8080)
    demo_p = sub.add_parser("demo", help="try the app with a fake camera full of generated clips")
    demo_p.add_argument("--host", default="127.0.0.1",
                        help="address to listen on (default: this Mac only; 0.0.0.0 for the LAN)")
    demo_p.add_argument("--port", type=int, default=8080)
    sub.add_parser("setup", help="set the camera password, the edit PIN and (optionally) the camera IP")
    sub.add_parser("set-camera-password",
                   help="give the camera a new password of your choice (so iCSee can't swap an empty one)")
    imp = sub.add_parser("examples-import", help="label clips from a CSV (clip_id,label) to seed the examples")
    imp.add_argument("csv", type=Path, help="CSV with the columns clip_id,label")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "setup":
        return run_setup(Settings.load())
    if args.command == "set-camera-password":
        return run_set_camera_password(Settings.load())
    if args.command == "examples-import":
        settings = Settings.load()
        return run_examples_import(settings, args.csv, detector_loader=model_loader(settings))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if args.command == "serve":
        serve(Settings.load(), host=args.host, port=args.port)
    else:
        run_demo(host=args.host, port=args.port)
    return 0


# serve and demo share this
def processor_loop(processor, stop: threading.Event, interval_s: float = PROCESS_INTERVAL_S) -> None:
    """Convert and recognise clips until `stop` is set; one failing pass never stops the loop.

    The thread drops to background priority first, so recognition yields to everything else on the Mac."""
    qos.set_background_priority()
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


def _raise_keyboard_interrupt(signum, frame) -> None:
    raise KeyboardInterrupt


def _install_sigterm_as_keyboard_interrupt():
    if threading.current_thread() is not threading.main_thread():
        return None  # signal handlers can only be set from the main thread
    return signal.signal(signal.SIGTERM, _raise_keyboard_interrupt)


def _restore_sigterm(previous) -> None:
    if previous is not None and threading.current_thread() is threading.main_thread():
        signal.signal(signal.SIGTERM, previous)


def open_library(settings: Settings) -> sqlite3.Connection:
    """Open the library (creating or migrating it as needed) with the species catalog filled in, so the
    species are known from the first run: corrections and category rules work before any import."""
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    conn = db.connect(settings.db_path)
    repo.ensure_catalog(conn)
    return conn


def model_loader(settings: Settings) -> Callable[[], object | None]:
    """A loader for the real detector: None while the model file is missing, the Detector once it exists."""
    path = settings.data_dir / "models" / MODEL_FILENAME

    def load():
        if not path.exists():  # a cheap stat each pass, so a model dropped in later is picked up
            return None
        from fatball.recognition.detector import Detector

        return Detector(path)

    return load


def serve(settings: Settings, *, host: str, port: int, watcher_options: dict | None = None,
          banner: str = "", detector_loader: Callable[[], object | None] | None = None,
          features: Callable | None = None) -> None:
    """Run the watcher and the processor in background threads and the API in this one until Ctrl-C."""
    import uvicorn

    from fatball.api.app import create_app

    open_library(settings).close()  # once at startup, not per API request
    # One connection per thread: sqlite3 connections are not safe for concurrent use (the API opens its own).
    watcher_conn, processor_conn = (db.connect(settings.db_path) for _ in range(2))
    stop = threading.Event()
    watcher = Watcher(settings, watcher_conn, sleep=stop.wait, **(watcher_options or {}))
    extra = {} if features is None else {"features": features}
    processor = Processor(settings, processor_conn, detector_loader=detector_loader or model_loader(settings),
                          **extra)
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
    config = uvicorn.Config(create_app(settings, model_loaded=lambda: processor.has_detector), host=host, port=port, proxy_headers=False)
    # uvicorn shuts down gracefully on SIGTERM, then restores the previous handler and re-raises the
    # signal. With the default handler that kills the process before our clean-up runs, so install one
    # that turns SIGTERM into KeyboardInterrupt, like Ctrl-C (signal handlers run in the main thread).
    previous_sigterm = _install_sigterm_as_keyboard_interrupt()
    try:
        uvicorn.Server(config).run()
    except KeyboardInterrupt:
        pass
    finally:
        _restore_sigterm(previous_sigterm)
        watcher.stop()
        stop.set()
        for t in threads:
            t.join(timeout=15)
        for c in (watcher_conn, processor_conn):
            c.close()
        print("Stopped.")


DEMO_BANNER = """
  Who Ate the Fat Ball? - DEMO
  ----------------------------
  This is a demo with a pretend camera and {n} generated test-pattern clips over {days} days.
  Nothing here is real footage, the real camera is not contacted and nothing is kept: the demo's
  data lives in a temporary folder that is deleted when you stop it.
"""


def run_demo(*, host: str = "127.0.0.1", port: int, n_clips: int = 12, days: int = 2) -> None:
    print("Generating demo clips...")
    with tempfile.TemporaryDirectory(prefix="fatball-demo-") as tmp, \
            demo.build_demo_camera(n_clips=n_clips, days=days) as cam:
        settings = Settings(data_dir=Path(tmp), camera_port=cam.port)
        conn = db.connect(settings.db_path)
        repo.upsert_camera(conn, CAMERA_NAME, None, "127.0.0.1")
        demo.seed_examples(conn)
        conn.close()
        detector, features = demo.fake_recognition()
        serve(settings, host=host, port=port, watcher_options=demo.watcher_options(),
              detector_loader=lambda: detector, features=features,
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
    conn = open_library(settings)
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
                auth = auth_mod.Auth(lambda: db.connect(settings.db_path), lambda: datetime.now().astimezone())
                auth.set_edit_pin(pin)
                print("Edit PIN saved.")
                break
            print("The edit PIN must be exactly 4 digits.")
        else:
            print("Edit PIN not changed.")
            return 2
    finally:
        conn.close()
    return 0


# set-camera-password
def run_set_camera_password(
    settings: Settings,
    *,
    getpass_fn: Callable[[str], str] = getpass.getpass,
    get_password: Callable[[], str | None] = secrets.get_password,
    set_password: Callable[[str], None] = secrets.set_password,
    connect: Callable[..., XMClient] = XMClient,
) -> int:
    """Change the camera's own password, check it, then save it in the Keychain. Never echoes secrets.

    The new password is saved only once the camera has logged in with it, so the app and the camera can't
    end up disagreeing.
    """
    conn = open_library(settings)
    try:
        camera = repo.get_camera(conn)
    finally:
        conn.close()
    if camera is None or not camera.last_ip:
        print("The camera's IP address isn't known yet: run `fatball setup` (or `fatball serve`) first.")
        return 1
    host, port = camera.last_ip, settings.camera_port

    def logs_in(password: str) -> bool:
        try:
            with connect(host, port) as client:
                client.login(CAMERA_USER, password)
            return True
        except WrongPassword:
            return False

    old = get_password() or ""
    try:
        if not logs_in(old):
            print("The camera doesn't accept the saved password, so nothing was changed.")
            return 1
    except CameraUnreachable:
        print(f"Can't reach the camera at {host}. Wake it up (walk past it) and try again.")
        return 1

    new = getpass_fn("New camera password (typing is hidden): ")
    if len(new) < MIN_CAMERA_PASSWORD:
        print(f"Please use at least {MIN_CAMERA_PASSWORD} characters. Nothing was changed.")
        return 1
    if getpass_fn("Type it again: ") != new:
        print("The two didn't match. Nothing was changed.")
        return 1

    changed = False
    try:
        with connect(host, port) as client:
            client.login(CAMERA_USER, old)
            client.change_password(CAMERA_USER, old, new)
        changed = True
        works = logs_in(new)
        if not works:
            print("The camera didn't take the new password; it still uses the old one." if logs_in(old)
                  else "Unexpected: neither the old nor the new password works. Don't retry yet.")
            return 1
    except CameraUnreachable:
        if changed:  # the camera confirmed the change, so keep the app in step with it
            set_password(new)
            print("The camera took the new password and it's saved in the Keychain, but the camera went to "
                  "sleep before it could be checked.")
            return 0
        print("The camera went to sleep before the change. Wake it and run this again; nothing was changed.")
        return 1
    except CameraError as e:
        print(f"The camera didn't take the new password ({e}). Nothing else changed.")
        return 1
    set_password(new)
    print("Done: the camera now uses your new password, and it's saved in the Keychain for the app.")
    return 0


# examples-import
NO_EXAMPLES = ("person", "skip")


def run_examples_import(
    settings: Settings,
    csv_path: Path,
    *,
    detector_loader: Callable[[], object | None],
    features: Callable = feature_print,
) -> int:
    """Label each listed clip's confident animal detections from a `clip_id,label` CSV.

    Every row is checked first; on any problem nothing is written. Clips not yet recognised are then all
    recognised and put in visits, exactly as the processor does (which needs the detector), before anything
    is labelled: if any of them fails, it is reported and nothing is labelled. Runs at background priority."""
    qos.set_background_priority()
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if not {"clip_id", "label"} <= set(reader.fieldnames or ()):
            print("The CSV needs the columns clip_id,label.")
            return 1
        rows = [(r["clip_id"].strip(), r["label"].strip()) for r in reader]
    conn = open_library(settings)
    try:
        wanted: dict[int, str | None] = {}  # clip id -> label to give (None: adds no examples); last row wins
        errors: list[str] = []
        for n, (raw_id, name) in enumerate(rows, start=2):
            clip = repo.get_clip(conn, int(raw_id)) if raw_id.isdigit() else None
            if clip is None:
                errors.append(f"line {n}: unknown clip id {raw_id!r}")
                continue
            key = name.lower()
            if key in NO_EXAMPLES:
                label = None
            elif key == "dog":
                label = DOG
            elif key == "nothing":
                label = "nothing"
            else:
                label = repo.scientific_name_for(conn, name)
                if label is None:
                    errors.append(f"line {n}: unknown name {name!r}")
                    continue
            wanted[clip.id] = label
        todo = [i for i, label in wanted.items() if label is not None and not repo.is_recognized(conn, i)]
        for i in todo:
            if not repo.get_clip(conn, i).web_path:
                errors.append(f"clip {i} has no converted video to recognise")
        if errors:
            print("Nothing was written. Fix these and run it again:")
            for e in errors:
                print("  " + e)
            return 1
        if todo:
            try:
                detector = detector_loader()
            except Exception:
                log.exception("detector failed to load")
                detector = None
            if detector is None:
                print("These clips need recognising first, but the detector model isn't available "
                      "(run scripts/export_detector.py). Nothing was written:")
                print("  " + ", ".join(str(i) for i in todo))
                return 1
            recognizer = Recognizer(settings, conn, detector, features)
            failed = []
            for clip_id in todo:
                error = recognize_and_group(conn, recognizer, repo.get_clip(conn, clip_id))
                if error is not None:
                    failed.append(f"clip {clip_id}: {error}")
            if failed:
                print("These clips could not be recognised, so nothing was labelled. Run the import again, "
                      "or leave them out of the CSV:")
                for line in failed:
                    print("  " + line)
                return 1
        examples = clips = 0
        for clip_id, label in wanted.items():
            if label is None:
                continue
            n = repo.label_detections(conn, clip_id, label, "import")
            examples += n
            clips += n > 0
        print(f"{examples} examples from {clips} clips")
        return 0
    finally:
        conn.close()
