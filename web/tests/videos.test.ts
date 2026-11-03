import { tick } from "svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import Videos from "../src/pages/Videos.svelte";
import { canEdit, serverDay, toast } from "../src/lib/session";
import type { Visit } from "../src/lib/api";

type Item = Visit & { video_url: string; video_clip_id: number };

function item(id: number, over: Partial<Item> = {}): Item {
  return {
    id,
    started_at: `2026-11-03T09:${String(60 - id).padStart(2, "0")}:00+01:00`,
    ended_at: `2026-11-03T09:${String(60 - id).padStart(2, "0")}:30+01:00`,
    category: "birds",
    species: { scientific: "Parus major", name: "great tit" },
    subject: "species",
    confidence: 0.94,
    is_favourite: false,
    best_frame_url: `/media/frames/${id}.jpg`,
    clip_count: 1,
    duration_s: 10,
    poster_url: `/media/c${id}.jpg`,
    preview_url: null,
    corrected: false,
    watched: true,
    video_url: `/media/web/${id}.mp4`,
    video_clip_id: id,
    ...over,
  };
}

interface Page {
  items: Item[];
  next_cursor: string | null;
  total: number;
  filters: { scientific: string; name: string | null }[];
}
const FILTERS = [
  { scientific: "Parus major", name: "great tit" },
  { scientific: "Cyanistes caeruleus", name: "blue tit" },
];

let fetchMock: ReturnType<typeof vi.fn>;
let pages: Record<string, Page>; // keyed by "cursor|species"
function serve(first: Page, more: Record<string, Page> = {}) {
  pages = { "|": first, ...more };
  fetchMock = vi.fn(async (url: string) => {
    if (url.startsWith("/api/videos")) {
      const q = new URL(url, "http://x").searchParams;
      const page = pages[`${q.get("cursor") ?? ""}|${q.get("species") ?? ""}`];
      if (!page) return new Response("{}", { status: 404 });
      return new Response(JSON.stringify(page), { status: 200 });
    }
    return new Response("{}", { status: 404 });
  });
  vi.stubGlobal("fetch", fetchMock);
}

const three = (over: Partial<Page> = {}): Page => ({
  items: [item(1), item(2), item(3)],
  next_cursor: null,
  total: 3,
  filters: FILTERS,
  ...over,
});

const video = () => document.querySelector("video") as HTMLVideoElement;
const feed = () => screen.getByRole("region", { name: "Videos feed" });
const position = () => screen.getByText(/^\d+ of \d+$/).textContent;

// jsdom has no PointerEvent: a MouseEvent with the pointer name carries the coordinates.
async function swipe(from: [number, number], to: [number, number], target: Element = feed()) {
  target.dispatchEvent(new MouseEvent("pointerdown", { clientX: from[0], clientY: from[1], bubbles: true }));
  target.dispatchEvent(new MouseEvent("pointerup", { clientX: to[0], clientY: to[1], bubbles: true }));
  await tick();
}

beforeEach(() => {
  canEdit.set(true);
  toast.set(null);
  serverDay.set("2026-11-03");
  vi.spyOn(HTMLMediaElement.prototype, "play").mockImplementation(() => Promise.resolve());
  vi.spyOn(HTMLMediaElement.prototype, "load").mockImplementation(() => {});
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("Videos", () => {
  it("shows_the_position_from_the_total_and_the_first_video", async () => {
    serve(three({ total: 12, next_cursor: "c2" }));
    render(Videos);
    await screen.findByText("1 of 12");
    expect(video().getAttribute("src")).toBe("/media/web/1.mp4");
    expect(video().getAttribute("poster")).toBe("/media/c1.jpg");
    expect(video().hasAttribute("controls")).toBe(true);
    expect(video().hasAttribute("autoplay")).toBe(true);
    expect(video().muted).toBe(true);
    expect(document.querySelectorAll("video")).toHaveLength(1);
    expect(screen.getByRole("button", { name: "All birds" }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByRole("button", { name: "Blue tit" })).toBeTruthy();
  });

  it("next_moves_on_and_previous_goes_back_without_wrapping", async () => {
    serve(three());
    render(Videos);
    await screen.findByText("1 of 3");
    expect((screen.getByRole("button", { name: "Previous" }) as HTMLButtonElement).disabled).toBe(true);
    await fireEvent.click(screen.getByRole("button", { name: "Next clip" }));
    expect(position()).toBe("2 of 3");
    expect(video().getAttribute("src")).toBe("/media/web/2.mp4");
    await fireEvent.click(screen.getByRole("button", { name: "Previous" }));
    expect(position()).toBe("1 of 3");
  });

  it("disables_next_on_the_last_visit_when_there_is_no_cursor", async () => {
    serve(three());
    render(Videos);
    await screen.findByText("1 of 3");
    const next = screen.getByRole("button", { name: "Next clip" }) as HTMLButtonElement;
    await fireEvent.click(next);
    await fireEvent.click(next);
    expect(position()).toBe("3 of 3");
    expect(next.disabled).toBe(true);
    await fireEvent.keyDown(window, { key: "ArrowRight" });
    expect(position()).toBe("3 of 3");
  });

  it("fetches_the_next_page_when_next_is_pressed_on_the_last_loaded_item", async () => {
    serve(three({ total: 5, next_cursor: "c2" }), {
      "c2|": { items: [item(4), item(5)], next_cursor: null, total: 5, filters: FILTERS },
    });
    render(Videos);
    await screen.findByText("1 of 5");
    const next = screen.getByRole("button", { name: "Next clip" }) as HTMLButtonElement;
    await fireEvent.click(next);
    await fireEvent.click(next);
    expect(position()).toBe("3 of 5");
    expect(next.disabled).toBe(false);
    await fireEvent.click(next);
    await waitFor(() => expect(position()).toBe("4 of 5"));
    expect(fetchMock.mock.calls.some((c) => String(c[0]).includes("cursor=c2"))).toBe(true);
    expect(video().getAttribute("src")).toBe("/media/web/4.mp4");
  });

  it("a_swipe_over_50px_moves_and_one_under_does_not", async () => {
    serve(three());
    render(Videos);
    await screen.findByText("1 of 3");
    await swipe([200, 300], [170, 300]); // 30px left: nothing
    expect(position()).toBe("1 of 3");
    await swipe([200, 300], [120, 300]); // left: next
    expect(position()).toBe("2 of 3");
    await swipe([200, 300], [200, 230]); // up: next
    expect(position()).toBe("3 of 3");
    await swipe([100, 300], [200, 310]); // right: previous
    expect(position()).toBe("2 of 3");
    await swipe([200, 300], [205, 400]); // down: previous
    expect(position()).toBe("1 of 3");
  });

  it("uses_the_dominant_axis_and_leaves_the_controls_bar_to_scrubbing", async () => {
    serve(three());
    render(Videos);
    await screen.findByText("1 of 3");
    await swipe([200, 300], [140, 380]); // mostly down: previous, so nothing at the first item
    expect(position()).toBe("1 of 3");
    vi.spyOn(video(), "getBoundingClientRect").mockReturnValue({ top: 0, bottom: 400, left: 0, right: 300, width: 300, height: 400, x: 0, y: 0, toJSON() {} });
    await swipe([250, 380], [100, 380], video()); // started on the controls bar
    expect(position()).toBe("1 of 3");
    await swipe([250, 200], [100, 200], video()); // started on the picture
    expect(position()).toBe("2 of 3");
  });

  it("arrow_keys_move_but_not_inside_an_input", async () => {
    serve(three());
    render(Videos);
    await screen.findByText("1 of 3");
    await fireEvent.keyDown(window, { key: "ArrowRight" });
    expect(position()).toBe("2 of 3");
    await fireEvent.keyDown(window, { key: "ArrowLeft" });
    expect(position()).toBe("1 of 3");
    const input = document.createElement("input");
    document.body.append(input);
    await fireEvent.keyDown(input, { key: "ArrowRight" });
    expect(position()).toBe("1 of 3");
    input.remove();
  });

  it("choosing_a_chip_refetches_with_the_species_and_resets_to_1", async () => {
    serve(three(), {
      "|Cyanistes caeruleus": { items: [item(9, { species: { scientific: "Cyanistes caeruleus", name: "blue tit" } })], next_cursor: null, total: 1, filters: FILTERS },
    });
    render(Videos);
    await screen.findByText("1 of 3");
    await fireEvent.click(screen.getByRole("button", { name: "Next clip" }));
    await fireEvent.click(screen.getByRole("button", { name: "Blue tit" }));
    await screen.findByText("1 of 1");
    expect(video().getAttribute("src")).toBe("/media/web/9.mp4");
    expect(fetchMock.mock.calls.some((c) => String(c[0]).includes("species=Cyanistes+caeruleus"))).toBe(true);
  });

  it("does_not_offer_favourite_or_what_is_it_when_locked", async () => {
    canEdit.set(false);
    serve(three());
    render(Videos);
    await screen.findByText("1 of 3");
    expect(screen.queryByRole("button", { name: /Favourite|Saved/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "What is it?" })).toBeNull();
    const dl = screen.getByRole("link", { name: "Download" });
    expect(dl.getAttribute("href")).toBe("/media/web/1.mp4");
    expect(dl.hasAttribute("download")).toBe(true);
  });

  it("favourite_toggles_for_editors", async () => {
    serve(three());
    render(Videos);
    await screen.findByText("1 of 3");
    const calls: string[] = [];
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (init?.method === "PATCH") {
        calls.push(`${url} ${init.body}`);
        return new Response(JSON.stringify({ undo_token: "t" }), { status: 200 });
      }
      return new Response(JSON.stringify(three()), { status: 200 });
    });
    const fav = screen.getByRole("button", { name: "Favourite" });
    expect(fav.getAttribute("aria-pressed")).toBe("false");
    await fireEvent.click(fav);
    await waitFor(() => expect(screen.getByRole("button", { name: "Favourite" }).getAttribute("aria-pressed")).toBe("true"));
    expect(calls).toEqual(['/api/visits/1 {"is_favourite":true}']);
  });

  it("an_empty_feed_says_so", async () => {
    serve({ items: [], next_cursor: null, total: 0, filters: [] });
    render(Videos);
    await screen.findByText(/No bird videos yet/);
    expect(document.querySelector("video")).toBeNull();
  });

  it("a_failed_first_load_offers_try_again", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("Failed to fetch"); }));
    render(Videos);
    await screen.findByText(/Couldn.t load the videos/);
    serve(three());
    await fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    await screen.findByText("1 of 3");
  });

  it("a_chip_change_during_a_load_more_wins_and_the_old_response_is_ignored", async () => {
    serve(three({ total: 5, next_cursor: "c2" }), {
      "|Cyanistes caeruleus": { items: [item(9), item(10)], next_cursor: null, total: 2, filters: FILTERS },
    });
    let release: () => void = () => {};
    const slow = new Promise<void>((r) => (release = r));
    const base = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation(async (url: string) => {
      if (url.includes("cursor=c2")) {
        await slow;
        return new Response(JSON.stringify({ items: [item(4), item(5)], next_cursor: null, total: 5, filters: FILTERS }), { status: 200 });
      }
      return base(url);
    });
    render(Videos);
    await screen.findByText("1 of 3");
    const next = screen.getByRole("button", { name: "Next clip" }) as HTMLButtonElement;
    await fireEvent.click(next);
    await fireEvent.click(next);
    await fireEvent.click(next); // load-more now in flight
    await fireEvent.click(screen.getByRole("button", { name: "Blue tit" }));
    await screen.findByText("1 of 2");
    release();
    await tick();
    await tick();
    expect(position()).toBe("1 of 2");
    expect(video().getAttribute("src")).toBe("/media/web/9.mp4");
    expect(next.disabled).toBe(false);
    await fireEvent.click(next);
    expect(position()).toBe("2 of 2");
  });

  it("a_rapid_double_next_at_the_last_loaded_item_fetches_the_cursor_once", async () => {
    serve(three({ total: 5, next_cursor: "c2" }), {
      "c2|": { items: [item(4), item(5)], next_cursor: null, total: 5, filters: FILTERS },
    });
    render(Videos);
    await screen.findByText("1 of 5");
    const next = screen.getByRole("button", { name: "Next clip" }) as HTMLButtonElement;
    await fireEvent.click(next);
    await fireEvent.click(next);
    next.click();
    next.click();
    await waitFor(() => expect(position()).toBe("4 of 5"));
    expect(fetchMock.mock.calls.filter((c) => String(c[0]).includes("cursor=c2"))).toHaveLength(1);
  });

  it("arrow_keys_leave_the_video_alone_so_native_seek_works", async () => {
    serve(three());
    render(Videos);
    await screen.findByText("1 of 3");
    await fireEvent.keyDown(video(), { key: "ArrowRight" });
    expect(position()).toBe("1 of 3");
  });

  it("keeps_the_header_and_chips_when_a_chip_refetch_fails", async () => {
    serve(three());
    render(Videos);
    await screen.findByText("1 of 3");
    fetchMock.mockImplementation(async () => { throw new TypeError("Failed to fetch"); });
    await fireEvent.click(screen.getByRole("button", { name: "Blue tit" }));
    await screen.findByText(/Couldn.t load the videos/);
    expect(screen.getByRole("heading", { name: "Videos" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Blue tit" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Try again" })).toBeTruthy();
  });

  it("says_loading_before_the_first_load_and_announces_the_position", async () => {
    serve(three());
    render(Videos);
    expect(screen.getByText("Loading…")).toBeTruthy();
    await screen.findByText("1 of 3");
    expect(screen.getByText("1 of 3").getAttribute("aria-live")).toBe("polite");
    expect(screen.queryByText("Loading…")).toBeNull();
  });
});
