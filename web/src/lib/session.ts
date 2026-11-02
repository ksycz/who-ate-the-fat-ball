import { writable } from "svelte/store";
import { getJSON } from "./api";

export const canEdit = writable(false);

export interface Toast {
  text: string;
  undoToken?: string;
}
export const toast = writable<Toast | null>(null);

export function showToast(text: string, undoToken?: string): void {
  toast.set(undoToken === undefined ? { text } : { text, undoToken });
}

export async function loadSession(): Promise<void> {
  try {
    const me = await getJSON<{ can_edit: boolean }>("/api/me");
    canEdit.set(!!me.can_edit);
  } catch {
    canEdit.set(false);
  }
}
