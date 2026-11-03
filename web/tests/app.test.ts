import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/svelte";
import { navigate } from "../src/lib/router";
import App from "../src/App.svelte";

describe("App shell", () => {
  it("says the page is not found, with a link to Today", () => {
    navigate("/nope");
    render(App);
    expect(screen.getByRole("heading", { name: "Page not found" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Go to Today" }).getAttribute("href")).toBe("/");
  });
});
