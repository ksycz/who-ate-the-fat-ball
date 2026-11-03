import type { Visit } from "./api";
import { changes } from "./session";

// What a list page had on screen when it was left, so Back lands in the same place with the same items.
export interface ListState {
  visits: Visit[];
  cursor: string | null;
  scrollY: number;
}

const lists = new Map<string, ListState>();
let todayY = 0;

export function saveList(kind: string, state: ListState): void {
  lists.set(kind, state);
}

export function loadList(kind: string): ListState | undefined {
  return lists.get(kind);
}

// The Other page's chosen filter, so Back from a visit lands on the same filter.
let otherFilter = "all";
export const saveOtherFilter = (f: string) => (otherFilter = f);
export const loadOtherFilter = () => otherFilter;

export function clearLists(): void {
  lists.clear();
}

export function saveTodayScroll(y: number): void {
  todayY = y;
}

export function loadTodayScroll(): number {
  return todayY;
}

// Anything that changed the library makes the remembered items stale.
let first = true;
changes.subscribe(() => {
  if (first) first = false;
  else clearLists();
});
