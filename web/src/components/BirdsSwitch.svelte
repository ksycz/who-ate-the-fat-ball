<script lang="ts">
  import { navigate } from "../lib/router";

  // Birds has two views of the same visits; switching replaces the history entry, so Back leaves Birds.
  let { view }: { view: "all" | "species" } = $props();

  const parts = [
    { key: "all", label: "All visits", path: "/birds" },
    { key: "species", label: "By species", path: "/birds/species" },
  ] as const;

  function pick(part: (typeof parts)[number]) {
    if (part.key !== view) navigate(part.path, { replace: true });
  }
</script>

<div class="switch" role="group" aria-label="View">
  {#each parts as part (part.key)}
    <button type="button" class:on={part.key === view} aria-pressed={part.key === view} onclick={() => pick(part)}>{part.label}</button>
  {/each}
</div>

<style>
  .switch {
    display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 4px; padding: 4px;
    background: #E9DFD2; border-radius: 14px;
  }
  button {
    min-height: 44px; border-radius: 11px; border: 1px solid transparent; background: transparent; color: var(--ink);
    font: inherit; font-size: 15px; font-weight: 500; cursor: pointer;
  }
  button.on { background: #fff; border-color: #C9BBA8; font-weight: 600; box-shadow: 0 1px 3px rgba(46, 33, 22, 0.15); }
  @media (min-width: 768px) {
    .switch { max-width: 360px; }
  }
</style>
