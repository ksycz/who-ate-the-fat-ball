import { navigate } from "./router";

// Svelte action: turn a plain in-app <a href> into a router navigation (new tabs and modified clicks still work).
export function link(node: HTMLAnchorElement) {
  function onClick(e: MouseEvent) {
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    if (node.target && node.target !== "_self") return;
    const href = node.getAttribute("href");
    if (!href || !href.startsWith("/")) return;
    e.preventDefault();
    navigate(href);
  }
  node.addEventListener("click", onClick);
  return { destroy: () => node.removeEventListener("click", onClick) };
}
