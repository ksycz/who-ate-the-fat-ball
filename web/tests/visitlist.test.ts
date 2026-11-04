import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import VisitList from "../src/pages/VisitList.svelte";
import { noteServerDay, noteUndone, serverDay } from "../src/lib/session";
import type { Visit } from "../src/lib/api";

function visit(id: number, startedAt: string, over: Partial<Visit> = {}): Visit {
  return {
    id,
    started_at: startedAt,
    ended_at: startedAt,
    category: "birds",
    species: { scientific: "Parus major", name: "great tit" },
    subject: "species",
    confidence: 0.9,
    is_favourite: false,
    best_frame_url: null,
    clip_count: 1,
    duration_s: 5,
    poster_url: null,
    preview_url: null,
    corrected: false,
    watched: true,
    ...over,
  };
}

// 300 visits, newest first: ids 300..1, one every minute, all on 2026-11-03 until id 101, then 2026-11-02.
const ALL: Visit[] = Array.from({ length: 300 }, (_, i) => {
  const id = 300 - i;
  const day = id > 120 ? "2026-11-03" : id > 20 ? "2026-11-02" : "2026-10-31";
  return visit(id, `${day}T10:${String(id % 60).padStart(2, "0")}:00+01:00`);
});

let fetchMock: ReturnType<typeof vi.fn>;
let visitsDown = false;
let statusDown = false;
function serve(items: Visit[] = ALL, newSpecies: unknown = null) {
  fetchMock = vi.fn(async (url: string) => {
    if ((url.startsWith("/api/visits") && visitsDown) || (url === "/api/status" && statusDown)) throw new TypeError("Failed to fetch");
    if (url === "/api/today") return new Response(JSON.stringify({ day: "2026-11-03", new_species: newSpecies }), { status: 200 });
    if (url.startsWith("/api/visits")) {
      const q = new URL(url, "http://x").searchParams;
      const start = Number(q.get("cursor") ?? 0);
      const limit = Number(q.get("limit"));
      const page = items.slice(start, start + limit);
      const next = start + limit < items.length ? String(start + limit) : null;
      return new Response(JSON.stringify({ items: page, next_cursor: next }), { status: 200 });
    }
    return new Response("{}", { status: 404 });
  });
  vi.stubGlobal("fetch", fetchMock);
}
const visitUrls = () => fetchMock.mock.calls.map((c) => c[0] as string).filter((u) => u.startsWith("/api/visits"));

let observerCallback: (() => void) | null = null;
beforeEach(() => {
  visitsDown = false;
  statusDown = false;
  noteServerDay("2026-11-03");
  observerCallback = null;
  vi.stubGlobal(
    "IntersectionObserver",
    class {
      constructor(cb: (e: { isIntersecting: boolean }[]) => void) {
        observerCallback = () => cb([{ isIntersecting: true }]);
      }
      observe() {}
      disconnect() {}
      unobserve() {}
    },
  );
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("VisitList", () => {
  it("first_request_asks_for_50", async () => {
    serve();
    render(VisitList, { kind: "birds" });
    await screen.findAllByRole("link", { name: /Great tit/ });
    const first = visitUrls()[0];
    expect(first).toContain("limit=50");
    expect(first).toContain("category=birds");
    expect(first).not.toContain("cursor");
    expect(screen.getAllByRole("link", { name: /Great tit/ })).toHaveLength(50);
    expect(screen.getByRole("heading", { level: 1, name: "Birds" })).toBeTruthy();
  });

  it("scrolling_sentinel_loads_next_cursor_and_appends", async () => {
    serve();
    render(VisitList, { kind: "birds" });
    await screen.findAllByRole("link", { name: /Great tit/ });
    await act(() => observerCallback!());
    await waitFor(() => expect(screen.getAllByRole("link", { name: /Great tit/ })).toHaveLength(100));
    expect(visitUrls()[1]).toContain("cursor=50");
  });

  it("show_more_button_works_without_the_observer", async () => {
    serve();
    render(VisitList, { kind: "birds" });
    await screen.findAllByRole("link", { name: /Great tit/ });
    await fireEvent.click(screen.getByRole("button", { name: "Show more" }));
    await waitFor(() => expect(screen.getAllByRole("link", { name: /Great tit/ })).toHaveLength(100));
  });

  it("day_heading_not_repeated_across_pages", async () => {
    serve();
    render(VisitList, { kind: "birds" });
    await screen.findAllByRole("link", { name: /Great tit/ });
    await act(() => observerCallback!());
    await waitFor(() => expect(screen.getAllByRole("link", { name: /Great tit/ })).toHaveLength(100));
    // ids 300..121 are today, so pages 1 and 2 both sit under the one heading.
    expect(screen.getAllByRole("heading", { level: 2, name: "Today" })).toHaveLength(1);
  });

  it("headings_use_the_server_day", async () => {
    serve();
    render(VisitList, { kind: "birds" });
    await screen.findAllByRole("link", { name: /Great tit/ });
    while (screen.queryByRole("button", { name: "Show more" })) {
      await fireEvent.click(screen.getByRole("button", { name: "Show more" }));
      await new Promise((r) => setTimeout(r, 0));
    }
    const names = screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent);
    expect(names).toEqual(["Today", "Yesterday", "Saturday 31 October"]);
  });

  it("favourites_uses_favourite_filter", async () => {
    serve();
    render(VisitList, { kind: "favourites" });
    await screen.findAllByRole("link", { name: /Great tit/ });
    expect(visitUrls()[0]).toContain("favourite=true");
    expect(visitUrls()[0]).not.toContain("category");
    expect(screen.getByRole("heading", { level: 1, name: "Favourites" })).toBeTruthy();
  });

  it("other_animals_and_other_use_their_category", async () => {
    serve();
    render(VisitList, { kind: "other_animals" });
    await screen.findAllByRole("link", { name: /Great tit/ });
    expect(visitUrls()[0]).toContain("category=other_animals");
    expect(screen.getByRole("heading", { level: 1, name: "Other animals" })).toBeTruthy();
    cleanup();
    serve();
    render(VisitList, { kind: "other" });
    await screen.findAllByRole("link", { name: /Great tit/ });
    expect(visitUrls()[0]).toContain("category=other");
    expect(screen.getByRole("heading", { level: 1, name: "Other" })).toBeTruthy();
  });

  it("empty_state_texts", async () => {
    const cases = [
      ["birds", "No bird visits yet"],
      ["other_animals", "No other animals yet"],
      ["other", "Nothing here: no dogs, people or empty clips"],
      ["favourites", "No favourites yet. Tap ☆ on a visit to keep it here."],
    ] as const;
    for (const [kind, text] of cases) {
      serve([]);
      render(VisitList, { kind });
      expect(await screen.findByText(text)).toBeTruthy();
      expect(screen.queryByRole("button", { name: "Show more" })).toBeNull();
      cleanup();
    }
  });

  it("birds_shows_banner_only_on_wide_layout", async () => {
    const ns = { visit_id: 2, scientific: "Sitta europaea", name: "Eurasian nuthatch", started_at: "2026-11-03T09:12:00+01:00" };
    serve(ALL, ns);
    const { container } = render(VisitList, { kind: "birds" });
    expect(await screen.findByText("New species")).toBeTruthy();
    // The wide-only rule lives in the component's CSS; here we check it is the Birds placement.
    expect(container.querySelector('[data-placement="birds"]')).toBeTruthy();
    cleanup();
    serve(ALL, ns);
    const other = render(VisitList, { kind: "other" });
    await screen.findAllByRole("link", { name: /Great tit/ });
    expect(screen.queryByText("New species")).toBeNull();
    expect(other.container.querySelector('[data-placement]')).toBeNull();
  });

  it("first_page_failure_offers_try_again", async () => {
    visitsDown = true;
    serve();
    render(VisitList, { kind: "birds" });
    expect(await screen.findByText("Couldn't load visits. Check the Wi-Fi and try again.")).toBeTruthy();
    visitsDown = false;
    await fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    await screen.findAllByRole("link", { name: /Great tit/ });
    expect(screen.queryByText(/Couldn't load visits/)).toBeNull();
    expect(screen.queryByRole("button", { name: "Try again" })).toBeNull();
  });

  it("renders_with_day_headings_from_the_dates_when_status_fails", async () => {
    serverDay.set(null);
    statusDown = true;
    serve();
    render(VisitList, { kind: "other" });
    await screen.findAllByRole("link", { name: /Great tit/ });
    const names = screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent);
    expect(names).toEqual(["Tuesday 3 November"]);
  });

  it("reloads_from_the_first_page_after_an_undo", async () => {
    serve();
    render(VisitList, { kind: "birds" });
    await screen.findAllByRole("link", { name: /Great tit/ });
    await fireEvent.click(screen.getByRole("button", { name: "Show more" }));
    await waitFor(() => expect(screen.getAllByRole("link", { name: /Great tit/ })).toHaveLength(100));
    noteUndone();
    await waitFor(() => expect(screen.getAllByRole("link", { name: /Great tit/ })).toHaveLength(50));
    expect(visitUrls().at(-1)).not.toContain("cursor");
  });
});
