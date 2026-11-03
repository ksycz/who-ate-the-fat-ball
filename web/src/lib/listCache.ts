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

// Display names of species the owner has seen on By species, so a species page can title itself at once.
const speciesNames = new Map<string, string>();
export const rememberSpeciesName = (scientific: string, name: string) => speciesNames.set(scientific, name);
export const recallSpeciesName = (scientific: string) => speciesNames.get(scientific);

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
