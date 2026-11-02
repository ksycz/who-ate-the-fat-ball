import { writable } from "svelte/store";
import { ApiError, getJSON } from "./api";

export const canEdit = writable(false);

// The Mac's local date as the server sees it ("YYYY-MM-DD"); null until first known.
export const serverDay = writable<string | null>(null);
export function noteServerDay(day: string): void {
  serverDay.set(day);
}

export interface Toast {
  text: string;
  undoToken?: string;
  unlock?: boolean; // show an "Unlock" link after the text
}
export const toast = writable<Toast | null>(null);

export function showToast(text: string, undoToken?: string): void {
  toast.set(undoToken === undefined ? { text } : { text, undoToken });
}

// Counts successful undos; the page that made a change re-fetches itself when this goes up.
export const changes = writable(0);
export function noteUndone(): void {
  changes.update((n) => n + 1);
}

export const LOCKED_TEXT = "Editing is locked on this device";
export const NETWORK_TEXT = "Couldn't save. Check the Wi-Fi and try again.";

// What to tell the owner when saving a change failed.
export function saveFailure(e: unknown): { text: string; locked: boolean } {
  if (e instanceof ApiError) {
    if (e.status === 403) return { text: LOCKED_TEXT, locked: true };
    return { text: "Couldn't save that. Try again.", locked: false };
  }
  return { text: NETWORK_TEXT, locked: false };
}

export function showSaveFailure(e: unknown): void {
  const f = saveFailure(e);
  toast.set(f.locked ? { text: f.text, unlock: true } : { text: f.text });
}

export async function loadSession(): Promise<void> {
  try {
    const me = await getJSON<{ can_edit: boolean }>("/api/me");
    canEdit.set(!!me.can_edit);
  } catch {
    canEdit.set(false);
  }
  try {
    noteServerDay((await getJSON<{ day: string }>("/api/status")).day);
  } catch {
    // pages fall back to asking again
  }
}
