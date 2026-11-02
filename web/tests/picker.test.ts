import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/svelte";
import { get } from "svelte/store";
import Visit from "../src/pages/Visit.svelte";
import Toast from "../src/components/Toast.svelte";
import { route } from "../src/lib/router";
import { canEdit, serverDay, toast } from "../src/lib/session";
import type { Visit as VisitData } from "../src/lib/api";

type Detail = VisitData & { clips: []; guesses: [] };

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
    best_frame_url: null,
    clip_count: 0,
    duration_s: null,
    poster_url: null,
    preview_url: null,
    corrected: false,
    watched: false,
    clips: [],
    guesses: [],
    ...over,
  };
}

const SPECIES = [
  { scientific: "Parus major", name: "great tit", group: "bird", visits: 12, last_seen_at: "2026-11-03T09:00:00+01:00" },
  { scientific: "Cyanistes caeruleus", name: "blue tit", group: "bird", visits: 4, last_seen_at: null },
  { scientific: "Passer domesticus", name: "house sparrow", group: "bird", visits: 1, last_seen_at: null },
  { scientific: "Poecile palustris", name: "marsh tit", group: "bird", visits: 0, last_seen_at: null },
  { scientific: "Sciurus vulgaris", name: "red squirrel", group: "mammal", visits: 3, last_seen_at: null },
];

let fetchMock: ReturnType<typeof vi.fn>;
let current: Detail;
let patched: Partial<Detail> = {};
let patchResult: () => Response | Promise<Response>;
let undoResult: () => Response;

function serve(data: Detail) {
  current = data;
  patched = {};
  patchResult = () => new Response(JSON.stringify({ undo_token: "tok9" }), { status: 200 });
  undoResult = () => new Response(null, { status: 204 });
  fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === "/api/visits/5" && init?.method === "PATCH") {
      const r = await patchResult();
      if (r.ok) current = { ...current, ...patched };
      return r;
    }
    if (url === "/api/visits/5") return new Response(JSON.stringify(current), { status: 200 });
    if (url === "/api/species") return new Response(JSON.stringify(SPECIES), { status: 200 });
    if (url === "/api/status") return new Response(JSON.stringify({ day: "2026-11-03" }), { status: 200 });
    if (url === "/api/undo/tok9") return undoResult();
    return new Response(JSON.stringify({ detail: "nope" }), { status: 404 });
  });
  vi.stubGlobal("fetch", fetchMock);
}

const patchBody = () => JSON.parse(fetchMock.mock.calls.find((c) => c[1]?.method === "PATCH")![1].body);

async function openPicker() {
  render(Visit);
  const opener = await screen.findByRole("button", { name: "Not right? Change" });
  await fireEvent.click(opener);
  const dialog = await screen.findByRole("dialog", { name: "What is it?" });
  await within(dialog).findByRole("button", { name: /Blue tit/ });
  return { opener, dialog };
}

beforeEach(() => {
  canEdit.set(true);
  toast.set(null);
  serverDay.set("2026-11-03");
  route.set({ name: "visit", params: { id: "5" } });
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("Picker", () => {
  it("seen_birds_listed_and_current_marked_pressed", async () => {
    serve(detail());
    const { dialog } = await openPicker();
    expect(dialog.getAttribute("aria-modal")).toBe("true");
    const names = within(dialog).getAllByRole("button", { name: /^(Great tit|Blue tit|House sparrow)/ }).map((b) => b.textContent);
    expect(names.join("|")).toMatch(/Great tit.*Blue tit.*House sparrow/);
    expect(within(dialog).queryByRole("button", { name: /Marsh tit/ })).toBeNull();
    expect(within(dialog).queryByRole("button", { name: /red squirrel/i })).toBeNull();
    const great = within(dialog).getByRole("button", { name: /Great tit/ });
    expect(great.getAttribute("aria-pressed")).toBe("true");
    expect(within(dialog).getByRole("button", { name: /Blue tit/ }).getAttribute("aria-pressed")).toBe("false");
  });

  it("search_filters_catalog_and_shows_no_match_text", async () => {
    serve(detail());
    const { dialog } = await openPicker();
    const box = within(dialog).getByLabelText("Search all birds");
    await fireEvent.input(box, { target: { value: "MARSH" } });
    expect(within(dialog).getByRole("button", { name: /Marsh tit/ })).toBeTruthy();
    expect(within(dialog).queryByRole("button", { name: /Blue tit/ })).toBeNull();
    await fireEvent.input(box, { target: { value: "cyanistes" } });
    expect(within(dialog).getByRole("button", { name: /Blue tit/ })).toBeTruthy();
    await fireEvent.input(box, { target: { value: "squirrel" } });
    expect(within(dialog).getByText(/No bird called "squirrel"\. Try a shorter name\./)).toBeTruthy();
  });

  it("choosing_bird_patches_species_and_toasts_with_undo", async () => {
    serve(detail());
    patched = { species: { scientific: "Cyanistes caeruleus", name: "blue tit" } };
    await openPicker();
    await fireEvent.click(screen.getByRole("button", { name: /Blue tit/ }));
    await waitFor(() => expect(get(toast)).toEqual({ text: "Changed to Blue tit", undoToken: "tok9" }));
    expect(patchBody()).toEqual({ species: "Cyanistes caeruleus" });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("choosing_bird_for_a_visit_in_other_says_moved", async () => {
    serve(detail({ category: "other", species: null, subject: "nothing" }));
    await openPicker();
    await fireEvent.click(screen.getByRole("button", { name: /Blue tit/ }));
    await waitFor(() => expect(get(toast)?.text).toBe("Moved to Birds"));
  });

  it("not_a_bird_options_send_exact_bodies", async () => {
    const cases: [string, object, string][] = [
      ["Other animal", { category: "other_animals" }, "Moved to Other animals"],
      ["Dog", { species: "Canis lupus familiaris" }, "Moved to Other"],
      ["Nothing", { species: null, category: "other" }, "Moved to Other"],
    ];
    for (const [label, body, text] of cases) {
      serve(detail());
      toast.set(null);
      await openPicker();
      const dialog = screen.getByRole("dialog");
      expect(within(dialog).getByText("Squirrel, cat…")).toBeTruthy();
      expect(within(dialog).getByText("Moves to Other")).toBeTruthy();
      expect(within(dialog).getByText("Empty clip")).toBeTruthy();
      await fireEvent.click(within(dialog).getByRole("button", { name: new RegExp(label) }));
      await waitFor(() => expect(get(toast)?.text).toBe(text));
      expect(patchBody()).toEqual(body);
      cleanup();
    }
  });

  it("undo_posts_token_and_refreshes", async () => {
    serve(detail());
    patched = { species: { scientific: "Cyanistes caeruleus", name: "blue tit" } };
    render(Toast);
    await openPicker();
    await fireEvent.click(screen.getByRole("button", { name: /Blue tit/ }));
    await screen.findByRole("heading", { name: "Blue tit" });
    expect(screen.getByRole("status").textContent).toContain("Changed to Blue tit");
    current = detail(); // the server rolls back
    await fireEvent.click(screen.getByRole("button", { name: "Undo" }));
    await waitFor(() => {
      const post = fetchMock.mock.calls.find((c) => c[0] === "/api/undo/tok9");
      expect(post![1].method).toBe("POST");
    });
    await screen.findByRole("heading", { name: "Great tit" });
    expect(get(toast)).toBeNull();
  });

  it("undo_404_shows_couldnt_undo", async () => {
    serve(detail());
    undoResult = () => new Response(JSON.stringify({ detail: "gone" }), { status: 404 });
    render(Toast);
    toast.set({ text: "Changed to Blue tit", undoToken: "tok9" });
    await fireEvent.click(await screen.findByRole("button", { name: "Undo" }));
    await waitFor(() => expect(screen.getByRole("status").textContent).toContain("Couldn't undo that"));
    expect(screen.queryByRole("button", { name: "Undo" })).toBeNull();
  });

  it("patch_403_keeps_picker_open_with_unlock_link", async () => {
    serve(detail());
    patchResult = () => new Response(JSON.stringify({ detail: "locked" }), { status: 403 });
    const { dialog } = await openPicker();
    await fireEvent.click(within(dialog).getByRole("button", { name: /Blue tit/ }));
    const alert = await within(dialog).findByRole("alert");
    expect(alert.textContent).toContain("Editing is locked on this device");
    expect(within(alert).getByRole("link", { name: "Unlock" }).getAttribute("href")).toBe("/unlock");
    expect(screen.getByRole("dialog")).toBeTruthy();
    expect(get(toast)).toBeNull();
  });

  it("network_error_keeps_picker_open_with_wifi_text", async () => {
    serve(detail());
    patchResult = () => {
      throw new TypeError("Failed to fetch");
    };
    const { dialog } = await openPicker();
    await fireEvent.click(within(dialog).getByRole("button", { name: /Blue tit/ }));
    const alert = await within(dialog).findByRole("alert");
    expect(alert.textContent).toBe("Couldn't save. Check the Wi-Fi and try again.");
  });

  it("esc_closes_and_returns_focus", async () => {
    serve(detail());
    const { opener } = await openPicker();
    expect(screen.getByRole("dialog").contains(document.activeElement)).toBe(true);
    await fireEvent.keyDown(document.activeElement!, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(document.activeElement).toBe(opener);
  });

  it("tab_stays_inside_the_dialog", async () => {
    serve(detail());
    const { dialog } = await openPicker();
    const all = dialog.querySelectorAll<HTMLElement>("button, input");
    const last = all[all.length - 1];
    last.focus();
    await fireEvent.keyDown(last, { key: "Tab" });
    expect(dialog.contains(document.activeElement)).toBe(true);
    expect(document.activeElement).toBe(all[0]);
  });
});
