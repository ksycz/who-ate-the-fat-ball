import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import Today from "../src/pages/Today.svelte";
import { canEdit } from "../src/lib/session";
import type { Today as TodayData, Visit } from "../src/lib/api";

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
    best_frame_url: "/media/frames/1.jpg",
    clip_count: 3,
    duration_s: 24,
    poster_url: "/media/c1.jpg",
    preview_url: null,
    corrected: false,
    watched: true,
    ...over,
  };
}

function today(over: Partial<TodayData> = {}): TodayData {
  return {
    day: "2026-11-03",
    now: "2026-11-03T09:20:00+01:00",
    summary: { visits: 2, species: 2 },
    champion: { scientific: "Parus major", name: "great tit", count: 6, first_at: "2026-11-03T07:21:00+01:00", best_frame_url: "/media/frames/9.jpg" },
    new_species: null,
    visits: [
      visit({ id: 2, started_at: "2026-11-03T09:12:00+01:00", ended_at: "2026-11-03T09:14:00+01:00", species: { scientific: "Sitta europaea", name: "Eurasian nuthatch" } }),
      visit({ id: 1 }),
    ],
    checking: [],
    failed: [],
    last_visitor: null,
    camera: { state: "ok", last_seen_at: "2026-11-03T09:15:00+01:00", last_error: null },
    ...over,
  };
}

let fetchMock: ReturnType<typeof vi.fn>;
function serve(data: TodayData) {
  fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === "/api/today") return new Response(JSON.stringify(data), { status: 200 });
    if (url.startsWith("/api/retry/") && init?.method === "POST") return new Response(null, { status: 204 });
    return new Response("{}", { status: 404 });
  });
  vi.stubGlobal("fetch", fetchMock);
}

beforeEach(() => {
  canEdit.set(false);
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date(2026, 10, 3, 9, 20));
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("Today", () => {
  it("renders_empty_state_with_last_visitor", async () => {
    serve(
      today({
        summary: { visits: 0, species: 0 },
        champion: null,
        visits: [],
        last_visitor: { name: "great tit", started_at: "2026-11-02T16:20:00+01:00" },
        camera: { state: "asleep", last_seen_at: "2026-11-03T06:10:00+01:00", last_error: null },
      }),
    );
    render(Today);
    expect(await screen.findByText("Quiet so far")).toBeTruthy();
    expect(screen.getByText("No visits yet")).toBeTruthy();
    expect(
      screen.getByText("No visitors yet today. Last visitor: Great tit, yesterday 16:20. The camera was last seen at 06:10."),
    ).toBeTruthy();
  });

  it("empty_state_links_to_yesterdays_visits", async () => {
    serve(today({ summary: { visits: 0, species: 0 }, champion: null, visits: [] }));
    render(Today);
    const a = await screen.findByRole("link", { name: "See yesterday’s visits" });
    expect(a.getAttribute("href")).toBe("/birds");
  });

  it("empty_state_leaves_out_missing_last_visitor", async () => {
    serve(today({ summary: { visits: 0, species: 0 }, champion: null, visits: [], last_visitor: null }));
    render(Today);
    const text = (await screen.findByText(/No visitors yet today\./)).textContent;
    expect(text).not.toContain("Last visitor");
  });

  it("renders_champion_and_visits_newest_first", async () => {
    serve(today({ summary: { visits: 14, species: 6 } }));
    render(Today);
    expect(await screen.findByText("Today's fat-ball champion")).toBeTruthy();
    expect(screen.getByText("6 visits · first at 07:21")).toBeTruthy();
    expect(screen.getByText("14 visits · 6 species")).toBeTruthy();
    const cards = screen.getAllByRole("link").filter((a) => a.getAttribute("href")?.startsWith("/visit/"));
    expect(cards.map((a) => a.getAttribute("href"))).toEqual(["/visit/2?list=day%3D2026-11-03", "/visit/1?list=day%3D2026-11-03"]);
    expect(cards[0].textContent).toContain("Eurasian nuthatch");
    expect(cards[0].textContent).toContain("09:12 · stayed 2 min");
    expect(cards[0].textContent).toContain("▶ 0:24 · 3 clips");
    expect(cards[0].textContent).toContain("94% sure");
  });

  it("corrected_visit_says_so_under_the_time", async () => {
    serve(today({ visits: [visit({ corrected: true })] }));
    render(Today);
    expect(await screen.findByText("Corrected by you")).toBeTruthy();
  });

  it("clip_badge_without_duration_shows_only_the_clip_count", async () => {
    serve(today({ visits: [visit({ duration_s: null, clip_count: 3 })] }));
    render(Today);
    expect(await screen.findByText("▶ 3 clips")).toBeTruthy();
  });

  it("new_species_banner_links_to_the_visit", async () => {
    serve(
      today({
        new_species: { visit_id: 2, scientific: "Sitta europaea", name: "Eurasian nuthatch", started_at: "2026-11-03T09:12:00+01:00" },
      }),
    );
    render(Today);
    expect(await screen.findByText("New species")).toBeTruthy();
    expect(screen.getByText("Eurasian nuthatch · 09:12")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Watch" }).getAttribute("href")).toBe("/visit/2");
  });

  it("checking_card_for_unrecognised_clip", async () => {
    serve(
      today({
        checking: [
          { id: 4, begin_at: "2026-11-03T09:05:00+01:00", end_at: "2026-11-03T09:06:00+01:00", kind: "video", duration_s: 9, web_url: null, original_url: null, poster_url: null, preview_url: null },
        ],
      }),
    );
    render(Today);
    expect(await screen.findByText("Checking who it is…")).toBeTruthy();
    expect(screen.getByText("Checking…")).toBeTruthy();
    expect(screen.getByText("▶ 0:09 · 1 clip")).toBeTruthy();
  });

  it("checking_card_is_not_a_link", async () => {
    serve(today({ checking: [{ id: 4, begin_at: "2026-11-03T09:05:00+01:00", end_at: "2026-11-03T09:06:00+01:00", kind: "video", duration_s: 9, web_url: null, original_url: null, poster_url: null, preview_url: null }] }));
    render(Today);
    const name = await screen.findByText("Checking who it is…");
    expect(name.closest("a")).toBeNull();
  });

  it("camera_minutes_come_from_the_servers_clock", async () => {
    // This device thinks it is 12:00; the Mac says 09:20, so the camera (seen 09:15) was seen 5 minutes ago.
    vi.setSystemTime(new Date(2026, 10, 3, 12, 0));
    serve(today({ camera: { state: "ok", last_seen_at: "2026-11-03T09:15:00+01:00", last_error: null } }));
    render(Today);
    expect(await screen.findByText("Camera seen 5 min ago")).toBeTruthy();
  });

  it("retry_hidden_when_locked", async () => {
    serve(today({ failed: [{ clip_id: 5, begin_at: "2026-11-03T08:00:00+01:00", can_retry: true }] }));
    render(Today);
    await screen.findByText("Today's fat-ball champion");
    expect(screen.queryByRole("button", { name: "Retry" })).toBeNull();
    expect(screen.queryByText(/couldn't be fetched/)).toBeNull();
  });

  it("retry_hidden_when_clip_cannot_be_retried", async () => {
    canEdit.set(true);
    serve(today({ failed: [{ clip_id: 5, begin_at: "2026-11-03T08:00:00+01:00", can_retry: false }] }));
    render(Today);
    await screen.findByText("Today's fat-ball champion");
    expect(screen.queryByRole("button", { name: "Retry" })).toBeNull();
  });

  it("retry_posts_and_hides_row", async () => {
    canEdit.set(true);
    serve(today({ failed: [{ clip_id: 5, begin_at: "2026-11-03T08:00:00+01:00", can_retry: true }] }));
    render(Today);
    expect(await screen.findByText("1 clip couldn't be fetched")).toBeTruthy();
    await fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(screen.queryByText("1 clip couldn't be fetched")).toBeNull());
    const post = fetchMock.mock.calls.find((c) => c[0] === "/api/retry/5");
    expect(post?.[1]?.method).toBe("POST");
  });

  it("retry_row_counts_several_clips", async () => {
    canEdit.set(true);
    serve(
      today({
        failed: [
          { clip_id: 5, begin_at: "2026-11-03T08:00:00+01:00", can_retry: true },
          { clip_id: 6, begin_at: "2026-11-03T08:10:00+01:00", can_retry: true },
        ],
      }),
    );
    render(Today);
    expect(await screen.findByText("2 clips couldn't be fetched")).toBeTruthy();
  });

  it("camera_problem_notice_links_to_status", async () => {
    serve(today({ camera: { state: "problem", last_seen_at: "2026-11-02T18:40:00+01:00", last_error: "x" } }));
    render(Today);
    const notice = await screen.findByRole("link", { name: /Camera not seen since yesterday 18:40/ });
    expect(notice.getAttribute("href")).toBe("/status");
  });

  it("card_without_any_image_shows_placeholder_not_broken_img", async () => {
    serve(today({ champion: null, visits: [visit({ best_frame_url: null, poster_url: null })] }));
    const { container } = render(Today);
    await screen.findByText("Great tit");
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("[data-placeholder]")).toBeTruthy();
  });

  it("card_falls_back_to_poster_when_no_best_frame", async () => {
    serve(today({ champion: null, visits: [visit({ best_frame_url: null, poster_url: "/media/c1.jpg" })] }));
    const { container } = render(Today);
    await screen.findByText("Great tit");
    expect(container.querySelector("img")?.getAttribute("src")).toBe("/media/c1.jpg");
  });

  it("today_label_uses_server_day", async () => {
    // The browser thinks it is the 2nd; the server says it is the 3rd.
    vi.setSystemTime(new Date(2026, 10, 2, 23, 50));
    serve(today());
    render(Today);
    await screen.findByText("Eurasian nuthatch");
    expect(screen.getByText("09:12 · stayed 2 min")).toBeTruthy();
    expect(screen.queryByText(/Yesterday/)).toBeNull();
  });
});
