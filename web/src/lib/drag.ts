import { writable } from "svelte/store";
import type { Category } from "./api";

// The visit card being dragged on the Mac, or null. The side menu's rows read it to become drop targets.
export interface Dragged {
  id: number;
  category: Category;
  name: string;
}
export const dragged = writable<Dragged | null>(null);
