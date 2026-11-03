<script lang="ts">
  import type { Category } from "../lib/api";
  import { wide } from "../lib/media";
  import { CATEGORY_NAMES, plural } from "../lib/format";
  import { canEdit } from "../lib/session";

  let {
    kind,
    count,
    busy = false,
    onmove,
    onzip,
  }: {
    kind: Category | "favourites";
    count: number;
    busy?: boolean;
    onmove: (category: Category) => void;
    onzip: () => void;
  } = $props();

  const DOTS: Record<Category, string> = {
    birds: "var(--robin)",
    other_animals: "var(--dot-animals)",
    other: "var(--dot-other)",
  };
  const ALL: Category[] = ["birds", "other_animals", "other"];

  // A category list offers the other two; Favourites mixes them all, so it offers all three.
  const targets = $derived(ALL.filter((c) => kind === "favourites" || c !== kind));
  let moveOpen = $state(false);
  $effect(() => {
    void $wide;
    moveOpen = false; // the reveal only exists on the phone layout
  });
</script>

<div class="bar" role="region" aria-label="Selected visits">
  <span class="count">{plural(count, "visit")} selected</span>
  {#if $canEdit && !$wide && moveOpen}
    <div class="targets" role="group" aria-label="Move to">
      {#each targets as c (c)}
        <button type="button" class="ghost" disabled={busy || count === 0} onclick={() => onmove(c)}>
          <span class="dot" style:background={DOTS[c]}></span>{CATEGORY_NAMES[c]}
        </button>
      {/each}
    </div>
  {/if}
  <div class="actions">
    {#if $canEdit && $wide}
      {#each targets as c (c)}
        <button type="button" class="ghost" disabled={busy || count === 0} onclick={() => onmove(c)}>
          <span class="dot" style:background={DOTS[c]}></span>Move to {CATEGORY_NAMES[c]}
        </button>
      {/each}
    {:else if $canEdit}
      <button type="button" class="ghost" aria-expanded={moveOpen} disabled={count === 0} onclick={() => (moveOpen = !moveOpen)}>Move to…</button>
    {/if}
    <button type="button" class="zip" disabled={count === 0} onclick={onzip}>
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 4v11M7 10l5 5 5-5M5 20h14"></path></svg>Download .zip
    </button>
  </div>
</div>

<style>
  .bar {
    position: fixed; z-index: 8; left: 12px; right: 12px; bottom: calc(var(--nav-phone-h) + 12px);
    box-sizing: border-box; display: flex; flex-direction: column; gap: 10px; padding: 12px; border-radius: 18px;
    background: var(--ink); color: #fff; box-shadow: 0 8px 24px rgba(40, 30, 20, 0.3);
  }
  .count { padding: 0 4px; font-size: 14px; font-weight: 600; }
  .targets { display: flex; flex-direction: column; gap: 6px; }
  .actions { display: grid; grid-auto-flow: column; grid-auto-columns: minmax(0, 1fr); gap: 8px; }
  button {
    display: flex; align-items: center; justify-content: center; gap: 8px; min-height: 48px; padding: 0 14px;
    border-radius: 12px; font: inherit; font-size: 15px; font-weight: 600; cursor: pointer;
  }
  .ghost { border: 1px solid rgba(255, 255, 255, 0.45); background: transparent; color: #fff; }
  .zip { border: none; background: #fff; color: var(--robin-dark); }
  button:disabled { opacity: 0.5; cursor: default; }
  .dot { width: 9px; height: 9px; border-radius: 50%; flex: none; box-shadow: 0 0 0 1px rgba(255, 255, 255, 0.6); }
  @media (min-width: 768px) {
    .bar {
      position: sticky; top: 12px; bottom: auto; left: auto; right: auto; flex-direction: row; flex-wrap: wrap;
      align-items: center; justify-content: space-between; gap: 12px; padding: 12px 14px 12px 18px; border-radius: 16px;
    }
    .count { padding: 0; font-size: 15px; }
    .actions { order: 3; display: flex; gap: 10px; }
    button { min-height: 44px; font-size: 14px; }
  }
</style>
