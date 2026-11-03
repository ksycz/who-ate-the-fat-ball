import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/svelte";
import { get } from "svelte/store";
import SelectBar from "../src/components/SelectBar.svelte";
import VisitCard from "../src/components/VisitCard.svelte";
import { movedText, moveVisits, selection } from "../src/lib/select";
import { canEdit, changes, toast } from "../src/lib/session";
import { navigate } from "../src/lib/router";
import type { Visit } from "../src/lib/api";

const visit: Visit = {
  id: 7, started_at: "2026-11-03T09:12:00+01:00", ended_at: "2026-11-03T09:14:00+01:00", category: "birds",
  species: { scientific: "Parus major", name: "great tit" }, subject: "species", confidence: 0.9, is_favourite: false,
  best_frame_url: null, clip_count: 1, duration_s: 5, poster_url: null, preview_url: null, corrected: false, watched: true,
};

beforeEach(() => selection.clear());
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  toast.set(null);
  canEdit.set(false);
});

describe("selection store", () => {
  it("starts off and empty", () => {
    expect(get(selection).on).toBe(false);
    expect(get(selection).ids.size).toBe(0);
  });
  it("toggle adds and removes", () => {
    selection.enter();
    selection.toggle(1);
    selection.toggle(2);
    expect([...get(selection).ids]).toEqual([1, 2]);
    selection.toggle(1);
    expect([...get(selection).ids]).toEqual([2]);
  });
  it("selectAll takes every id given", () => {
    selection.enter();
    selection.selectAll([3, 4, 5]);
    expect(get(selection).ids.size).toBe(3);
  });
  it("clear turns select mode off", () => {
    selection.enter();
    selection.toggle(1);
    selection.clear();
    expect(get(selection)).toEqual({ on: false, ids: new Set() });
  });
  it("clears when the route changes", () => {
    selection.enter();
    selection.toggle(1);
    navigate("/other");
    expect(get(selection).on).toBe(false);
    expect(get(selection).ids.size).toBe(0);
  });
});

describe("movedText", () => {
  it("names a single visit, counts several", () => {
    expect(movedText(1, "other", "Great tit")).toBe("Great tit moved to Other");
    expect(movedText(1, "other")).toBe("1 visit moved to Other");
    expect(movedText(3, "other_animals")).toBe("3 visits moved to Other animals");
  });
});

describe("moveVisits", () => {
  it("posts the bulk change, then toasts with Undo and notes the change", async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ undo_token: "u1", changed: 3 }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    selection.enter();
    selection.toggle(1);
    const before = get(changes);
    await moveVisits([1, 2, 3], "other");
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/visits/bulk");
    expect(JSON.parse(init.body as string)).toEqual({ visit_ids: [1, 2, 3], category: "other" });
    expect(get(toast)).toEqual({ text: "3 visits moved to Other", undoToken: "u1" });
    expect(get(changes)).toBe(before + 1);
    expect(get(selection).on).toBe(false);
  });

  it("offers no Undo when nothing changed", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ undo_token: null, changed: 0 }), { status: 200 })));
    await moveVisits([1], "other");
    expect(get(toast)?.undoToken).toBeUndefined();
    expect(get(toast)?.text).toBe("Nothing changed");
  });

  it("says editing is locked on 403 and keeps the selection", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ detail: "locked" }), { status: 403 })));
    canEdit.set(true);
    selection.enter();
    selection.toggle(1);
    await moveVisits([1], "other");
    expect(get(toast)?.unlock).toBe(true);
    expect(get(canEdit)).toBe(false);
    expect(get(selection).ids.size).toBe(1);
  });
});

describe("SelectBar", () => {
  it("shows the count and Download .zip for everyone, no Move when locked", () => {
    canEdit.set(false);
    render(SelectBar, { kind: "birds", count: 3, onmove: () => {}, onzip: () => {} });
    expect(screen.getByText("3 visits selected")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Download .zip" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Move to/ })).toBeNull();
  });

  it("says 1 visit selected", () => {
    render(SelectBar, { kind: "birds", count: 1, onmove: () => {}, onzip: () => {} });
    expect(screen.getByText("1 visit selected")).toBeTruthy();
  });

  it("offers the two other categories to editors", async () => {
    canEdit.set(true);
    const onmove = vi.fn();
    render(SelectBar, { kind: "birds", count: 2, onmove, onzip: () => {} });
    await fireEvent.click(screen.getByRole("button", { name: "Move to…" }));
    const group = screen.getByRole("group", { name: "Move to" });
    expect(group.textContent).toContain("Other animals");
    expect(group.textContent).toContain("Other");
    expect(group.textContent).not.toContain("Birds");
    await fireEvent.click(screen.getByRole("button", { name: "Other animals" }));
    expect(onmove).toHaveBeenCalledWith("other_animals");
  });

  it("offers all three on Favourites", async () => {
    canEdit.set(true);
    render(SelectBar, { kind: "favourites", count: 2, onmove: () => {}, onzip: () => {} });
    await fireEvent.click(screen.getByRole("button", { name: "Move to…" }));
    expect(screen.getAllByRole("button").map((b) => b.textContent?.trim())).toEqual(
      expect.arrayContaining(["Birds", "Other animals", "Other"]),
    );
  });

  it("Download .zip calls onzip", async () => {
    const onzip = vi.fn();
    render(SelectBar, { kind: "birds", count: 2, onmove: () => {}, onzip });
    await fireEvent.click(screen.getByRole("button", { name: "Download .zip" }));
    expect(onzip).toHaveBeenCalled();
  });
});

describe("VisitCard in select mode", () => {
  it("is a checkbox, not a link", async () => {
    const onselect = vi.fn();
    render(VisitCard, { visit, today: "2026-11-03", selecting: true, selected: false, onselect });
    expect(screen.queryByRole("link")).toBeNull();
    const box = screen.getByRole("checkbox", { name: "Select Great tit at 09:12" });
    await fireEvent.click(box);
    expect(onselect).toHaveBeenCalledTimes(1);
  });

  it("reflects selected", () => {
    render(VisitCard, { visit, today: "2026-11-03", selecting: true, selected: true, onselect: () => {} });
    expect((screen.getByRole("checkbox") as HTMLInputElement).checked).toBe(true);
  });

  it("stays a link otherwise", () => {
    render(VisitCard, { visit, today: "2026-11-03" });
    expect(screen.getByRole("link")).toBeTruthy();
    expect(screen.queryByRole("checkbox")).toBeNull();
  });
});
