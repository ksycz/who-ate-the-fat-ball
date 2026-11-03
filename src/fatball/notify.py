"""Mac banners for new bird visits: a background loop that groups settled visits and shows them via osascript."""

import logging
import subprocess
import threading
from collections import Counter
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta

from fatball.library import repo

log = logging.getLogger("fatball.notify")

TITLE = "Who Ate the Fat Ball?"
SETTING = "notifications"
SETTLE = timedelta(seconds=90)  # a visit may still grow while the bird is around
SHOWN_NAMES = 3
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


def send_banner(title: str, body: str) -> None:
    """Show a macOS banner. The text goes in as arguments, never into the script. Failures are only logged."""
    try:
        subprocess.run(["osascript", "-e", _SCRIPT, "--", title, body], check=True, timeout=10,
                       capture_output=True)
    except (OSError, subprocess.SubprocessError) as exc:
        log.warning("could not show a banner: %s", exc)


def notifier_loop(conn, stop: threading.Event, now: Callable[[], datetime], send=send_banner,
                  interval_s: float = 60) -> None:
    """Every pass: banner the bird visits that have settled, then mark them notified (also when banners are
    off, so turning them back on doesn't flood). One failing pass never stops the loop."""
    while not stop.is_set():
        try:
            current = now()
            rows = repo.unnotified_bird_visits(conn, current - SETTLE)
            if rows:
                if (repo.get_setting(conn, SETTING) or "on") == "on":
                    for message in messages(rows):
                        try:
                            send(TITLE, message)
                        except Exception:  # one lost banner must not make the others repeat every pass
                            log.exception("banner failed; carrying on")
                repo.mark_notified(conn, [r["id"] for r in rows], current)
        except Exception:
            log.exception("notification pass failed; retrying")
        stop.wait(interval_s)
