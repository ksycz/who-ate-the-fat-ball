import { writable } from "svelte/store";
import { send, type Category } from "./api";
import { CATEGORY_NAMES, plural } from "./format";
import { route } from "./router";
import { noteChanged, showSaveFailure, showToast } from "./session";

interface Selection {
  on: boolean;
  ids: Set<number>;
}

const store = writable<Selection>({ on: false, ids: new Set() });

export const selection = {
  subscribe: store.subscribe,
  enter: () => store.update((s) => ({ ...s, on: true })),
  toggle: (id: number) =>
    store.update((s) => {
      const ids = new Set(s.ids);
      if (!ids.delete(id)) ids.add(id);
      return { ...s, ids };
    }),
  selectAll: (ids: number[]) => store.update((s) => ({ ...s, ids: new Set(ids) })),
  // Leaves select mode and forgets the picks.
  clear: () => store.set({ on: false, ids: new Set() }),
};

// Picks never follow you to another page.
route.subscribe(() => selection.clear());

// "Great tit moved to Other" for one named visit, "3 visits moved to Other" otherwise.
export function movedText(count: number, to: Category, name?: string): string {
  const what = count === 1 && name ? name : plural(count, "visit");
  return `${what} moved to ${CATEGORY_NAMES[to]}`;
}

// Move visits to a category in one go; the toast offers Undo. Used by the Select bar (and by drag, later).
export async function moveVisits(ids: number[], category: Category, name?: string): Promise<void> {
  try {
    const { undo_token, changed } = await send<{ undo_token: string | null; changed: number }>(
      "POST",
      "/api/visits/bulk",
      { visit_ids: ids, category },
    );
    if (changed === 0 || !undo_token) {
      showToast("Nothing changed");
    } else {
      showToast(movedText(changed, category, changed === ids.length ? name : undefined), undo_token);
      noteChanged();
    }
    selection.clear();
  } catch (e) {
    showSaveFailure(e); // the picks stay, so the owner can try again
  }
}
