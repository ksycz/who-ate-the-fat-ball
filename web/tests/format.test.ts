import { describe, expect, it } from "vitest";
import type { Visit } from "../src/lib/api";
import { cameraStatus, dayHeading, minutesAgo, clipBadge, durationText, sizeText, sureChip, visitName, visitTime } from "../src/lib/format";

const TODAY = "2026-11-02";

describe("visitTime", () => {
  it("shows time and stay for today", () => {
    expect(visitTime("2026-11-02T09:12:00", "2026-11-02T09:14:10", TODAY)).toBe("09:12 · stayed 2 min");
  });
  it("handles under a minute", () => {
    expect(visitTime("2026-11-02T09:12:00", "2026-11-02T09:12:30", TODAY)).toBe("09:12 · stayed under 1 min");
  });
  it("labels yesterday and older days", () => {
    expect(visitTime("2026-11-01T09:12:00", "2026-11-01T09:14:10", TODAY)).toBe("Yesterday 09:12 · stayed 2 min");
    expect(visitTime("2026-10-31T09:12:00", "2026-10-31T09:14:10", TODAY)).toBe("31 Oct 09:12 · stayed 2 min");
  });
  it("keeps the wall-clock digits when an offset is present", () => {
    expect(visitTime("2026-11-02T09:12:00+01:00", "2026-11-02T09:14:10+01:00", TODAY)).toBe("09:12 · stayed 2 min");
  });
});

describe("clipBadge", () => {
  it("formats duration and count", () => {
    expect(clipBadge(24, 3)).toBe("▶ 0:24 · 3 clips");
    expect(clipBadge(9, 1)).toBe("▶ 0:09 · 1 clip");
    expect(clipBadge(65, 2)).toBe("▶ 1:05 · 2 clips");
  });
});

describe("durationText", () => {
  it("is m:ss", () => {
    expect(durationText(24)).toBe("0:24");
    expect(durationText(65)).toBe("1:05");
  });
});

describe("sureChip", () => {
  it("rounds to nearest, never 100%, null stays null", () => {
    expect(sureChip(0.94)).toBe("94% sure");
    expect(sureChip(0.999)).toBe("99% sure");
    expect(sureChip(0.57)).toBe("57% sure");
    expect(sureChip(null)).toBeNull();
  });
});

function visit(over: Partial<Visit>): Visit {
  return {
    id: 1, started_at: "", ended_at: "", category: "birds", species: null, subject: "species",
    confidence: null, is_favourite: false, best_frame_url: null, clip_count: 1, duration_s: null,
    poster_url: null, preview_url: null, corrected: false, watched: false, ...over,
  };
}

describe("visitName", () => {
  it("capitalises species names", () => {
    expect(visitName(visit({ species: { scientific: "Parus major", name: "great tit" } }))).toBe("Great tit");
  });
  it("names unknowns by category", () => {
    expect(visitName(visit({ category: "birds", subject: "unknown" }))).toBe("Unknown bird");
  });
  it("names other things", () => {
    expect(visitName(visit({ category: "other", subject: "person" }))).toBe("Person");
    expect(visitName(visit({ category: "other", subject: "species", species: { scientific: "Canis lupus familiaris", name: "dog" } }))).toBe("Dog");
    expect(visitName(visit({ category: "other", subject: "nothing" }))).toBe("Empty clip");
  });
  it("calls a plain move to Other just Other, never an empty clip", () => {
    expect(visitName(visit({ category: "other", subject: "unknown" }))).toBe("Other");
  });
  it("falls back to the scientific name", () => {
    expect(visitName(visit({ species: { scientific: "Parus major", name: null } }))).toBe("Parus major");
  });
});

describe("minutesAgo", () => {
  const serverNow = "2026-11-02T12:00:00+01:00";
  it("counts from the server's clock", () => {
    expect(minutesAgo("2026-11-02T11:55:00+01:00", serverNow, 1000, 1000)).toBe(5);
    expect(minutesAgo("2026-11-02T11:59:40+01:00", serverNow, 1000, 1000)).toBe(0);
  });
  it("adds the time since the response arrived, never the browser's own date", () => {
    // 2 minutes passed on this device since the response: 5 + 2.
    expect(minutesAgo("2026-11-02T11:55:00+01:00", serverNow, 1000, 1000 + 120_000)).toBe(7);
    // A browser clock years off changes nothing: only the difference between the two readings counts.
    expect(minutesAgo("2026-11-02T11:55:00+01:00", serverNow, 5_000_000_000, 5_000_000_000)).toBe(5);
  });
  it("never goes below zero", () => {
    expect(minutesAgo("2026-11-02T12:00:30+01:00", serverNow, 0, 0)).toBe(0);
  });
});

describe("cameraStatus", () => {
  const clock = { serverNow: "2026-11-02T12:00:00+01:00", fetchedAt: 0, nowMs: 0 };
  const TODAY_ = "2026-11-02";
  it("ok", () => {
    expect(cameraStatus({ state: "ok", last_seen_at: "2026-11-02T11:55:00+01:00", last_error: null }, TODAY_, clock))
      .toEqual({ dot: "ok", text: "Camera seen 5 min ago" });
    expect(cameraStatus({ state: "ok", last_seen_at: "2026-11-02T11:59:40+01:00", last_error: null }, TODAY_, clock).text)
      .toBe("Camera seen just now");
    expect(cameraStatus({ state: "ok", last_seen_at: "2026-11-02T10:30:00+01:00", last_error: null }, TODAY_, clock).text)
      .toBe("Camera seen 90 min ago");
  });
  it("ok keeps counting while the page waits for the next refresh", () => {
    const later = { ...clock, nowMs: 3 * 60_000 };
    expect(cameraStatus({ state: "ok", last_seen_at: "2026-11-02T11:55:00+01:00", last_error: null }, TODAY_, later).text)
      .toBe("Camera seen 8 min ago");
  });
  it("asleep", () => {
    expect(cameraStatus({ state: "asleep", last_seen_at: "2026-11-02T06:10:00+01:00", last_error: null }, TODAY_, clock))
      .toEqual({ dot: "asleep", text: "Camera asleep · seen 06:10" });
    expect(cameraStatus({ state: "asleep", last_seen_at: "2026-11-01T18:40:00+01:00", last_error: null }, TODAY_, clock).text)
      .toBe("Camera asleep · since yesterday 18:40");
  });
  it("problem", () => {
    expect(cameraStatus({ state: "problem", last_seen_at: "2026-11-01T18:40:00+01:00", last_error: "x" }, TODAY_, clock))
      .toEqual({ dot: "problem", text: "Camera not seen since yesterday 18:40 · Check App status" });
    expect(cameraStatus({ state: "problem", last_seen_at: "2026-11-02T08:05:00+01:00", last_error: "x" }, TODAY_, clock).text)
      .toBe("Camera not seen since 08:05 · Check App status");
    expect(cameraStatus({ state: "problem", last_seen_at: "2026-10-31T18:40:00+01:00", last_error: "x" }, TODAY_, clock).text)
      .toBe("Camera not seen since 31 Oct · Check App status");
    expect(cameraStatus({ state: "problem", last_seen_at: null, last_error: null }, TODAY_, clock).text)
      .toBe("Camera not seen yet · Check App status");
  });
  it("problem_day_label_uses_the_servers_day_not_the_browser_clock", () => {
    expect(cameraStatus({ state: "problem", last_seen_at: "2026-11-02T18:40:00+01:00", last_error: "x" }, "2026-11-03", clock).text)
      .toBe("Camera not seen since yesterday 18:40 · Check App status");
    expect(cameraStatus({ state: "problem", last_seen_at: "2026-11-02T18:40:00+01:00", last_error: "x" }, "2026-11-02", clock).text)
      .toBe("Camera not seen since 18:40 · Check App status");
  });
});

describe("clipBadge without a duration", () => {
  it("shows just the clip count", async () => {
    const { clipBadge } = await import("../src/lib/format");
    expect(clipBadge(null, 3)).toBe("▶ 3 clips");
    expect(clipBadge(null, 1)).toBe("▶ 1 clip");
  });
});

describe("whenText", () => {
  it("says today, yesterday or the date", async () => {
    const { whenText } = await import("../src/lib/format");
    expect(whenText("2026-11-03T06:10:00+01:00", "2026-11-03")).toBe("06:10");
    expect(whenText("2026-11-02T16:20:00+01:00", "2026-11-03")).toBe("yesterday 16:20");
    expect(whenText("2026-10-20T16:20:00+01:00", "2026-11-03")).toBe("20 Oct 16:20");
  });
});

describe("dayHeading", () => {
  it("names_today_and_yesterday_and_older_days", () => {
    expect(dayHeading("2026-11-03", "2026-11-03")).toBe("Today");
    expect(dayHeading("2026-11-02", "2026-11-03")).toBe("Yesterday");
    expect(dayHeading("2026-10-31", "2026-11-03")).toBe("Saturday 31 October");
  });
  it("works_across_month_and_year_boundaries", () => {
    expect(dayHeading("2026-10-31", "2026-11-01")).toBe("Yesterday");
    expect(dayHeading("2025-12-31", "2026-01-01")).toBe("Yesterday");
    expect(dayHeading("2025-12-30", "2026-01-01")).toBe("Tuesday 30 December");
  });
});

describe("plural and correctionText", () => {
  it("plural_counts_0_1_2", async () => {
    const { plural } = await import("../src/lib/format");
    expect(plural(0, "clip")).toBe("0 clips");
    expect(plural(1, "clip")).toBe("1 clip");
    expect(plural(2, "clip")).toBe("2 clips");
  });

  it("correctionText_says_moved_only_when_the_list_changes", async () => {
    const { correctionText } = await import("../src/lib/format");
    expect(correctionText("birds", "other", "Dog")).toBe("Moved to Other");
    expect(correctionText("birds", "other", "x")).toBe("Moved to Other");
    expect(correctionText("birds", "birds", "Blue tit")).toBe("Changed to Blue tit");
  });
});

describe("sizeText", () => {
  it("is decimal: KB below 1 MB, one decimal from 1 MB", () => {
    expect(sizeText(820_000)).toBe("820 KB");
    expect(sizeText(14_200_000)).toBe("14.2 MB");
    expect(sizeText(1_300_000_000)).toBe("1.3 GB");
  });
  it("picks the unit after rounding", () => {
    expect(sizeText(999_999)).toBe("1.0 MB");
    expect(sizeText(999_960_000)).toBe("1.0 GB");
  });
  it("copes with tiny sizes", () => {
    expect(sizeText(0)).toBe("0 KB");
    expect(sizeText(300)).toBe("1 KB");
  });
});
