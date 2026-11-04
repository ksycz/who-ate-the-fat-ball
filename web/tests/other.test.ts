import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import { get } from "svelte/store";
import FilterChips from "../src/components/FilterChips.svelte";
import SelectBar from "../src/components/SelectBar.svelte";
import VisitList from "../src/pages/VisitList.svelte";
import { selection } from "../src/lib/select";
import { canEdit, changes, noteServerDay, toast } from "../src/lib/session";
import { clearLists } from "../src/lib/listCache";
import type { Visit } from "../src/lib/api";

const empty = (id: number): Visit => ({
  id, started_at: "2026-11-03T10:03:00", ended_at: "2026-11-03T10:03:00", category: "other", species: null,
  subject: "empty", confidence: null, is_favourite: false, best_frame_url: null, clip_count: 1, duration_s: 5,
  poster_url: null, preview_url: null, corrected: false, watched: true,
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  toast.set(null);
  canEdit.set(false);
});

describe("FilterChips", () => {
  it("marks the chosen option pressed and reports a click", async () => {
    const onchange = vi.fn();
    render(FilterChips, { options: ["All", "Only dogs", "Empty clips"], value: "Only dogs", onchange });
    expect(screen.getByRole("group", { name: "Show" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Only dogs" }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByRole("button", { name: "All" }).getAttribute("aria-pressed")).toBe("false");
    await fireEvent.click(screen.getByRole("button", { name: "Empty clips" }));
    expect(onchange).toHaveBeenCalledWith("Empty clips");
  });

  it("accepts a dark tone", () => {
    const { container } = render(FilterChips, { options: ["A", "B"], value: "A", onchange: () => {}, tone: "dark" });
    expect(container.querySelector(".dark")).toBeTruthy();
  });
});

describe("SelectBar Delete", () => {
  const props = { count: 3, onmove: () => {}, onzip: () => {}, ondelete: () => {} };
  it("is offered to editors on Other with Empty clips", () => {
    canEdit.set(true);
    render(SelectBar, { kind: "other", filter: "empty", ...props });
    expect(screen.getByRole("button", { name: "Delete" })).toBeTruthy();
  });
  it("is not rendered when locked", () => {
    canEdit.set(false);
    render(SelectBar, { kind: "other", filter: "empty", ...props });
    expect(screen.queryByRole("button", { name: "Delete" })).toBeNull();
  });
  it("is not rendered for other filters or other lists", () => {
    canEdit.set(true);
    render(SelectBar, { kind: "other", filter: "dogs", ...props });
    expect(screen.queryByRole("button", { name: "Delete" })).toBeNull();
    cleanup();
    render(SelectBar, { kind: "other", filter: "all", ...props });
    expect(screen.queryByRole("button", { name: "Delete" })).toBeNull();
    cleanup();
    render(SelectBar, { kind: "birds", ...props });
    expect(screen.queryByRole("button", { name: "Delete" })).toBeNull();
  });
});

describe("Other page", () => {
  let fetchMock: ReturnType<typeof vi.fn>;
  let deleteStatus = 200;
  beforeEach(() => {
    clearLists();
    selection.clear();
    noteServerDay("2026-11-03");
    deleteStatus = 200;
    fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      if (url === "/api/visits/delete") {
        const n = JSON.parse(init!.body as string).visit_ids.length;
        return deleteStatus === 200
          ? new Response(JSON.stringify({ deleted: n }), { status: 200 })
          : new Response(JSON.stringify({ detail: "Only empty clips can be deleted" }), { status: deleteStatus });
      }
      if (url.startsWith("/api/visits")) {
        const only = new URL(url, "http://x").searchParams.get("only");
        const items = only === "empty" ? [empty(2), empty(1)] : [];
        return new Response(JSON.stringify({ items, next_cursor: null }), { status: 200 });
      }
      return new Response("{}", { status: 404 });
    });
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("IntersectionObserver", class { observe() {} disconnect() {} unobserve() {} });
  });

  const lastList = () => fetchMock.mock.calls.filter((c) => String(c[0]).startsWith("/api/visits?")).at(-1)![0] as string;

  it("shows the chips only on Other, and the per-filter empty text", async () => {
    render(VisitList, { kind: "other" });
    expect(await screen.findByText("Nothing here: no dogs, people or empty clips")).toBeTruthy();
    await fireEvent.click(screen.getByRole("button", { name: "Only dogs" }));
    expect(await screen.findByText("No dogs here")).toBeTruthy();
    expect(lastList()).toContain("only=dogs");
    cleanup();
    render(VisitList, { kind: "birds" });
    await waitFor(() => expect(screen.queryByRole("group", { name: "Show" })).toBeNull());
  });

  it("deletes the selected empty clips after a confirm", async () => {
    canEdit.set(true);
    render(VisitList, { kind: "other" });
    await fireEvent.click(await screen.findByRole("button", { name: "Empty clips" }));
    await fireEvent.click(await screen.findByRole("button", { name: "Select" }));
    await fireEvent.click(screen.getByRole("button", { name: "Select all" }));
    await fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    await screen.findByText("Delete 2 empty clips? This can't be undone.");
    const before = get(changes);
    await fireEvent.click(screen.getByRole("dialog").querySelector(".go") as HTMLElement);
    await waitFor(() => expect(get(toast)?.text).toBe("2 empty clips deleted"));
    expect(get(changes)).toBeGreaterThan(before);
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("heading", { level: 1 })));
    const call = fetchMock.mock.calls.find((c) => c[0] === "/api/visits/delete")!;
    expect(JSON.parse((call[1] as RequestInit).body as string)).toEqual({ visit_ids: [2, 1] });
  });

  it("says one empty clip, and Cancel deletes nothing", async () => {
    canEdit.set(true);
    render(VisitList, { kind: "other" });
    await fireEvent.click(await screen.findByRole("button", { name: "Empty clips" }));
    await fireEvent.click(await screen.findByRole("button", { name: "Select" }));
    await fireEvent.click(screen.getAllByRole("checkbox")[0]);
    await fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    await screen.findByText("Delete 1 empty clip? This can't be undone.");
    await fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(fetchMock.mock.calls.some((c) => c[0] === "/api/visits/delete")).toBe(false);
  });

  it("keeps the selection and shows a friendly toast on a 409", async () => {
    canEdit.set(true);
    deleteStatus = 409;
    render(VisitList, { kind: "other" });
    await fireEvent.click(await screen.findByRole("button", { name: "Empty clips" }));
    await fireEvent.click(await screen.findByRole("button", { name: "Select" }));
    await fireEvent.click(screen.getByRole("button", { name: "Select all" }));
    await fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    await fireEvent.click(screen.getByRole("dialog").querySelector(".go") as HTMLElement);
    await waitFor(() => expect(get(toast)?.text).toBe("Only empty clips can be deleted"));
    expect(screen.getByText("2 visits selected")).toBeTruthy();
  });
});
