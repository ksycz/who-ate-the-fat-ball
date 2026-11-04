import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import { get } from "svelte/store";
import VisitCard from "../src/components/VisitCard.svelte";
import NewSpeciesBanner from "../src/components/NewSpeciesBanner.svelte";
import Today from "../src/pages/Today.svelte";
import VisitList from "../src/pages/VisitList.svelte";
import { canEdit, changes, noteChanged, serverDay, showSaveFailure, toast } from "../src/lib/session";
import { ApiError, type Visit } from "../src/lib/api";
import { clearLists, loadList, loadTodayScroll, saveList, saveTodayScroll } from "../src/lib/listCache";
import { arrival } from "../src/lib/router";

function visit(over: Partial<Visit> = {}): Visit {
  return {
    id: 1,
    started_at: "2026-11-03T09:00:00+01:00",
    ended_at: "2026-11-03T09:02:10+01:00",
    category: "birds",
    species: { scientific: "Parus major", name: "great tit" },
    subject: "species",
    confidence: 0.94,
    is_favourite: false,
    best_frame_url: null,
    clip_count: 1,
    duration_s: 24,
    poster_url: null,
    preview_url: null,
    corrected: false,
    watched: true,
    ...over,
  };
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  arrival.viaHistory = false;
  clearLists();
});

describe("VisitCard sure chip", () => {
  it("shows_the_chip_for_a_plain_visit", () => {
    render(VisitCard, { visit: visit(), today: "2026-11-03" });
    expect(screen.getByText("94% sure")).toBeTruthy();
  });
  it("hides_the_chip_when_corrected", () => {
    render(VisitCard, { visit: visit({ corrected: true }), today: "2026-11-03" });
    expect(screen.queryByText(/sure/)).toBeNull();
  });
  it("hides_the_chip_without_a_species", () => {
    render(VisitCard, { visit: visit({ species: null, confidence: 0.4 }), today: "2026-11-03" });
    expect(screen.getByText("Unknown bird")).toBeTruthy();
    expect(screen.queryByText(/sure/)).toBeNull();
  });
});

describe("NewSpeciesBanner", () => {
  it("says_yesterday_for_an_earlier_day", () => {
    serverDay.set("2026-11-03");
    render(NewSpeciesBanner, {
      species: { visit_id: 4, scientific: "Sitta europaea", name: "nuthatch", started_at: "2026-11-02T16:20:00+01:00" },
    });
    expect(screen.getByText(/yesterday 16:20/)).toBeTruthy();
  });
});

describe("saving fails with 403", () => {
  beforeEach(() => {
    toast.set(null);
  });
  it("turns editing off", () => {
    canEdit.set(true);
    showSaveFailure(new ApiError(403, "no"));
    expect(get(canEdit)).toBe(false);
    expect(get(toast)?.unlock).toBe(true);
  });
  it("leaves editing on for other failures", () => {
    canEdit.set(true);
    showSaveFailure(new ApiError(500, "no"));
    expect(get(canEdit)).toBe(true);
  });
});

describe("listCache", () => {
  it("remembers_a_list_until_the_library_changes", () => {
    saveList("birds", { visits: [visit()], cursor: "c1", scrollY: 640 });
    expect(loadList("birds")).toEqual({ visits: [visit()], cursor: "c1", scrollY: 640 });
    expect(loadList("other")).toBeUndefined();
    noteChanged();
    expect(loadList("birds")).toBeUndefined();
  });
  it("remembers_where_today_was_scrolled", () => {
    saveTodayScroll(320);
    expect(loadTodayScroll()).toBe(320);
  });
});

describe("Today", () => {
  const data = {
    day: "2026-11-03",
    now: "2026-11-03T09:20:00+01:00",
    summary: { visits: 0, species: 0 },
    champion: null,
    new_species: null,
    visits: [],
    checking: [],
    failed: [],
    last_visitor: null,
    camera: { state: "ok", last_seen_at: "2026-11-03T09:15:00+01:00", last_error: null },
  };
  const todayCalls = (fetchMock: ReturnType<typeof vi.fn>) => fetchMock.mock.calls.filter((c) => c[0] === "/api/today").length;

  it("refetches_when_the_library_changes", async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify(data), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    render(Today);
    await screen.findByText("No visits yet");
    expect(todayCalls(fetchMock)).toBe(1);
    noteChanged();
    await waitFor(() => expect(todayCalls(fetchMock)).toBe(2));
  });

  it("shows_a_try_again_when_the_first_load_fails", async () => {
    let up = false;
    const fetchMock = vi.fn(async () =>
      up ? new Response(JSON.stringify(data), { status: 200 }) : Promise.reject(new TypeError("offline")),
    );
    vi.stubGlobal("fetch", fetchMock);
    render(Today);
    expect(await screen.findByText("Couldn't reach the app. Check the Wi-Fi and try again.")).toBeTruthy();
    up = true;
    await fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    await screen.findByText("No visits yet");
    expect(screen.queryByText(/Couldn't reach/)).toBeNull();
  });
});

describe("VisitList coming back", () => {
  const items = Array.from({ length: 3 }, (_, i) => visit({ id: 3 - i, started_at: `2026-11-03T09:0${i}:00+01:00` }));
  it("restores_items_and_scroll_after_Back_without_asking_again", async () => {
    serverDay.set("2026-11-03");
    saveList("birds", { visits: items, cursor: null, scrollY: 480 });
    arrival.viaHistory = true;
    const scrollTo = vi.fn();
    vi.stubGlobal("scrollTo", scrollTo);
    const fetchMock = vi.fn(async (url: string) =>
      url === "/api/today" ? new Response(JSON.stringify({ day: "2026-11-03", new_species: null }), { status: 200 }) : new Response("{}", { status: 404 }),
    );
    vi.stubGlobal("fetch", fetchMock);
    render(VisitList, { kind: "birds" });
    expect(screen.getAllByRole("link", { name: /Great tit/ })).toHaveLength(3);
    await waitFor(() => expect(scrollTo).toHaveBeenCalledWith(0, 480));
    expect(fetchMock.mock.calls.some((c) => String(c[0]).startsWith("/api/visits"))).toBe(false);
  });

  it("starts_fresh_when_opened_by_a_click", async () => {
    serverDay.set("2026-11-03");
    saveList("birds", { visits: items, cursor: null, scrollY: 480 });
    const fetchMock = vi.fn(async (url: string) =>
      String(url).startsWith("/api/visits")
        ? new Response(JSON.stringify({ items: [items[0]], next_cursor: null }), { status: 200 })
        : new Response(JSON.stringify({ day: "2026-11-03", new_species: null }), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);
    render(VisitList, { kind: "birds" });
    await waitFor(() => expect(screen.getAllByRole("link", { name: /Great tit/ })).toHaveLength(1));
  });
});

it("changes_counter_goes_up", () => {
  const before = get(changes);
  noteChanged();
  expect(get(changes)).toBe(before + 1);
});
