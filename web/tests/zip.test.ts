import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/svelte";
import { get } from "svelte/store";
import ZipConfirm from "../src/components/ZipConfirm.svelte";
import { askZip, startDownload } from "../src/lib/zip";
import { toast } from "../src/lib/session";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  toast.set(null);
});

describe("askZip", () => {
  it("posts the body and returns the plan", async () => {
    const plan = { token: "t1", size_bytes: 1000, visits: 3, files: 5, filename: "fat-ball-3-visits.zip" };
    const fetchMock = vi.fn(async () => new Response(JSON.stringify(plan), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    expect(await askZip({ visit_ids: [1, 2, 3] })).toEqual(plan);
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/downloads/zip");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({ visit_ids: [1, 2, 3] });
  });
});

describe("startDownload", () => {
  it("clicks a temporary download link to the token url, then removes it", () => {
    let seen: HTMLAnchorElement | null = null;
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      seen = this;
    });
    startDownload("abc", "fat-ball-1-visits.zip");
    expect(seen!.getAttribute("href")).toBe("/api/downloads/zip/abc");
    expect(seen!.getAttribute("download")).toBe("fat-ball-1-visits.zip");
    expect(document.body.contains(seen)).toBe(false);
  });
});

describe("ZipConfirm", () => {
  const info = { token: "abc", size_bytes: 14_200_000, visits: 3, filename: "fat-ball-3-visits.zip" };

  it("asks with the count and size", () => {
    render(ZipConfirm, { info, ondone: () => {} });
    expect(screen.getByRole("dialog")).toBeTruthy();
    expect(screen.getByText("Download 3 visits (14.2 MB)?")).toBeTruthy();
  });

  it("uses the singular for one visit", () => {
    render(ZipConfirm, { info: { ...info, visits: 1, size_bytes: 820_000 }, ondone: () => {} });
    expect(screen.getByText("Download 1 visit (820 KB)?")).toBeTruthy();
  });

  it("Download starts it and says so", async () => {
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    const ondone = vi.fn();
    render(ZipConfirm, { info, ondone });
    await fireEvent.click(screen.getByRole("button", { name: "Download" }));
    expect(click).toHaveBeenCalledOnce();
    expect(get(toast)?.text).toBe("Downloading 3 visits (14.2 MB)…");
    expect(ondone).toHaveBeenCalled();
  });

  it("Cancel downloads nothing", async () => {
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    const ondone = vi.fn();
    render(ZipConfirm, { info, ondone });
    await fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(click).not.toHaveBeenCalled();
    expect(get(toast)).toBeNull();
    expect(ondone).toHaveBeenCalled();
  });

  it("gives focus back to the button that opened it", async () => {
    const opener = document.createElement("button");
    document.body.appendChild(opener);
    opener.focus();
    const { unmount } = render(ZipConfirm, { info, ondone: () => {} });
    expect(document.activeElement).not.toBe(opener);
    unmount();
    expect(document.activeElement).toBe(opener);
    opener.remove();
  });

  it("Esc closes it", async () => {
    const ondone = vi.fn();
    render(ZipConfirm, { info, ondone });
    await fireEvent.keyDown(window, { key: "Escape" });
    expect(ondone).toHaveBeenCalled();
  });
});
