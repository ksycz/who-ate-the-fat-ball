import { beforeEach, describe, expect, it } from "vitest";
import { get } from "svelte/store";
import { back, matchRoute, navigate, route } from "../src/lib/router";

describe("matchRoute", () => {
  it("parses a visit id", () => {
    expect(matchRoute("/visit/12")).toEqual({ name: "visit", params: { id: "12" } });
  });
  it("no longer has a Videos page", () => {
    expect(matchRoute("/videos").name).toBe("notfound");
  });
  it("names the fixed pages", () => {
    expect(matchRoute("/").name).toBe("today");
    expect(matchRoute("/birds").name).toBe("birds");
    expect(matchRoute("/other-animals").name).toBe("other"); // the old section opens Other
    expect(matchRoute("/other").name).toBe("other");
    expect(matchRoute("/favourites").name).toBe("favourites");
    expect(matchRoute("/more").name).toBe("more");
    expect(matchRoute("/status").name).toBe("status");
    expect(matchRoute("/unlock").name).toBe("unlock");
    expect(matchRoute("/setup").name).toBe("setup");
  });
  it("parses the By species page and one species, decoding its name", () => {
    expect(matchRoute("/birds/species")).toEqual({ name: "birds-species", params: {} });
    expect(matchRoute("/birds/species/Parus%20major")).toEqual({ name: "species", params: { scientific: "Parus major" } });
    expect(matchRoute("/birds/species/Parus%20major/")).toEqual({ name: "species", params: { scientific: "Parus major" } });
    expect(matchRoute("/birds/species/%E0%A4%A").name).toBe("notfound");
  });
  it("sends unknown paths to notfound", () => {
    expect(matchRoute("/nope").name).toBe("notfound");
    expect(matchRoute("/visit/abc").name).toBe("notfound");
    expect(matchRoute("/visit").name).toBe("notfound");
  });
});

describe("navigation", () => {
  beforeEach(() => {
    window.history.replaceState(null, "", "/");
  });

  it("navigate pushes state and updates the route", () => {
    navigate("/birds");
    expect(window.location.pathname).toBe("/birds");
    expect(get(route).name).toBe("birds");
  });

  it("back() with no history of our own goes to the fallback", () => {
    back("/birds");
    expect(window.location.pathname).toBe("/birds");
    expect(get(route).name).toBe("birds");
  });
});
