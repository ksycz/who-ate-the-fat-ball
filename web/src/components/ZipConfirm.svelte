<script lang="ts">
  import { onMount } from "svelte";
  import { plural, sizeText } from "../lib/format";
  import { showToast } from "../lib/session";
  import { startDownload, type ZipPlan } from "../lib/zip";

  let { info, ondone }: { info: ZipPlan; ondone: () => void } = $props();

  const summary = $derived(`${plural(info.visits, "visit")} (${sizeText(info.size_bytes)})`);
  let dialog = $state<HTMLElement | null>(null);
  let downloadButton = $state<HTMLButtonElement | null>(null);

  onMount(() => {
    const opener = document.activeElement as HTMLElement | null;
    downloadButton?.focus();
    return () => opener?.focus?.(); // back to the button that opened this
  });

  function download() {
    startDownload(info.token, info.filename);
    showToast(`Downloading ${summary}…`);
    ondone();
  }

  function onKey(e: KeyboardEvent) {
    if (e.key !== "Tab" || !dialog) return;
    const items = [...dialog.querySelectorAll<HTMLElement>("button:not([disabled])")];
    const first = items[0];
    const last = items[items.length - 1];
    const active = document.activeElement;
    if (e.shiftKey && (active === first || !dialog.contains(active))) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && (active === last || !dialog.contains(active))) {
      e.preventDefault();
      first.focus();
    }
  }
</script>

<svelte:window onkeydown={(e) => e.key === "Escape" && ondone()} />

<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
<div class="backdrop" onclick={(e) => e.target === e.currentTarget && ondone()}>
  <div class="sheet" role="dialog" aria-modal="true" aria-labelledby="zip-h" tabindex="-1" bind:this={dialog} onkeydown={onKey}>
    <h2 id="zip-h">Download {summary}?</h2>
    <div class="buttons">
      <button type="button" class="cancel" onclick={ondone}>Cancel</button>
      <button type="button" class="go" bind:this={downloadButton} onclick={download}>Download</button>
    </div>
  </div>
</div>

<style>
  .backdrop {
    position: fixed; inset: 0; z-index: 10; display: flex; flex-direction: column; justify-content: flex-end;
    background: rgba(46, 33, 22, 0.45);
  }
  .sheet {
    box-sizing: border-box; background: #fff; color: var(--ink); border-radius: 22px 22px 0 0;
    padding: 22px 20px 28px; display: flex; flex-direction: column; gap: 18px;
  }
  h2 { margin: 0; font-weight: 800; font-size: 20px; }
  .buttons { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
  button { min-height: 48px; border-radius: 12px; font: inherit; font-size: 15px; font-weight: 600; cursor: pointer; }
  .cancel { border: 1px solid var(--line-strong); background: #fff; color: var(--ink); }
  .go { border: none; background: var(--robin); color: #fff; }
  @media (min-width: 768px) {
    .backdrop { align-items: center; justify-content: center; }
    .sheet { width: 400px; max-width: calc(100vw - 32px); border-radius: 22px; }
  }
</style>
