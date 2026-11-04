"""The service the Playwright tests run against: the real API and gallery over a small seeded library.

    uv run python scripts/e2e_server.py --data-dir .e2e-data --port 8765 [--empty] [--camera-problem]

It wipes DATA_DIR, seeds it with generated 2-second test-pattern clips (never real footage), and serves
`create_app` with a fixed clock of 2026-11-02 10:00 local time on 127.0.0.1, so requests come from the Mac
itself and editing works without the PIN.

  busy day (default)  today: 4 great tit visits (one with 2 clips), 2 blue tit, 1 nuthatch (a new species,
                      not watched), 1 unknown bird, 1 clip still being checked, 1 failed clip with its raw
                      file. Yesterday: 3 bird visits. 31 October: a dog, an empty clip and a red squirrel.
  --empty             only yesterday's 3 visits; the camera was seen two minutes ago.
  --camera-problem    the camera was last seen yesterday 18:40, with no error. Combine with --empty for
                      the "quiet day and a camera problem" state.

For tests that change data there is `POST /__e2e/reseed`, which wipes and seeds again in place.
"""

import argparse
import shutil
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import uvicorn

from fatball.config import Settings
from fatball.demo import make_xm_clip
from fatball.library import repo, today
from fatball.library.db import connect
from fatball.library.visits import assign_visit
from fatball.media.convert import ConvertedClip, convert_clip
from fatball.recognition.catalog import DOG
from fatball.recognition.matcher import Verdict
from fatball.recognition.recognizer import verdict_to_json

NOW = datetime(2026, 11, 2, 10, 0)
TODAY = NOW.date()
YESTERDAY = TODAY - timedelta(days=1)
EARLIER = TODAY - timedelta(days=2)

GREAT, BLUE, NUTHATCH = "Parus major", "Cyanistes caeruleus", "Sitta europaea"
SQUIRREL = "Sciurus vulgaris"
CLIP_SECONDS = 2


def sure(species: str, category: str = "birds", conf: float = 0.94, others: tuple = ()) -> Verdict:
    return Verdict(category, species, conf, [(species, conf), *others], "species", None)


UNKNOWN_BIRD = Verdict("birds", None, 0.4, [], "unknown", None)
EMPTY_CLIP = Verdict("other", None, 0.0, [], "nothing", None)


def at(day, hour: int, minute: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute)


def make_bases(work: Path) -> dict[str, ConvertedClip]:
    """Three converted test clips (different colours) that every seeded clip copies."""
    bases = {}
    for name, hue in (("a", 0), ("b", 120), ("c", 240)):
        raw = work / f"{name}.raw"
        raw.write_bytes(make_xm_clip(CLIP_SECONDS, source="testsrc2", hue=hue))
        bases[name] = convert_clip(raw, work / name)
    return bases


class Seeder:
    def __init__(self, settings: Settings, bases: dict[str, ConvertedClip]):
        self.settings = settings
        self.bases = bases
        self.conn = connect(settings.db_path)
        self.cam = 0
        self.n = 0

    def visit(self, begin: datetime, verdict: Verdict, *, base: str = "a", clips: int = 1, watched: bool = True) -> int:
        """A recognised visit of `clips` clips (20 s apart); returns the visit's id."""
        for k in range(clips):
            visit_id = self._clip(begin + timedelta(seconds=20 * k), verdict, base)
        if watched:
            today.mark_watched(self.conn, visit_id, NOW)
        return visit_id

    def _clip(self, begin: datetime, verdict: Verdict, base: str) -> int:
        self.n += 1
        conn, media, src = self.conn, self.settings.media_dir, self.bases[base]
        clip_id = repo.add_clip(conn, self.cam, f"/e2e/{self.n}.h265", begin, begin + timedelta(seconds=CLIP_SECONDS), "h264", 1)
        folder = media / "clips" / str(clip_id)
        folder.mkdir(parents=True)
        for f in (src.original, src.web, src.poster, src.preview, src.thumb):
            shutil.copy(f, folder / f.name)
        (media / "frames").mkdir(exist_ok=True)
        shutil.copy(src.poster, media / "frames" / f"{clip_id}.jpg")
        rel = f"clips/{clip_id}/"
        repo.set_clip_status(
            conn, clip_id, "ready", original_path=rel + src.original.name, web_path=rel + src.web.name,
            poster_path=rel + src.poster.name, preview_path=rel + src.preview.name, duration_s=src.duration_s,
        )
        repo.set_recognition(
            conn, clip_id, best_frame_path=f"frames/{clip_id}.jpg", verdict_json=verdict_to_json(verdict),
            recognized_at=begin,
        )
        conn.execute(
            "INSERT INTO detection(clip_id, frame_index, cls, conf, x1, y1, x2, y2, feature) "
            "VALUES (?, 0, 'animal', 0.9, 0, 0, 1, 1, ?)", (clip_id, b"\x00" * 8),
        )
        conn.commit()
        return assign_visit(conn, repo.get_clip(conn, clip_id), verdict)

    def pending_clip(self, begin: datetime, status: str, raw_name: str) -> None:
        """A clip that has not become a visit: 'downloaded' is still being checked, 'failed' has its raw file."""
        self.n += 1
        clip_id = repo.add_clip(
            self.conn, self.cam, f"/e2e/{self.n}.h265", begin, begin + timedelta(seconds=CLIP_SECONDS), "h264", 1
        )
        raw = self.settings.media_dir / "raw" / raw_name
        raw.parent.mkdir(parents=True, exist_ok=True)
        raw.write_bytes(make_xm_clip(CLIP_SECONDS, source="testsrc2", hue=240))
        repo.set_clip_status(self.conn, clip_id, status, raw_path=f"raw/{raw_name}")

    def seed(self, *, empty: bool, camera_problem: bool) -> None:
        repo.ensure_catalog(self.conn)
        self.cam = repo.upsert_camera(self.conn, "feeder", None, None)
        for hour, minute, species in ((16, 20, GREAT), (17, 5, GREAT), (17, 40, BLUE)):
            self.visit(at(YESTERDAY, hour, minute), sure(species), base="b" if species == BLUE else "a")
        if not empty:
            self.visit(at(EARLIER, 8, 15), sure(SQUIRREL, "other", 0.81), base="c")
            self.visit(at(EARLIER, 9, 5), sure(DOG, "other", 0.88), base="c")
            self.visit(at(EARLIER, 10, 40), EMPTY_CLIP, base="c")
            blue_alt = ((BLUE, 0.31),)
            self.visit(at(TODAY, 7, 10), sure(GREAT, others=blue_alt), clips=2)
            self.visit(at(TODAY, 7, 40), sure(BLUE), base="b")
            self.visit(at(TODAY, 8, 5), sure(GREAT, others=blue_alt))
            self.visit(at(TODAY, 8, 50), sure(GREAT, others=blue_alt))
            self.visit(at(TODAY, 9, 0), sure(BLUE), base="b")
            self.visit(at(TODAY, 9, 15), UNKNOWN_BIRD, base="c")
            self.visit(at(TODAY, 9, 30), sure(GREAT, others=blue_alt))
            self.visit(at(TODAY, 9, 45), sure(NUTHATCH, conf=0.87), base="b", watched=False)
            self.pending_clip(at(TODAY, 9, 20), "failed", "failed.raw")
            self.pending_clip(at(TODAY, 9, 55), "downloaded", "checking.raw")
        seen = at(YESTERDAY, 18, 40) if camera_problem else NOW - timedelta(minutes=2)
        repo.update_camera_status(self.conn, self.cam, last_seen_at=seen)
        self.conn.close()


MARKER = ".fatball-e2e"


def wipe(data_dir: Path) -> None:
    """Empty `data_dir`, but only if it is missing, empty, or was seeded by this script before."""
    if data_dir.resolve().name in ("", "WhoAteTheFatBall"):
        sys.exit("refusing to wipe a data directory that looks like the real library")
    if data_dir.exists() and any(data_dir.iterdir()) and not (data_dir / MARKER).exists():
        sys.exit(f"refusing to wipe {data_dir}: it is not empty and has no {MARKER} file from an earlier e2e run")
    data_dir.mkdir(parents=True, exist_ok=True)
    for child in data_dir.iterdir():
        shutil.rmtree(child) if child.is_dir() else child.unlink()
    (data_dir / MARKER).write_text("seeded by scripts/e2e_server.py\n")


def build(args, bases: dict[str, ConvertedClip]) -> Settings:
    settings = Settings(data_dir=args.data_dir.resolve())
    wipe(settings.data_dir)
    settings.media_dir.mkdir()
    Seeder(settings, bases).seed(empty=args.empty, camera_problem=args.camera_problem)
    return settings


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--empty", action="store_true")
    parser.add_argument("--camera-problem", action="store_true")
    args = parser.parse_args()
    from fatball.api.app import create_app

    work = Path(tempfile.mkdtemp(prefix="fatball-e2e-"))
    try:
        bases = make_bases(work)
        settings = build(args, bases)
        inner = create_app(settings, now=lambda: NOW.astimezone())

        async def app(scope, receive, send):
            if scope["type"] == "http" and scope["path"] == "/__e2e/reseed" and scope["method"] == "POST":
                build(args, bases)
                await send({"type": "http.response.start", "status": 204, "headers": []})
                await send({"type": "http.response.body", "body": b""})
                return
            await inner(scope, receive, send)

        uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
