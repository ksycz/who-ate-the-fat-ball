<script lang="ts">
  import { onMount } from "svelte";
  import type { Category } from "../lib/api";
  import { CATEGORY_DOTS, CATEGORY_NAMES } from "../lib/format";

  // The ⋯ menu on a visit card: move it to the other category.
  // `button` is the ⋯ that opened it: clicking it is not "outside" (it toggles the menu itself).
  let { current, onchoose, onclose, button }: { current: Category; onchoose: (c: Category) => void; onclose: () => void; button?: HTMLElement } = $props();

  const ALL: Category[] = ["birds", "other"];
  const targets = $derived(ALL.filter((c) => c !== current));
  let items: HTMLButtonElement[] = $state([]);
  let root: HTMLDivElement;

  onMount(() => {
    items[0]?.focus();
    // A click anywhere else closes it (the ⋯ button toggles it itself).
    const away = (e: MouseEvent) => {
      const t = e.target as Node;
      if (!root.contains(t) && !button?.contains(t)) onclose();
    };
    document.addEventListener("mousedown", away);
    return () => document.removeEventListener("mousedown", away);
  });

  function onkeydown(e: KeyboardEvent) {
    const at = items.indexOf(document.activeElement as HTMLButtonElement);
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      const step = e.key === "ArrowDown" ? 1 : -1;
      items[(at + step + items.length) % items.length]?.focus();
    } else if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();
      onclose();
    } else if (e.key === "Tab") {
      onclose();
    }
  }
</script>

<!-- svelte-ignore a11y_interactive_supports_focus -->
<div class="menu" role="menu" aria-label="Move to" bind:this={root} {onkeydown}>
  <span class="head" aria-hidden="true">Move to</span>
  {#each targets as c, i (c)}
    <button type="button" role="menuitem" tabindex="-1" bind:this={items[i]} onclick={() => onchoose(c)}>
      <span class="dot" style:background={CATEGORY_DOTS[c]}></span>{CATEGORY_NAMES[c]}
    </button>
  {/each}
</div>

<style>
  .menu {
    position: absolute; z-index: 5; top: 50px; right: 8px; min-width: 190px; padding: 6px; border-radius: 14px;
    background: #fff; border: 1px solid var(--line); box-shadow: 0 8px 24px rgba(40, 30, 20, 0.22);
    display: flex; flex-direction: column; gap: 2px;
  }
  .head { padding: 6px 10px 4px; font-size: 12px; font-weight: 600; color: var(--ink-2); }
  button {
    display: flex; align-items: center; gap: 10px; min-height: 40px; padding: 0 10px; border: 0; border-radius: 10px;
    background: none; font: inherit; font-size: 14px; font-weight: 500; color: var(--ink); text-align: left; cursor: pointer;
  }
  button:hover, button:focus-visible { background: var(--robin-tint); outline: none; }
  .dot { width: 10px; height: 10px; border-radius: 50%; flex: none; box-shadow: 0 0 0 1px rgba(46, 33, 22, 0.45); }
</style>
