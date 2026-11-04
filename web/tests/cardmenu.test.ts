import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/svelte";
import { get } from "svelte/store";
import CardMenu from "../src/components/CardMenu.svelte";
import SortedInto from "../src/components/SortedInto.svelte";
import VisitCard from "../src/components/VisitCard.svelte";
import { dragged } from "../src/lib/drag";
import { canEdit, toast } from "../src/lib/session";
import type { Visit } from "../src/lib/api";

const visit: Visit = {
  id: 7, started_at: "2026-11-03T09:12:00+01:00", ended_at: "2026-11-03T09:14:00+01:00", category: "birds",
  species: { scientific: "Parus major", name: "great tit" }, subject: "species", confidence: 0.9, is_favourite: false,
  best_frame_url: null, clip_count: 1, duration_s: 5, poster_url: null, preview_url: null, corrected: false, watched: true,
};

const screenIs = (wide: boolean) =>
  vi.stubGlobal("matchMedia", (q: string) => ({ matches: wide, media: q, addEventListener() {}, removeEventListener() {} }));

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  canEdit.set(false);
  dragged.set(null);
  toast.set(null);
});

describe("CardMenu", () => {
  it("lists the other category under a Move to heading", () => {
    render(CardMenu, { current: "birds", onchoose: () => {}, onclose: () => {} });
    expect(screen.getByRole("menu")).toBeTruthy();
    expect(screen.getByText("Move to")).toBeTruthy();
    expect(screen.getAllByRole("menuitem").map((i) => i.textContent?.trim())).toEqual(["Other"]);
  });

  it("focuses the item; arrows keep it focused; choosing it moves", async () => {
    const onchoose = vi.fn();
    render(CardMenu, { current: "other", onchoose, onclose: () => {} });
    const [only] = screen.getAllByRole("menuitem");
    expect(only.textContent?.trim()).toBe("Birds");
    expect(document.activeElement).toBe(only);
    await fireEvent.keyDown(only, { key: "ArrowDown" });
    expect(document.activeElement).toBe(only);
    await fireEvent.keyDown(only, { key: "ArrowUp" });
    expect(document.activeElement).toBe(only);
    await fireEvent.click(only);
    expect(onchoose).toHaveBeenCalledWith("birds");
  });

  it("Escape asks to close", async () => {
    const onclose = vi.fn();
    render(CardMenu, { current: "other", onchoose: () => {}, onclose });
    await fireEvent.keyDown(screen.getAllByRole("menuitem")[0], { key: "Escape" });
    expect(onclose).toHaveBeenCalled();
  });
});

describe("VisitCard ⋯ button", () => {
  it("is there for an editor on a wide screen", () => {
    screenIs(true);
    canEdit.set(true);
    render(VisitCard, { visit, today: "2026-11-03" });
    const more = screen.getByRole("button", { name: "More actions for Great tit" });
    expect(more.getAttribute("aria-haspopup")).toBe("menu");
    expect(more.getAttribute("aria-expanded")).toBe("false");
    expect(more.closest("a")).toBeNull();
    expect(screen.getByRole("link").getAttribute("draggable")).toBe("true");
  });

  it("is not rendered when locked", () => {
    screenIs(true);
    render(VisitCard, { visit, today: "2026-11-03" });
    expect(screen.queryByRole("button", { name: /More actions/ })).toBeNull();
    expect(screen.getByRole("link").getAttribute("draggable")).toBeNull();
  });

  it("is not rendered under 768px", () => {
    screenIs(false);
    canEdit.set(true);
    render(VisitCard, { visit, today: "2026-11-03" });
    expect(screen.queryByRole("button", { name: /More actions/ })).toBeNull();
  });

  it("is not rendered in select mode", () => {
    screenIs(true);
    canEdit.set(true);
    render(VisitCard, { visit, today: "2026-11-03", selecting: true });
    expect(screen.queryByRole("button", { name: /More actions/ })).toBeNull();
  });

  it("opens the menu, and Escape closes it and returns focus to ⋯", async () => {
    screenIs(true);
    canEdit.set(true);
    render(VisitCard, { visit, today: "2026-11-03" });
    const more = screen.getByRole("button", { name: "More actions for Great tit" });
    await fireEvent.click(more);
    expect(more.getAttribute("aria-expanded")).toBe("true");
    const items = screen.getAllByRole("menuitem");
    await fireEvent.keyDown(items[0], { key: "Escape" });
    expect(screen.queryByRole("menu")).toBeNull();
    expect(document.activeElement).toBe(more);
  });

  it("opening a second card's menu closes the first", async () => {
    screenIs(true);
    canEdit.set(true);
    render(VisitCard, { visit, today: "2026-11-03" });
    render(VisitCard, { visit: { ...visit, id: 8 }, today: "2026-11-03" });
    const [a, b] = screen.getAllByRole("button", { name: "More actions for Great tit" });
    await fireEvent.click(a);
    expect(screen.getAllByRole("menu")).toHaveLength(1);
    await fireEvent.mouseDown(b);
    await fireEvent.click(b);
    expect(a.getAttribute("aria-expanded")).toBe("false");
    expect(b.getAttribute("aria-expanded")).toBe("true");
    expect(screen.getAllByRole("menu")).toHaveLength(1);
  });

  it("choosing moves the visit with one bulk request", async () => {
    screenIs(true);
    canEdit.set(true);
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ undo_token: "t", changed: 1 }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    render(VisitCard, { visit, today: "2026-11-03" });
    await fireEvent.click(screen.getByRole("button", { name: "More actions for Great tit" }));
    await fireEvent.click(screen.getByRole("menuitem", { name: "Other" }));
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/visits/bulk");
    expect(JSON.parse(init.body as string)).toEqual({ visit_ids: [7], category: "other" });
    await vi.waitFor(() => expect(get(toast)?.text).toBe("Great tit moved to Other"));
  });
});

describe("SortedInto drop targets", () => {
  it("a drop on another category moves; a drop on its own does nothing", async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ undo_token: "t", changed: 1 }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    render(SortedInto, { sorted: { birds: 3, other: 1, favourites: 0 } as never });
    dragged.set({ id: 7, category: "birds", name: "Great tit" });
    const birds = screen.getByRole("link", { name: /^Birds/ });
    await fireEvent.drop(birds);
    expect(fetchMock).not.toHaveBeenCalled();
    const animals = screen.getByRole("link", { name: /^Other/ });
    await fireEvent.dragOver(animals);
    expect(animals.classList.contains("over")).toBe(true);
    await fireEvent.drop(animals);
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(get(dragged)).toBeNull();
  });

  it("a cancelled drag leaves no highlighted row", async () => {
    render(SortedInto, { sorted: { birds: 3, other: 1, favourites: 0 } as never });
    dragged.set({ id: 7, category: "birds", name: "Great tit" });
    const animals = screen.getByRole("link", { name: /^Other/ });
    await fireEvent.dragOver(animals);
    expect(animals.classList.contains("over")).toBe(true);
    dragged.set(null);
    await vi.waitFor(() => expect(animals.classList.contains("over")).toBe(false));
  });
});
