"""Read-only queries for Birds by species (period), Stats and the Videos feed. Birds only.

Days and hours come from the stored local-time ISO text (`started_at[:10]`, `started_at[11:13]`), never from a
UTC conversion, so a visit counts on the wall clock it happened on.
"""

import sqlite3
from datetime import date, timedelta
from typing import Literal

SLOTS = ["6–8 am", "8–10 am", "10 am–12 pm", "12–2 pm", "2–4 pm", "4–6 pm", "6–8 pm"]
FIRST_HOUR = 6
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
_PERIOD_DAYS = {"week": 7, "month": 30}
_NAMES = "LEFT JOIN species_name n ON n.species_id = s.id AND n.lang = 'en' "
_LOCAL_DAY = "substr(v.started_at, 1, 10)"


def _since(today: date, days: int) -> str:
    """First local date of a window of `days` days that ends today."""
    return (today - timedelta(days=days - 1)).isoformat()


def species_for_period(conn: sqlite3.Connection, today: date, period: Literal["week", "month", "all"]) -> list[dict]:
    """Birds seen in the period, most visits first. `last_seen_at` and `first_seen_at` are all-time; `is_new`
    means first seen within the last 7 days; `photo_path` is the best frame of the species' most confident
    visit in the period."""
    days = _PERIOD_DAYS.get(period)
    in_period = f" AND {_LOCAL_DAY} >= ?" if days else ""
    args = (_since(today, days),) if days else ()
    rows = conn.execute(
        "SELECT s.scientific_name, n.name, COUNT(*) AS visits, "
        "(SELECT MAX(a.started_at) FROM visit a WHERE a.species_id = s.id AND a.category = 'birds') AS last_seen_at, "
        "COALESCE(s.first_seen_at, (SELECT MIN(a.started_at) FROM visit a WHERE a.species_id = s.id "
        "AND a.category = 'birds')) AS first_seen_at, "
        "(SELECT p.best_frame_path FROM visit p WHERE p.species_id = s.id AND p.category = 'birds' "
        f"AND p.best_frame_path IS NOT NULL{in_period.replace('v.started_at', 'p.started_at')} "
        "ORDER BY p.confidence DESC, p.started_at DESC, p.id DESC LIMIT 1) AS photo_path "
        "FROM visit v JOIN species s ON s.id = v.species_id "
        f"{_NAMES}WHERE v.category = 'birds'{in_period} "
        "GROUP BY s.id ORDER BY visits DESC, n.name, s.id",
        (*args, *args),
    ).fetchall()
    new_since = _since(today, 7)
    return [
        {
            "scientific": r["scientific_name"], "name": r["name"], "visits": r["visits"],
            "last_seen_at": r["last_seen_at"], "first_seen_at": r["first_seen_at"],
            "is_new": r["first_seen_at"] is not None and r["first_seen_at"][:10] >= new_since,
            "photo_path": r["photo_path"],
        }
        for r in rows
    ]


def summary(conn: sqlite3.Connection, today: date, weeks: int) -> dict:
    """Bird visits over the last `weeks` weeks: totals, the busiest-times heatmap (Mon..Sun rows by time slot)
    and the visits per species, plus `unknown_visits` for the Unknown birds, so the bars add up to `visits`."""
    since, until = _since(today, weeks * 7), today.isoformat()
    window = f"v.category = 'birds' AND {_LOCAL_DAY} BETWEEN ? AND ?"
    totals = conn.execute(
        f"SELECT COUNT(*) AS visits, COUNT(DISTINCT v.species_id) AS species FROM visit v WHERE {window}",
        (since, until),
    ).fetchone()
    heatmap = [{"day": d, "cells": [0] * len(SLOTS)} for d in DAYS]
    last_hour = FIRST_HOUR + 2 * len(SLOTS)
    for r in conn.execute(
        "SELECT CAST(strftime('%w', substr(v.started_at, 1, 10)) AS INTEGER) AS wd, "
        "CAST(substr(v.started_at, 12, 2) AS INTEGER) AS hr, COUNT(*) AS n "
        f"FROM visit v WHERE {window} GROUP BY wd, hr",
        (since, until),
    ):
        if FIRST_HOUR <= r["hr"] < last_hour:
            heatmap[(r["wd"] + 6) % 7]["cells"][(r["hr"] - FIRST_HOUR) // 2] += r["n"]
    columns = [sum(row["cells"][i] for row in heatmap) for i in range(len(SLOTS))]
    busiest = SLOTS[columns.index(max(columns))] if any(columns) else None
    per_species = conn.execute(
        "SELECT s.scientific_name, n.name, COUNT(*) AS visits FROM visit v JOIN species s ON s.id = v.species_id "
        f"{_NAMES}WHERE {window} GROUP BY s.id ORDER BY visits DESC, n.name, s.id",
        (since, until),
    ).fetchall()
    return {
        "weeks": weeks, "visits": totals["visits"], "species": totals["species"], "busiest": busiest,
        "slots": SLOTS, "heatmap": heatmap,
        "per_species": [
            {"scientific": r["scientific_name"], "name": r["name"], "visits": r["visits"]} for r in per_species
        ],
        "unknown_visits": totals["visits"] - sum(r["visits"] for r in per_species),
    }
