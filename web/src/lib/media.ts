import { readable } from "svelte/store";

// True while the screen is at least 768px wide (the Mac layout). Without matchMedia it stays false.
export const wide = readable(false, (set) => {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return;
  const query = window.matchMedia("(min-width: 768px)");
  const update = () => set(query.matches);
  update();
  query.addEventListener("change", update);
  return () => query.removeEventListener("change", update);
});
