import { writable } from "svelte/store";

export type RouteName =
  | "today"
  | "visit"
  | "birds"
  | "other-animals"
  | "other"
  | "favourites"
  | "more"
  | "status"
  | "unlock"
  | "setup"
  | "notfound";

export interface Route {
  name: RouteName;
  params: Record<string, string>;
}

const FIXED: Record<string, RouteName> = {
  "/": "today",
  "/birds": "birds",
  "/other-animals": "other-animals",
  "/other": "other",
  "/favourites": "favourites",
  "/more": "more",
  "/status": "status",
  "/unlock": "unlock",
  "/setup": "setup",
};

export function matchRoute(path: string): Route {
  const clean = path.length > 1 ? path.replace(/\/+$/, "") : path;
  const fixed = FIXED[clean];
  if (fixed) return { name: fixed, params: {} };
  const visit = /^\/visit\/(\d+)$/.exec(clean);
  if (visit) return { name: "visit", params: { id: visit[1] } };
  return { name: "notfound", params: {} };
}

export const route = writable<Route>(matchRoute(window.location.pathname));

// Pages we push carry this marker in history.state, so back() knows the previous entry is ours.
const OWN = { fatball: true };

// True when the last page change was Back/Forward, so lists restore where they were; a click starts fresh.
export const arrival = { viaHistory: false };

export function navigate(path: string, opts: { replace?: boolean } = {}): void {
  arrival.viaHistory = false;
  if (opts.replace) window.history.replaceState(OWN, "", path);
  else window.history.pushState(OWN, "", path);
  route.set(matchRoute(new URL(path, window.location.origin).pathname));
}

export function back(fallback = "/"): void {
  if (window.history.state?.fatball) {
    window.history.back();
  } else {
    navigate(fallback);
  }
}

window.addEventListener("popstate", () => {
  arrival.viaHistory = true;
  route.set(matchRoute(window.location.pathname));
});
