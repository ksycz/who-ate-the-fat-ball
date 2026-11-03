<script lang="ts">
  import type { Status } from "../lib/api";
  import { link } from "../lib/link";

  // `big` is the roomier phone list on the More page; the default is the compact side-menu box.
  let { sorted, current = "", big = false }: { sorted?: Status["sorted"]; current?: string; big?: boolean } = $props();

  const rows = $derived([
    { label: "Birds", href: "/birds", dot: "var(--robin)", count: sorted?.birds, name: "birds" },
    { label: "Other animals", href: "/other-animals", dot: "var(--dot-animals)", count: sorted?.other_animals, name: "other-animals" },
    { label: "Other", href: "/other", dot: "var(--dot-other)", count: sorted?.other, name: "other" },
  ]);
</script>

<div class="sorted" class:big role="group" aria-label="Sorted into">
  <span class="sorted-head" aria-hidden="true">Sorted into</span>
  {#each rows as s (s.label)}
    {@const on = current === s.name}
    <a class="item" href={s.href} use:link aria-current={on ? "page" : undefined} class:on>
      <span class="swatch" style:background={s.dot}></span>
      <span class="label">{s.label}</span>
      {#if s.count !== undefined}<span class="count">{s.count}</span>{/if}
    </a>
  {/each}
</div>

<style>
  .sorted {
    margin: 12px 0; padding: 10px 8px; border-radius: 16px; background: var(--sand); border: 1px solid var(--line);
    display: flex; flex-direction: column; gap: 4px;
  }
  .sorted-head { padding: 0 6px 4px; font-size: 12px; font-weight: 600; color: var(--ink-2); }
  .item {
    display: flex; align-items: center; gap: 12px; min-height: 44px; padding: 0 10px; border-radius: 12px;
    font-size: 14px; font-weight: 500; color: var(--ink);
  }
  .item.on { background: var(--robin-tint); font-weight: 600; color: var(--robin-dark); }
  .label { flex: 1; }
  .count { font-size: 12px; color: var(--ink-2); }
  .swatch { width: 10px; height: 10px; border-radius: 50%; flex: none; box-shadow: 0 0 0 1px rgba(46, 33, 22, 0.45); }
  .big { margin: 0; background: #fff; border: 0; border-radius: 18px; }
  .big .sorted-head { padding: 4px 8px 6px; font-size: 13px; }
  .big .item { min-height: 52px; font-size: 16px; }
  .big .count { font-size: 13px; }
</style>
