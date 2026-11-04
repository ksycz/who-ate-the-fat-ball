import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import { get } from "svelte/store";
import VisitList from "../src/pages/VisitList.svelte";
import { selection } from "../src/lib/select";
import { noteServerDay, toast } from "../src/lib/session";
import type { Visit } from "../src/lib/api";

const v = (id: number, at: string): Visit => ({
  id, started_at: at, ended_at: at, category: "birds", species: { scientific: "Parus major", name: "great tit" },
  subject: "species", confidence: 0.9, is_favourite: false, best_frame_url: null, clip_count: 1, duration_s: 5,
  poster_url: null, preview_url: null, corrected: false, watched: true,
});
const ITEMS = [v(3, "2026-11-03T10:03:00"), v(2, "2026-11-03T10:02:00"), v(1, "2026-11-02T10:01:00")];

let fetchMock: ReturnType<typeof vi.fn>;
let items = ITEMS;
beforeEach(() => {
  items = ITEMS;
  selection.clear();
  noteServerDay("2026-11-03");
  fetchMock = vi.fn(async (url: string) => {
    if (url === "/api/downloads/zip") {
      return new Response(
        JSON.stringify({ token: "t", size_bytes: 2000, visits: 2, files: 2, filename: "fat-ball-2-visits.zip" }),
        { status: 200 },
      );
    }
    if (url.startsWith("/api/visits")) return new Response(JSON.stringify({ items, next_cursor: null }), { status: 200 });
    if (url === "/api/today") return new Response(JSON.stringify({ day: "2026-11-03", new_species: null }), { status: 200 });
    return new Response("{}", { status: 404 });
  });
  vi.stubGlobal("fetch", fetchMock);
  vi.stubGlobal("IntersectionObserver", class { observe() {} disconnect() {} unobserve() {} });
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  toast.set(null);
});

describe("VisitList select mode", () => {
  it("Select turns into Done, links become checkboxes, Select all picks every loaded visit", async () => {
    render(VisitList, { kind: "birds" });
    const select = await screen.findByRole("button", { name: "Select" });
    expect(select.getAttribute("aria-pressed")).toBe("false");
    await fireEvent.click(select);
    expect(screen.getByRole("button", { name: "Done" }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.queryAllByRole("link")).toHaveLength(0);
    await fireEvent.click(screen.getByRole("button", { name: "Select all" }));
    expect(screen.getByText("3 visits selected")).toBeTruthy();
    await fireEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(screen.queryByText(/selected/)).toBeNull();
    expect(screen.getAllByRole("link").length).toBe(3);
  });

  it("Download .zip sends the picked ids and asks to confirm", async () => {
    render(VisitList, { kind: "birds" });
    await fireEvent.click(await screen.findByRole("button", { name: "Select" }));
    await fireEvent.click(screen.getAllByRole("checkbox")[0]);
    await fireEvent.click(screen.getAllByRole("checkbox")[1]);
    await fireEvent.click(screen.getByRole("button", { name: "Download .zip" }));
    await screen.findByText("Download 2 visits (2 KB)?");
    const call = fetchMock.mock.calls.find((c) => c[0] === "/api/downloads/zip")!;
    expect(JSON.parse((call[1] as RequestInit).body as string)).toEqual({ visit_ids: [3, 2] });
  });

  it("Download this day sends the day and category", async () => {
    render(VisitList, { kind: "birds" });
    const buttons = await screen.findAllByRole("button", { name: "Download this day (.zip)" });
    await fireEvent.click(buttons[1]);
    await waitFor(() => expect(fetchMock.mock.calls.some((c) => c[0] === "/api/downloads/zip")).toBe(true));
    const call = fetchMock.mock.calls.find((c) => c[0] === "/api/downloads/zip")!;
    expect(JSON.parse((call[1] as RequestInit).body as string)).toEqual({ day: "2026-11-02", category: "birds" });
  });

  it("on Favourites the day zip sends favourite: true", async () => {
    render(VisitList, { kind: "favourites" });
    const buttons = await screen.findAllByRole("button", { name: "Download this day (.zip)" });
    await fireEvent.click(buttons[0]);
    await waitFor(() => expect(fetchMock.mock.calls.some((c) => c[0] === "/api/downloads/zip")).toBe(true));
    const call = fetchMock.mock.calls.find((c) => c[0] === "/api/downloads/zip")!;
    expect(JSON.parse((call[1] as RequestInit).body as string)).toEqual({ day: "2026-11-03", favourite: true });
  });

  it("refuses to zip more than 500 selected without asking the Mac", async () => {
    items = Array.from({ length: 501 }, (_, i) => v(1000 - i, "2026-11-03T10:00:00"));
    render(VisitList, { kind: "birds" });
    await fireEvent.click(await screen.findByRole("button", { name: "Select" }));
    await fireEvent.click(screen.getByRole("button", { name: "Select all" }));
    await fireEvent.click(screen.getByRole("button", { name: "Download .zip" }));
    await waitFor(() => expect(get(toast)?.text).toBe("You can download up to 500 visits at once"));
    expect(fetchMock.mock.calls.some((c) => c[0] === "/api/downloads/zip")).toBe(false);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("on Other, the day zip is offered only with All chosen", async () => {
    items = [{ ...ITEMS[0], category: "other", species: null, subject: "nothing" }];
    render(VisitList, { kind: "other" });
    expect(await screen.findAllByRole("button", { name: "Download this day (.zip)" })).toHaveLength(1);
    await fireEvent.click(screen.getByRole("button", { name: "Empty clips" }));
    await screen.findByRole("link");
    expect(screen.queryByRole("button", { name: "Download this day (.zip)" })).toBeNull();
    await fireEvent.click(screen.getByRole("button", { name: "Only dogs" }));
    await screen.findByRole("link");
    expect(screen.queryByRole("button", { name: "Download this day (.zip)" })).toBeNull();
  });
});
