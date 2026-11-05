"""Mac banners for new bird visits: a background loop that groups settled visits and shows them.

With terminal-notifier installed (`brew install terminal-notifier`), clicking a banner opens the gallery.
Without it, banners go through osascript, and macOS opens Script Editor on a click.
"""

import logging
import os
import shutil
import subprocess
import threading
from collections import Counter
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from pathlib import Path

from fatball.library import repo

log = logging.getLogger("fatball.notify")

TITLE = "Who Ate the Fat Ball?"
SETTING = "notifications"
SETTLE = timedelta(seconds=90)  # a visit may still grow while the bird is around
RECENT = timedelta(minutes=30)  # an older visit (a backfill, a Retry) is marked without a banner
SHOWN_NAMES = 3
NOT_AUTHORIZED = 3  # terminal-notifier's exit status when macOS hasn't allowed its notifications
# Where Homebrew puts it: a LaunchAgent's PATH has neither folder.
TERMINAL_NOTIFIER_PLACES = (Path("/opt/homebrew/bin/terminal-notifier"), Path("/usr/local/bin/terminal-notifier"))
_SCRIPT = "on run argv\ndisplay notification (item 2 of argv) with title (item 1 of argv)\nend run"


def messages(rows: Sequence) -> list[str]:
    """One summary line for the visits, then a line for each species seen for the first time."""
    if not rows:
        return []
    names = list(dict.fromkeys(r["species_name"] or "unknown bird" for r in rows))
    shown = ", ".join(names[:SHOWN_NAMES])
    if len(names) > SHOWN_NAMES:
        shown += f" and {len(names) - SHOWN_NAMES} more"
    n = len(rows)
    out = [f"{n} new visit{'' if n == 1 else 's'}: {shown}"]
    new = Counter(r["species_name"] for r in rows if r["is_new_species"] and r["species_name"])
    out += [f"New species: {name}" for name in new]
    return out


def terminal_notifier() -> str | None:
    """The terminal-notifier program, if installed."""
    found = shutil.which("terminal-notifier")
    if found:
        return found
    return next((str(p) for p in TERMINAL_NOTIFIER_PLACES if os.access(p, os.X_OK)), None)


def send_banner(title: str, body: str, url: str | None = None) -> None:
    """Show a macOS banner; with terminal-notifier, a click opens `url`. The text always goes in as separate
    arguments, never into a script. Failures are only logged."""
    tool = terminal_notifier()
    if tool is not None:
        cmd = [tool, "-title", title, "-message", body] + (["-open", url] if url else [])
        try:
            subprocess.run(cmd, check=True, timeout=10, capture_output=True)
            return
        except subprocess.CalledProcessError as exc:
            if exc.returncode == NOT_AUTHORIZED:
                log.warning("macOS isn't allowing terminal-notifier's banners; using osascript, so a click won't "
                            "open the gallery. Turn it on in System Settings > Notifications > terminal-notifier.")
            else:
                log.warning("terminal-notifier failed (%s); using osascript", exc)
        except (OSError, subprocess.SubprocessError) as exc:
            log.warning("terminal-notifier failed (%s); using osascript", exc)
    try:
        subprocess.run(["osascript", "-e", _SCRIPT, "--", title, body], check=True, timeout=10,
                       capture_output=True)
    except (OSError, subprocess.SubprocessError) as exc:
        log.warning("could not show a banner: %s", exc)


def notifier_loop(conn, stop: threading.Event, now: Callable[[], datetime], send=send_banner,
                  interval_s: float = 60) -> None:
    """Every pass: mark every settled visit notified, whatever its category, so a later move into Birds is never
    "new". Only bird visits that ended within RECENT get a banner; older ones (a backfill, a Retry) are marked
    silently. Visits are marked also when banners are off, so turning them back on doesn't flood. One failing
    pass never stops the loop."""
    while not stop.is_set():
        try:
            current = now()
            rows = repo.unnotified_visits(conn, current - SETTLE, current - RECENT)
            if rows:
                fresh = [r for r in rows if r["category"] == "birds" and r["is_recent"]]
                if fresh and (repo.get_setting(conn, SETTING) or "on") == "on":
                    for message in messages(fresh):
                        try:
                            send(TITLE, message)
                        except Exception:  # one lost banner must not make the others repeat every pass
                            log.exception("banner failed; carrying on")
                repo.mark_notified(conn, [r["id"] for r in rows], current)
        except Exception:
            log.exception("notification pass failed; retrying")
        stop.wait(interval_s)
