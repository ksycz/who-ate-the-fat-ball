<script lang="ts">
  import { cellText, heatLevel } from "../lib/format";

  let { heatmap, slots }: { heatmap: { day: string; cells: number[] }[]; slots: string[] } = $props();

  const HINT = "Tap a square to see the number of visits";
  const SHORT = ["6am", "8am", "10am", "12pm", "2pm", "4pm", "6pm"];
  const COLOURS = [
    { bg: "#F1E8DC", border: "#C9BBA8" },
    { bg: "#F7E1D3", border: "#E39A72" },
    { bg: "#E39A72", border: "#E39A72" },
    { bg: "#B4491A", border: "#B4491A" },
    { bg: "#8F3712", border: "#8F3712" },
  ];

  let picked = $state<string | null>(null);
  let pickedText = $state(HINT);
  let focusedText = $state<string | null>(null);
  const detail = $derived(focusedText ?? pickedText);
  const max = $derived(Math.max(0, ...heatmap.flatMap((r) => r.cells)));
  let grid: HTMLElement | undefined = $state();

  function pick(key: string, text: string) {
    picked = picked === key ? null : key;
    pickedText = picked ? text : HINT;
    focusedText = null;
  }

  // Arrow keys move between squares.
  function keydown(e: KeyboardEvent, r: number, c: number) {
    const d: Record<string, [number, number]> = { ArrowUp: [-1, 0], ArrowDown: [1, 0], ArrowLeft: [0, -1], ArrowRight: [0, 1] };
    const step = d[e.key];
    if (!step) return;
    const nr = r + step[0];
    const nc = c + step[1];
    if (nr < 0 || nc < 0 || nr >= heatmap.length || nc >= slots.length) return;
    e.preventDefault();
    grid?.querySelector<HTMLElement>(`[data-cell="${nr}-${nc}"]`)?.focus();
  }
</script>

<div class="grid" role="grid" aria-label="Visits by day and time of day" bind:this={grid}>
  <div class="row" role="row">
    <span></span>
    {#each slots as slot, i (slot)}
      <span class="head" role="columnheader" aria-label={slot}>{SHORT[i] ?? slot}</span>
    {/each}
  </div>
  {#each heatmap as row, r (row.day)}
    <div class="row" role="row">
      <span class="head left" role="rowheader">{row.day}</span>
      {#each row.cells as n, c (c)}
        {@const key = `${r}-${c}`}
        {@const text = cellText(row.day, slots[c], n)}
        {@const colour = COLOURS[heatLevel(n, max)]}
        <span role="gridcell">
          <button
            type="button"
            data-cell={key}
            aria-label={text}
            aria-pressed={picked === key}
            class:on={picked === key}
            style="background: {colour.bg}; border-color: {colour.border}"
            onclick={() => pick(key, text)}
            onfocus={() => (focusedText = text)}
            onblur={() => (focusedText = null)}
            onkeydown={(e) => keydown(e, r, c)}
          ></button>
        </span>
      {/each}
    </div>
  {/each}
</div>
<div role="status" class="detail">{detail}</div>
<div class="legend">
  <span>Fewer</span>
  {#each COLOURS as c (c.bg)}<span class="swatch" style="background: {c.bg}; border-color: {c.border}"></span>{/each}
  <span>More visits</span>
</div>

<style>
  .grid { display: flex; flex-direction: column; gap: 4px; }
  .row { display: grid; grid-template-columns: 34px repeat(7, minmax(0, 1fr)); gap: 4px; align-items: center; }
  .row > [role="gridcell"] { display: block; min-width: 0; }
  .head { font-size: 11px; color: var(--ink-2); text-align: center; }
  .head.left { text-align: left; }
  button {
    display: block; width: 100%; height: 32px; padding: 0; border-radius: 6px; border: 1px solid; cursor: pointer;
    outline-offset: 1px;
  }
  button.on { outline: 2px solid var(--ink); }
  button:focus-visible { outline: 2px solid var(--ink); }
  .detail { min-height: 22px; margin-top: 12px; font-size: 14px; font-weight: 600; color: var(--ink); }
  .legend { display: flex; align-items: center; gap: 6px; margin-top: 12px; font-size: 12px; color: var(--ink-2); }
  .swatch { width: 18px; height: 12px; border-radius: 3px; border: 1px solid; }
</style>
