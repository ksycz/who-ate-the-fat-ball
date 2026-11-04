import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import { get } from "svelte/store";
import Species from "../src/pages/Species.svelte";
import SpeciesCard from "../src/components/SpeciesCard.svelte";
import VisitList from "../src/pages/VisitList.svelte";
import { noteServerDay, period } from "../src/lib/session";
import { clearLists, rememberSpeciesName } from "../src/lib/listCache";
import { route } from "../src/lib/router";

const row = (over: Record<string, unknown> = {}) => ({
  scientific: "Parus major", name: "great tit", visits: 42, last_seen_at: "2026-11-03T08:47:00+01:00",
  first_seen_at: "2026-09-01T08:00:00+01:00", is_new: false, photo_url: "/media/p.jpg", ...over,
});

let fetchMock: ReturnType<typeof vi.fn>;
function serve(species: unknown[]) {
  fetchMock = vi.fn(async (url: string) => {
    if (url.startsWith("/api/species")) return new Response(JSON.stringify(species), { status: 200 });
    if (url.startsWith("/api/visits")) return new Response(JSON.stringify({ items: [], next_cursor: null }), { status: 200 });
    if (url === "/api/today") return new Response(JSON.stringify({ day: "2026-11-03", new_species: null }), { status: 200 });
    return new Response("{}", { status: 404 });
  });
  vi.stubGlobal("fetch", fetchMock);
}
const speciesUrls = () => fetchMock.mock.calls.map((c) => c[0] as string).filter((u) => u.startsWith("/api/species"));

beforeEach(() => {
  noteServerDay("2026-11-03");
  period.set("week");
  clearLists();
  window.history.replaceState(null, "", "/birds/species");
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("SpeciesCard", () => {
  it("says 42 visits and 1 visit", () => {
    render(SpeciesCard, { species: row(), today: "2026-11-03" });
    expect(screen.getByText("42")).toBeTruthy();
    expect(screen.getByText("visits")).toBeTruthy();
    cleanup();
    render(SpeciesCard, { species: row({ visits: 1 }), today: "2026-11-03" });
    expect(screen.getByText("visit")).toBeTruthy();
    expect(screen.queryByText("visits")).toBeNull();
  });

  it("links to the encoded scientific name, with the last visit and a New tag", () => {
    render(SpeciesCard, { species: row({ is_new: true }), today: "2026-11-03" });
    expect(screen.getByRole("link").getAttribute("href")).toBe("/birds/species/Parus%20major");
    expect(screen.getByText("Last seen today 08:47")).toBeTruthy();
    expect(screen.getByText("New")).toBeTruthy();
    expect(screen.getByText("Great tit")).toBeTruthy();
  });

  it("has no New tag for an older species", () => {
    render(SpeciesCard, { species: row(), today: "2026-11-03" });
    expect(screen.queryByText("New")).toBeNull();
  });
});

describe("By species", () => {
  it("shows the period chips, the subtitle and a card per species, week by default", async () => {
    serve([row(), row({ scientific: "Cyanistes caeruleus", name: "blue tit", visits: 3 })]);
    render(Species);
    await screen.findByText("Great tit");
    expect(speciesUrls()).toEqual(["/api/species?period=week"]);
    expect(screen.getByText("2 species · this week")).toBeTruthy();
    expect(screen.getByRole("button", { name: "This week" }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getAllByRole("link")).toHaveLength(2);
  });

  it("switches period and asks again, with the new period's subtitle", async () => {
    serve([row()]);
    render(Species);
    await screen.findByText("Great tit");
    await fireEvent.click(screen.getByRole("button", { name: "This month" }));
    await waitFor(() => expect(speciesUrls()).toContain("/api/species?period=month"));
    expect(get(period)).toBe("month");
    expect(await screen.findByText("1 species · this month")).toBeTruthy();
  });

  it("hides the subtitle and the old cards while the new period loads", async () => {
    serve([row()]);
    render(Species);
    await screen.findByText("Great tit");
    let release: (r: Response) => void = () => {};
    fetchMock.mockImplementationOnce(() => new Promise<Response>((r) => (release = r)));
    await fireEvent.click(screen.getByRole("button", { name: "This month" }));
    expect(screen.queryByText("Great tit")).toBeNull();
    expect(screen.queryByText(/species ·/)).toBeNull();
    release(new Response(JSON.stringify([row({ visits: 5 })]), { status: 200 }));
    expect(await screen.findByText("1 species · this month")).toBeTruthy();
  });

  it("on a failure shows the message and Try again, with no old cards, and Try again reloads", async () => {
    serve([row()]);
    render(Species);
    await screen.findByText("Great tit");
    fetchMock.mockImplementationOnce(async () => {
      throw new TypeError("Failed to fetch");
    });
    await fireEvent.click(screen.getByRole("button", { name: "This month" }));
    expect(await screen.findByText("Couldn't load the birds. Check the Wi-Fi and try again.")).toBeTruthy();
    expect(screen.queryByText("Great tit")).toBeNull();
    expect(screen.queryByText(/species ·/)).toBeNull();
    const before = speciesUrls().length;
    await fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("Great tit")).toBeTruthy();
    expect(speciesUrls().length).toBe(before + 1);
    expect(screen.queryByText("Couldn't load the birds. Check the Wi-Fi and try again.")).toBeNull();
  });

  it("says so when there are no birds", async () => {
    serve([]);
    render(Species);
    expect(await screen.findByText("No birds this week")).toBeTruthy();
    expect(screen.getByText("0 species · this week")).toBeTruthy();
  });

  it("has the All visits | By species switch, By species pressed", async () => {
    serve([row()]);
    render(Species);
    const group = screen.getByRole("group", { name: "View" });
    expect(group).toBeTruthy();
    expect(screen.getByRole("button", { name: "By species" }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByRole("button", { name: "All visits" }).getAttribute("aria-pressed")).toBe("false");
    await fireEvent.click(screen.getByRole("button", { name: "All visits" }));
    expect(window.location.pathname).toBe("/birds");
    expect(get(route).name).toBe("birds");
  });
});

describe("Birds › All visits", () => {
  it("has the switch with All visits pressed and no period chips", async () => {
    serve([]);
    render(VisitList, { kind: "birds" });
    expect(screen.getByRole("button", { name: "All visits" }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByRole("button", { name: "By species" }).getAttribute("aria-pressed")).toBe("false");
    expect(screen.queryByRole("button", { name: "This week" })).toBeNull();
    await fireEvent.click(screen.getByRole("button", { name: "By species" }));
    expect(window.location.pathname).toBe("/birds/species");
  });

  it("does not show the switch on other lists", () => {
    serve([]);
    render(VisitList, { kind: "other_animals" });
    expect(screen.queryByRole("group", { name: "View" })).toBeNull();
  });
});

describe("one species' visits", () => {
  it("asks for that species only and is titled with its name", async () => {
    serve([]);
    render(VisitList, { kind: "birds", species: "Parus major" });
    await waitFor(() => expect(fetchMock.mock.calls.some((c) => String(c[0]).startsWith("/api/visits"))).toBe(true));
    const url = fetchMock.mock.calls.map((c) => String(c[0])).find((u) => u.startsWith("/api/visits"))!;
    const q = new URL(url, "http://x").searchParams;
    expect(q.get("category")).toBe("birds");
    expect(q.get("species")).toBe("Parus major");
    expect(screen.queryByRole("group", { name: "View" })).toBeNull();
    expect(screen.getByRole("button", { name: "Back" })).toBeTruthy();
  });

  it("titles itself with the remembered name at once, and never flashes the scientific name", async () => {
    rememberSpeciesName("Parus major", "Great tit");
    serve([]);
    render(VisitList, { kind: "birds", species: "Parus major" });
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Great tit");
    cleanup();
    serve([]);
    render(VisitList, { kind: "birds", species: "Erithacus rubecula" });
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("");
    await waitFor(() => expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Erithacus rubecula"));
  });
});
