import { readable } from "svelte/store";

// This device's clock in ms, refreshed every 30 s while anything is listening, so "N min ago" keeps moving.
export const tick = readable(Date.now(), (set) => {
  set(Date.now());
  const timer = setInterval(() => set(Date.now()), 30_000);
  return () => clearInterval(timer);
});
