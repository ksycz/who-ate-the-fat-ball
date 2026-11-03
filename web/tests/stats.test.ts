import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/svelte";
import Stats from "../src/pages/Stats.svelte";
import { cellText, heatLevel } from "../src/lib/format";
import { matchRoute } from "../src/lib/router";

const SLOTS = ["6–8 am", "8–10 am", "10 am–12 pm", "12–2 pm", "2–4 pm", "4–6 pm", "6–8 pm"];
const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function stats(over: Record<string, unknown> = {}) {
  return {
    weeks: 4,
    visits: 441,
    species: 6,
    busiest: "8–10 am",
    slots: SLOTS,
    heatmap: DAYS.map((day, i) => ({ day, cells: SLOTS.map((_, j) => (i === 1 && j === 1 ? 12 : i === 2 && j === 2 ? 1 : 0)) })),
    per_species: [
      { scientific: "Parus major", name: "great tit", visits: 168 },
      { scientific: "Cyanistes caeruleus", name: "blue tit", visits: 84 },
      { scientific: "Sitta europaea", name: "Eurasian nuthatch", visits: 1 },
    ],
    ...over,
  };
}

function serve(body: unknown, ok = true) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => (ok ? new Response(JSON.stringify(body), { status: 200 }) : new Response("{}", { status: 500 }))),
  );
}

beforeEach(() => window.history.replaceState(null, "", "/stats"));
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("heatLevel", () => {
  it("is 0 for no visits and 4 for the busiest", () => {
    expect(heatLevel(0, 12)).toBe(0);
    expect(heatLevel(12, 12)).toBe(4);
    expect(heatLevel(3, 12)).toBe(1);
    expect(heatLevel(4, 12)).toBe(2);
    expect(heatLevel(1, 12)).toBe(1);
    expect(heatLevel(0, 0)).toBe(0);
  });
});

describe("cellText", () => {
  it("pluralises visits", () => {
    expect(cellText("Tue", "8–10 am", 12)).toBe("Tue 8–10 am · 12 visits");
    expect(cellText("Wed", "10 am–12 pm", 1)).toBe("Wed 10 am–12 pm · 1 visit");
    expect(cellText("Sun", "6–8 pm", 0)).toBe("Sun 6–8 pm · 0 visits");
  });
});

describe("route", () => {
  it("knows /stats", () => expect(matchRoute("/stats").name).toBe("stats"));
});

describe("Stats page", () => {
  it("shows the tiles, bars and the default status line", async () => {
    serve(stats());
    render(Stats);
    await screen.findByText("441");
    expect(screen.getByRole("heading", { name: "Stats" })).toBeTruthy();
    expect(screen.getByText("Last 4 weeks")).toBeTruthy();
    expect(screen.getByText("8–10 am", { selector: ".value" })).toBeTruthy();
    expect(screen.getByRole("status").textContent).toBe("Tap a square to see the number of visits");
    expect(screen.getByText("great tit")).toBeTruthy();
    expect(screen.getAllByRole("button", { name: /visits?$/ })).toHaveLength(49);
  });

  it("shows a dash when nothing is busiest", async () => {
    serve(stats({ visits: 0, species: 0, busiest: null, per_species: [] }));
    render(Stats);
    await screen.findByText("—");
  });

  it("tapping a cell sets the status text and tapping again clears it", async () => {
    serve(stats());
    render(Stats);
    const cell = await screen.findByRole("button", { name: "Tue 8–10 am · 12 visits" });
    expect(cell.getAttribute("aria-pressed")).toBe("false");
    await fireEvent.click(cell);
    expect(screen.getByRole("status").textContent).toBe("Tue 8–10 am · 12 visits");
    expect(cell.getAttribute("aria-pressed")).toBe("true");
    await fireEvent.click(cell);
    expect(screen.getByRole("status").textContent).toBe("Tap a square to see the number of visits");
    expect(cell.getAttribute("aria-pressed")).toBe("false");
  });

  it("focusing a cell sets the status text too", async () => {
    serve(stats());
    render(Stats);
    const cell = await screen.findByRole("button", { name: "Wed 10 am–12 pm · 1 visit" });
    await fireEvent.focus(cell);
    expect(screen.getByRole("status").textContent).toBe("Wed 10 am–12 pm · 1 visit");
  });

  it("offers Try again when the first load fails", async () => {
    serve({}, false);
    render(Stats);
    await screen.findByText(/Couldn't reach the app/);
    serve(stats());
    await fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    await screen.findByText("441");
  });
});
