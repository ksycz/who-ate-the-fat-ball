import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import Visit from "../src/pages/Visit.svelte";
import { route } from "../src/lib/router";
import { canEdit, NETWORK_TEXT, serverDay, toast } from "../src/lib/session";
import type { Clip, VisitDetail as Detail } from "../src/lib/api";

function clip(id: number, over: Partial<Clip> = {}): Clip {
  return {
    id,
    begin_at: `2026-11-03T09:0${id}:00+01:00`,
    end_at: `2026-11-03T09:0${id}:10+01:00`,
    kind: "video",
    duration_s: 10,
    web_url: `/media/web/${id}.mp4`,
    original_url: `/media/orig/${id}.mp4`,
    poster_url: `/media/c${id}.jpg`,
    preview_url: null,
    ...over,
  };
}

function detail(over: Partial<Detail> = {}): Detail {
  return {
    id: 5,
    started_at: "2026-11-03T09:00:00+01:00",
    ended_at: "2026-11-03T09:02:10+01:00",
    category: "birds",
    species: { scientific: "Parus major", name: "great tit" },
    subject: "species",
    confidence: 0.94,
    is_favourite: false,
    best_frame_url: "/media/frames/5.jpg",
    clip_count: 2,
    duration_s: 20,
    poster_url: "/media/c1.jpg",
    preview_url: null,
    corrected: false,
    watched: false,
    clips: [clip(1), clip(2)],
    guesses: [
      { scientific: "Parus major", name: "great tit", confidence: 0.94 },
      { scientific: "Cyanistes caeruleus", name: "blue tit", confidence: 0.04 },
      { scientific: "Passer domesticus", name: "house sparrow", confidence: 0.01 },
    ],
    ...over,
  };
}

let fetchMock: ReturnType<typeof vi.fn>;
let current: Detail;
let serverDayFromApi = "2026-11-03";
let statusDown = false;
let patchDown = false;
function serve(data: Detail, patched?: Partial<Detail>) {
  current = data;
  fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === "/api/visits/5" && (!init || init.method === "GET")) return new Response(JSON.stringify(current), { status: 200 });
    if (url === "/api/visits/5" && init?.method === "PATCH") {
      if (patchDown) throw new TypeError("Failed to fetch");
      current = { ...current, ...patched };
      return new Response(JSON.stringify({ undo_token: "tok1" }), { status: 200 });
    }
    if (url === "/api/status") {
      if (statusDown) throw new TypeError("Failed to fetch");
      return new Response(JSON.stringify({ day: serverDayFromApi }), { status: 200 });
    }
    if (url === "/api/visits/5/watched") return new Response(null, { status: 204 });
    return new Response(JSON.stringify({ detail: "not found" }), { status: 404 });
  });
  vi.stubGlobal("fetch", fetchMock);
}

function video(): HTMLVideoElement {
  return document.querySelector("video") as HTMLVideoElement;
}

beforeEach(() => {
  statusDown = false;
  patchDown = false;
  canEdit.set(true);
  toast.set(null);
  serverDay.set("2026-11-03");
  route.set({ name: "visit", params: { id: "5" } });
  vi.spyOn(HTMLMediaElement.prototype, "play").mockImplementation(() => Promise.resolve());
  vi.spyOn(HTMLMediaElement.prototype, "load").mockImplementation(() => {});
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("Visit", () => {
  it("marks_playing_clip_and_advances_on_end", async () => {
    serve(detail());
    render(Visit);
    await screen.findByRole("heading", { name: "Great tit" });
    const items = screen.getAllByRole("button", { name: /^Clip \d/ });
    expect(items).toHaveLength(2);
    expect(items[0].getAttribute("aria-current")).toBe("true");
    expect(items[0].textContent).toContain("playing");
    expect(items[1].hasAttribute("aria-current")).toBe(false);
    expect(video().getAttribute("src")).toBe("/media/web/1.mp4");
    expect(video().getAttribute("poster")).toBe("/media/c1.jpg");

    await fireEvent(video(), new Event("ended"));
    await waitFor(() => expect(video().getAttribute("src")).toBe("/media/web/2.mp4"));
    expect(items[1].getAttribute("aria-current")).toBe("true");
    expect(items[1].textContent).toContain("playing");
    expect(items[0].textContent).not.toContain("playing");

    await fireEvent.click(items[0]);
    await waitFor(() => expect(video().getAttribute("src")).toBe("/media/web/1.mp4"));
    expect(items[0].getAttribute("aria-current")).toBe("true");
  });

  it("watched_posted_once_on_first_play", async () => {
    serve(detail());
    render(Visit);
    await screen.findByRole("heading", { name: "Great tit" });
    await fireEvent(video(), new Event("play"));
    await fireEvent(video(), new Event("play"));
    await waitFor(() => {
      const posts = fetchMock.mock.calls.filter((c) => c[0] === "/api/visits/5/watched");
      expect(posts).toHaveLength(1);
      expect(posts[0][1].method).toBe("POST");
    });
  });

  it("or_maybe_tap_patches_species_and_toasts_changed_to", async () => {
    serve(detail());
    render(Visit);
    const pick = await screen.findByRole("button", { name: "Blue tit · 4%" });
    expect(screen.queryByRole("button", { name: /House sparrow/ })).not.toBeNull();
    await fireEvent.click(pick);
    await waitFor(() => expect(get(toast)).toEqual({ text: "Changed to Blue tit", undoToken: "tok1" }));
    const patch = fetchMock.mock.calls.find((c) => c[1]?.method === "PATCH")!;
    expect(JSON.parse(patch[1].body)).toEqual({ species: "Cyanistes caeruleus" });
  });

  it("or_maybe_toast_says_moved_to_when_category_changes", async () => {
    serve(detail(), { category: "other_animals", species: { scientific: "Cyanistes caeruleus", name: "blue tit" } });
    render(Visit);
    await fireEvent.click(await screen.findByRole("button", { name: "Blue tit · 4%" }));
    await waitFor(() => expect(get(toast)).toEqual({ text: "Moved to Other animals", undoToken: "tok1" }));
  });

  it("favourite_toggle_patches_and_toasts", async () => {
    serve(detail(), { is_favourite: true });
    render(Visit);
    const star = await screen.findByRole("button", { name: /Favourite/ });
    expect(star.getAttribute("aria-pressed")).toBe("false");
    await fireEvent.click(star);
    await waitFor(() => expect(get(toast)).toEqual({ text: "Added to Favourites", undoToken: "tok1" }));
    expect(star.getAttribute("aria-pressed")).toBe("true");
    const patch = fetchMock.mock.calls.find((c) => c[1]?.method === "PATCH")!;
    expect(JSON.parse(patch[1].body)).toEqual({ is_favourite: true });
  });

  it("editor_sees_not_right_change", async () => {
    serve(detail());
    render(Visit);
    expect(await screen.findByRole("button", { name: "Not right? Change" })).toBeTruthy();
  });

  it("locked_device_has_no_change_or_favourite_controls", async () => {
    canEdit.set(false);
    serve(detail());
    render(Visit);
    await screen.findByRole("heading", { name: "Great tit" });
    expect(screen.queryByRole("button", { name: "Not right? Change" })).toBeNull();
    expect(screen.queryByRole("button", { name: /Favourite/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /Blue tit/ })).toBeNull();
    expect(screen.getByText(/Blue tit · 4%/)).toBeTruthy();
    expect(screen.getByRole("button", { name: /Download/ })).toBeTruthy();
  });

  it("corrected_replaces_the_sure_chip", async () => {
    serve(detail({ corrected: true }));
    render(Visit);
    expect(await screen.findByText("Corrected by you")).toBeTruthy();
    expect(screen.queryByText("94% sure")).toBeNull();
  });

  it("uses_the_servers_day_for_the_time_prefix", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date(2026, 10, 2, 12, 0));
    serverDay.set(null);
    serverDayFromApi = "2026-11-03";
    serve(detail({ started_at: "2026-11-02T09:00:00+01:00", ended_at: "2026-11-02T09:02:10+01:00" }));
    render(Visit);
    expect(await screen.findByText(/Yesterday 09:00 · stayed 2 min/)).toBeTruthy();
    vi.useRealTimers();
  });

  it("onended_skips_clips_that_are_not_ready", async () => {
    serve(detail({ clips: [clip(1), clip(2, { web_url: null }), clip(3)] }));
    render(Visit);
    await screen.findByRole("heading", { name: "Great tit" });
    await fireEvent(video(), new Event("ended"));
    await waitFor(() => expect(video().getAttribute("src")).toBe("/media/web/3.mp4"));
    const items = screen.getAllByRole("button", { name: /^Clip \d/ });
    expect(items[2].getAttribute("aria-current")).toBe("true");
  });

  it("onended_stops_after_the_last_ready_clip", async () => {
    serve(detail({ clips: [clip(1), clip(2, { web_url: null })] }));
    render(Visit);
    await screen.findByRole("heading", { name: "Great tit" });
    await fireEvent(video(), new Event("ended"));
    expect(video().getAttribute("src")).toBe("/media/web/1.mp4");
  });

  it("no_download_menu_without_a_video_or_a_photo", async () => {
    serve(detail({ best_frame_url: null, clips: [clip(1, { web_url: null })] }));
    render(Visit);
    await screen.findByText("Video not ready yet");
    expect(screen.queryByRole("button", { name: /Download/ })).toBeNull();
  });

  it("download_menu_stays_for_a_photo_alone", async () => {
    serve(detail({ clips: [clip(1, { web_url: null })] }));
    render(Visit);
    await fireEvent.click(await screen.findByRole("button", { name: /Download/ }));
    expect(screen.queryByRole("link", { name: "Video (.mp4)" })).toBeNull();
    expect(screen.getByRole("link", { name: "Photo (.jpg)" })).toBeTruthy();
  });

  it("failed_patch_toast_says_check_the_wifi_on_a_network_error", async () => {
    serve(detail());
    patchDown = true;
    render(Visit);
    await fireEvent.click(await screen.findByRole("button", { name: "Blue tit · 4%" }));
    await waitFor(() => expect(get(toast)).toEqual({ text: NETWORK_TEXT }));
  });

  it("time_line_shows_when_the_status_request_fails", async () => {
    serverDay.set(null);
    statusDown = true;
    serve(detail());
    render(Visit);
    // No server day to judge by, so the visit's own date stands in: the time and stay still show.
    expect(await screen.findByText(/09:00 · stayed 2 min/)).toBeTruthy();
  });

  it("or_maybe_is_hidden_on_a_corrected_visit", async () => {
    serve(detail({ corrected: true }));
    render(Visit);
    await screen.findByText("Corrected by you");
    expect(screen.queryByText("Or maybe")).toBeNull();
    expect(screen.queryByRole("button", { name: /Blue tit/ })).toBeNull();
  });

  it("escape_closes_download_menu_and_returns_focus", async () => {
    serve(detail());
    render(Visit);
    const btn = await screen.findByRole("button", { name: /Download/ });
    await fireEvent.click(btn);
    screen.getByRole("link", { name: "Photo (.jpg)" }).focus();
    await fireEvent.keyDown(window, { key: "Escape" });
    expect(btn.getAttribute("aria-expanded")).toBe("false");
    expect(document.activeElement).toBe(btn);
  });

  it("clip_without_web_video_says_not_ready", async () => {
    serve(detail({ clips: [clip(1, { web_url: null }), clip(2)] }));
    render(Visit);
    expect(await screen.findByText("Video not ready yet")).toBeTruthy();
    expect(document.querySelector("video")).toBeNull();
  });

  it("download_menu_links_point_at_media", async () => {
    serve(detail());
    render(Visit);
    const btn = await screen.findByRole("button", { name: /Download/ });
    expect(btn.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByRole("link", { name: "Video (.mp4)" })).toBeNull();
    await fireEvent.click(btn);
    expect(btn.getAttribute("aria-expanded")).toBe("true");
    const v = screen.getByRole("link", { name: "Video (.mp4)" });
    const p = screen.getByRole("link", { name: "Photo (.jpg)" });
    expect(v.getAttribute("href")).toBe("/media/web/1.mp4");
    expect(v.hasAttribute("download")).toBe(true);
    expect(p.getAttribute("href")).toBe("/media/frames/5.jpg");
    expect(p.hasAttribute("download")).toBe(true);
    await fireEvent.keyDown(window, { key: "Escape" });
    expect(btn.getAttribute("aria-expanded")).toBe("false");
    await fireEvent.click(btn);
    await fireEvent.click(document.body);
    expect(btn.getAttribute("aria-expanded")).toBe("false");
  });

  it("unknown_visit_shows_message", async () => {
    route.set({ name: "visit", params: { id: "999" } });
    serve(detail());
    render(Visit);
    expect(await screen.findByText("This visit doesn't exist any more")).toBeTruthy();
    expect(screen.getByRole("link", { name: /Today/ }).getAttribute("href")).toBe("/");
  });
});

import { get } from "svelte/store";
