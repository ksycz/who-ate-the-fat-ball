import { describe, expect, it } from "vitest";
import type { Visit } from "../src/lib/api";
import { cameraStatus, clipBadge, durationText, sureChip, visitName, visitTime } from "../src/lib/format";

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
    expect(visitName(visit({ category: "other_animals", subject: "unknown" }))).toBe("Unknown animal");
  });
  it("names other things", () => {
    expect(visitName(visit({ category: "other", subject: "person" }))).toBe("Person");
    expect(visitName(visit({ category: "other", subject: "species", species: { scientific: "Canis lupus familiaris", name: "dog" } }))).toBe("Dog");
    expect(visitName(visit({ category: "other", subject: "nothing" }))).toBe("Empty clip");
  });
  it("falls back to the scientific name", () => {
    expect(visitName(visit({ species: { scientific: "Parus major", name: null } }))).toBe("Parus major");
  });
});

describe("cameraStatus", () => {
  const now = new Date(2026, 10, 2, 12, 0, 0);
  it("ok", () => {
    expect(cameraStatus({ state: "ok", last_seen_at: "2026-11-02T11:55:00", last_error: null }, now, "2026-11-02"))
      .toEqual({ dot: "ok", text: "Camera seen 5 min ago" });
    expect(cameraStatus({ state: "ok", last_seen_at: "2026-11-02T11:59:40", last_error: null }, now, "2026-11-02").text)
      .toBe("Camera seen just now");
  });
  it("asleep", () => {
    expect(cameraStatus({ state: "asleep", last_seen_at: "2026-11-02T06:10:00", last_error: null }, now, "2026-11-02"))
      .toEqual({ dot: "asleep", text: "Camera asleep · seen 06:10" });
  });
  it("problem", () => {
    expect(cameraStatus({ state: "problem", last_seen_at: "2026-11-01T18:40:00", last_error: "x" }, now, "2026-11-02"))
      .toEqual({ dot: "problem", text: "Camera not seen since yesterday 18:40 · Check App status" });
    expect(cameraStatus({ state: "problem", last_seen_at: "2026-11-02T08:05:00", last_error: "x" }, now, "2026-11-02").text)
      .toBe("Camera not seen since 08:05 · Check App status");
    expect(cameraStatus({ state: "problem", last_seen_at: "2026-10-31T18:40:00", last_error: "x" }, now, "2026-11-02").text)
      .toBe("Camera not seen since 31 Oct · Check App status");
    expect(cameraStatus({ state: "problem", last_seen_at: null, last_error: null }, now, "2026-11-02").text)
      .toBe("Camera not seen yet · Check App status");
  });
  it("problem_day_label_uses_the_servers_day_not_the_browser_clock", () => {
    // Browser clock says the 2nd; the server says the 3rd.
    expect(cameraStatus({ state: "problem", last_seen_at: "2026-11-02T18:40:00", last_error: "x" }, now, "2026-11-03").text)
      .toBe("Camera not seen since yesterday 18:40 · Check App status");
    expect(cameraStatus({ state: "problem", last_seen_at: "2026-11-02T18:40:00", last_error: "x" }, now, "2026-11-02").text)
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
