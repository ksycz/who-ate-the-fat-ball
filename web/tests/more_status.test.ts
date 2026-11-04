import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import { get } from "svelte/store";
import More from "../src/pages/More.svelte";
import AppStatus from "../src/pages/AppStatus.svelte";
import Unlock from "../src/pages/Unlock.svelte";
import Setup from "../src/pages/Setup.svelte";
import { canEdit, noteServerDay } from "../src/lib/session";
import { navigate, route } from "../src/lib/router";
import type { Status } from "../src/lib/api";

function status(over: Partial<Status> = {}): Status {
  return {
    day: "2026-11-02",
    now: "2026-11-02T10:02:00+00:00",
    local: true,
    camera: { state: "ok", last_seen_at: "2026-11-02T10:00:00+00:00", last_error: null },
    sorted: { birds: 41, other_animals: 3, other: 7, favourites: 12 },
    queue: { downloaded: 2, processing: 1, failed: 0 },
    recognition: { pending: 4, old_waiting: 0, errors: 0, model: true, examples: 10 },
    disk: { free_bytes: 12_400_000_000, low: false },
    ...over,
  };
}

let fetchMock: ReturnType<typeof vi.fn>;
function serve(st: Status, handlers: Record<string, () => Response> = {}) {
  fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const key = `${init?.method ?? "GET"} ${url}`;
    if (handlers[key]) return handlers[key]();
    if (url === "/api/status") return new Response(JSON.stringify(st), { status: 200 });
    return new Response("{}", { status: 404 });
  });
  vi.stubGlobal("fetch", fetchMock);
}
function narrow(matches: boolean) {
  vi.stubGlobal("matchMedia", (q: string) => ({ matches, media: q, addEventListener() {}, removeEventListener() {} }));
}

beforeEach(() => {
  noteServerDay("2026-11-02");
  canEdit.set(false);
  window.history.replaceState(null, "", "/more");
  narrow(false);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("More", () => {
  it("more_lists_sorted_counts_and_links", async () => {
    serve(status());
    render(More);
    await screen.findByText("41");
    const birds = screen.getByRole("link", { name: /Birds/ });
    expect(birds.getAttribute("href")).toBe("/birds");
    expect(screen.getByRole("link", { name: /Other animals/ }).textContent).toContain("3");
    expect(screen.getByRole("link", { name: /^Other\b(?! animals)/ }).textContent).toContain("7");
    expect(screen.getByRole("link", { name: /Favourites/ }).getAttribute("href")).toBe("/favourites");
    expect(screen.getByRole("link", { name: /App status/ }).getAttribute("href")).toBe("/status");
    expect(screen.getByRole("link", { name: "Unlock editing" }).getAttribute("href")).toBe("/unlock");
  });

  it("hides_unlock_when_editing_is_on", async () => {
    canEdit.set(true);
    serve(status());
    render(More);
    await screen.findByRole("link", { name: /Birds/ });
    expect(screen.queryByRole("link", { name: "Unlock editing" })).toBeNull();
  });

  it("camera_text_updates_every_30_seconds", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "Date"] });
    vi.setSystemTime(new Date(2026, 10, 2, 10, 2, 0));
    serve(status({ camera: { state: "ok", last_seen_at: "2026-11-02T10:00:00+00:00", last_error: null } }));
    render(More);
    await screen.findByText(/Camera seen 2 min ago/);
    await act(() => vi.advanceTimersByTimeAsync(30_000));
    expect(screen.getByText(/Camera seen 2 min ago/)).toBeTruthy();
    await act(() => vi.advanceTimersByTimeAsync(30_000));
    expect(screen.getByText(/Camera seen 3 min ago/)).toBeTruthy();
    vi.useRealTimers();
  });

  it("wide_layout_never_renders_the_heading", async () => {
    narrow(true);
    serve(status());
    render(More);
    expect(screen.queryByRole("heading", { name: "More" })).toBeNull();
    await waitFor(() => expect(get(route).name).toBe("today"));
    expect(screen.queryByRole("heading", { name: "More" })).toBeNull();
  });

  it("wide_layout_redirects_to_today_without_a_history_entry", async () => {
    narrow(true);
    serve(status());
    const before = window.history.length;
    render(More);
    await waitFor(() => expect(get(route).name).toBe("today"));
    expect(window.history.length).toBe(before);
  });
});

describe("AppStatus", () => {
  it("status_explains_wrong_password", async () => {
    serve(status({ camera: { state: "problem", last_seen_at: "2026-11-02T09:00:00+00:00", last_error: "wrong_password" } }));
    render(AppStatus);
    expect(await screen.findByText("The camera rejected the password. Set it again in Setup.")).toBeTruthy();
    expect(screen.getByText(/Last seen/)).toBeTruthy();
  });

  it("status_explains_other_errors", async () => {
    serve(status({ camera: { state: "problem", last_seen_at: null, last_error: "weird" } }));
    render(AppStatus);
    expect(await screen.findByText("Something went wrong (weird). The app keeps trying.")).toBeTruthy();
  });

  it("status_shows_low_disk_warning", async () => {
    serve(status({ disk: { free_bytes: 800_000_000, low: true } }));
    render(AppStatus);
    expect(await screen.findByText("Disk nearly full")).toBeTruthy();
    expect(screen.getByText("0.8 GB free")).toBeTruthy();
  });

  it("shows_free_disk_and_queue", async () => {
    serve(status());
    render(AppStatus);
    expect(await screen.findByText("12.4 GB free")).toBeTruthy();
    expect(screen.queryByText("Disk nearly full")).toBeNull();
    expect(screen.getByText("7 clips waiting")).toBeTruthy();
  });

  it("shows_the_waiting_count_once", async () => {
    serve(status());
    render(AppStatus);
    await screen.findByText("7 clips waiting");
    expect(screen.getAllByText(/waiting/)).toHaveLength(1);
  });

  it("setup_link_only_when_the_server_says_local", async () => {
    serve(status({ local: false }));
    const first = render(AppStatus);
    await screen.findByText("12.4 GB free");
    expect(screen.queryByRole("link", { name: "Setup" })).toBeNull();
    first.unmount();
    serve(status({ local: true }));
    render(AppStatus);
    expect((await screen.findByRole("link", { name: "Setup" })).getAttribute("href")).toBe("/setup");
  });
});

describe("Unlock", () => {
  const typePin = async (pin: string) => {
    const input = screen.getByLabelText("Edit PIN") as HTMLInputElement;
    expect(input.getAttribute("inputmode")).toBe("numeric");
    expect(input.getAttribute("autocomplete")).toBe("one-time-code");
    await fireEvent.input(input, { target: { value: pin } });
    await fireEvent.click(screen.getByRole("button", { name: "Unlock" }));
  };

  it("unlock_wrong_pin_message", async () => {
    serve(status(), { "POST /api/unlock": () => new Response(JSON.stringify({ detail: "wrong_pin" }), { status: 401 }) });
    render(Unlock);
    await typePin("1234");
    expect(await screen.findByText("That PIN isn't right")).toBeTruthy();
    expect(get(canEdit)).toBe(false);
  });

  it("unlock_429_message", async () => {
    serve(status(), { "POST /api/unlock": () => new Response("{}", { status: 429 }) });
    render(Unlock);
    await typePin("1234");
    expect(await screen.findByText("Too many tries. Wait 15 minutes and try again.")).toBeTruthy();
  });

  it("unlock_success_enables_editing_and_goes_back", async () => {
    serve(status(), { "POST /api/unlock": () => new Response(null, { status: 204 }) });
    navigate("/more");
    navigate("/unlock");
    render(Unlock);
    await typePin("1234");
    await waitFor(() => expect(get(canEdit)).toBe(true));
    await waitFor(() => expect(get(route).name).toBe("more"));
    expect(window.location.pathname).toBe("/more");
    expect(JSON.parse(fetchMock.mock.calls.find((c) => c[0] === "/api/unlock")![1].body)).toEqual({ pin: "1234" });
  });
});

describe("Setup", () => {
  it("setup_sends_only_filled_fields", async () => {
    serve(status(), { "PUT /api/setup": () => new Response(null, { status: 204 }) });
    render(Setup);
    const pw = (await screen.findByLabelText("Camera password")) as HTMLInputElement;
    expect(pw.type).toBe("password");
    expect(pw.value).toBe("");
    await fireEvent.input(screen.getByLabelText("Camera address"), { target: { value: "192.168.1.50" } });
    await fireEvent.input(pw, { target: { value: "test-password" } });
    await fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText("Saved")).toBeTruthy();
    const call = fetchMock.mock.calls.find((c) => c[0] === "/api/setup")!;
    expect(JSON.parse(call[1].body)).toEqual({ ip: "192.168.1.50", password: "test-password" });
    expect(pw.value).toBe("");
  });

  it("setup_rejects_a_bad_pin_without_sending", async () => {
    serve(status());
    render(Setup);
    await fireEvent.input(await screen.findByLabelText("Edit PIN"), { target: { value: "12" } });
    await fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText("The edit PIN is 4 digits")).toBeTruthy();
    expect(fetchMock.mock.calls.some((c) => c[0] === "/api/setup")).toBe(false);
  });

  it("setup_off_the_mac_message", async () => {
    serve(status(), { "PUT /api/setup": () => new Response("{}", { status: 403 }) });
    render(Setup);
    await fireEvent.input(await screen.findByLabelText("Camera address"), { target: { value: "192.168.1.50" } });
    await fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText("Setup only works on the Mac itself.")).toBeTruthy();
  });

  it("setup_off_the_mac_shows_the_message_instead_of_the_form", async () => {
    serve(status({ local: false }));
    render(Setup);
    expect(await screen.findByText("Setup only works on the Mac itself.")).toBeTruthy();
    expect(screen.queryByLabelText("Camera address")).toBeNull();
    expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
  });
});
