<script lang="ts">
  import { onMount } from "svelte";
  import { getJSON, send, type Category, type Species, type Visit } from "../lib/api";
  import { correctionText, speciesLabel } from "../lib/format";
  import { link } from "../lib/link";
  import { canEdit, noteChanged, saveFailure, showToast } from "../lib/session";

  let { visit, onclose, onchanged }: { visit: Visit; onclose: () => void; onchanged: (visit: Visit) => void } = $props();

  interface Other {
    label: string;
    hint: string;
    dot: string;
    body: Record<string, unknown>;
    category: Category;
  }
  const OTHERS: Other[] = [
    { label: "Other animal", hint: "Squirrel, cat…", dot: "var(--dot-animals)", body: { category: "other_animals" }, category: "other_animals" },
    { label: "Dog", hint: "Moves to Other", dot: "var(--dot-other)", body: { species: "Canis lupus familiaris" }, category: "other" },
    { label: "Nothing", hint: "Empty clip", dot: "var(--dot-other)", body: { species: null, category: "other" }, category: "other" },
  ];

  let catalog = $state<Species[]>([]);
  let loadFailed = $state(false);
  let query = $state("");
  let busy = $state(false);
  let error = $state<{ text: string; locked: boolean } | null>(null);
  let dialog = $state<HTMLElement | null>(null);
  let closeButton = $state<HTMLButtonElement | null>(null);

  const birds = $derived(catalog.filter((s) => s.group === "bird"));
  const seen = $derived(birds.filter((s) => s.visits > 0 || s.scientific === visit.species?.scientific));
  const q = $derived(query.trim().toLowerCase());
  const matches = $derived(
    q === "" ? [] : birds.filter((s) => (s.name ?? "").toLowerCase().includes(q) || s.scientific.toLowerCase().includes(q)),
  );
  const shown = $derived(q === "" ? seen : matches);

  onMount(() => {
    closeButton?.focus();
    getJSON<Species[]>("/api/species")
      .then((list) => (catalog = list))
      .catch(() => (loadFailed = true));
  });

  async function choose(body: Record<string, unknown>, category: Category, label: string) {
    if (busy) return;
    busy = true;
    error = null;
    try {
      const { undo_token } = await send<{ undo_token: string }>("PATCH", `/api/visits/${visit.id}`, body);
      showToast(correctionText(visit.category, category, label), undo_token);
      noteChanged();
      onchanged(visit);
      onclose();
    } catch (e) {
      error = saveFailure(e);
      if (error.locked) canEdit.set(false); // the Mac says this device may not edit, so stop offering it
    } finally {
      busy = false;
    }
  }

  function chooseBird(s: Species) {
    return choose({ species: s.scientific }, "birds", speciesLabel(s));
  }

  function onKey(e: KeyboardEvent) {
    if (e.key === "Escape") {
      e.stopPropagation();
      onclose();
      return;
    }
    if (e.key !== "Tab" || !dialog) return;
    const items = [...dialog.querySelectorAll<HTMLElement>("button:not([disabled]), input, a[href]")];
    if (items.length === 0) return;
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

<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
<div class="backdrop" onclick={(e) => e.target === e.currentTarget && onclose()}>
  <div class="sheet" role="dialog" aria-modal="true" aria-labelledby="pick-h" tabindex="-1" bind:this={dialog} onkeydown={onKey}>
    <div class="top">
      <h2 id="pick-h">What is it?</h2>
      <button type="button" class="close" aria-label="Close" bind:this={closeButton} onclick={onclose}>
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"></path></svg>
      </button>
    </div>

    {#if error}
      <p class="error" role="alert">
        {error.text}{#if error.locked}{" · "}<a href="/unlock" use:link>Unlock</a>{/if}
      </p>
    {/if}

    <label for="birdsearch">Search all birds</label>
    <input id="birdsearch" type="search" placeholder="e.g. coal tit" autocomplete="off" bind:value={query} />

    <div class="heading">{q === "" ? "Birds seen at your feeder" : "Matching birds"}</div>
    {#if loadFailed}
      <p class="note">Couldn't load the bird list. The buttons below still work.</p>
    {:else if q !== "" && shown.length === 0}
      <p class="note">No bird called "{query.trim()}". Try a shorter name.</p>
    {/if}
    {#each shown as s (s.scientific)}
      {@const on = s.scientific === visit.species?.scientific}
      <button type="button" class="bird" class:on aria-pressed={on} disabled={busy} onclick={() => chooseBird(s)}>
        <span>{speciesLabel(s)}{#if on}<span class="tick" aria-hidden="true"> ✓</span>{/if}</span>
        <span class="latin">{s.scientific}</span>
      </button>
    {/each}

    <div class="heading other-h">Not a bird?</div>
    <div class="others">
      {#each OTHERS as o (o.label)}
        <button type="button" class="other" disabled={busy} onclick={() => choose(o.body, o.category, o.label)}>
          <span class="label"><span class="dot" style:background={o.dot}></span>{o.label}</span>
          <span class="hint">{o.hint}</span>
        </button>
      {/each}
    </div>
  </div>
</div>

<style>
  .backdrop {
    position: fixed; inset: 0; z-index: 10; display: flex; flex-direction: column; justify-content: flex-end;
    background: rgba(46, 33, 22, 0.45);
  }
  .sheet {
    box-sizing: border-box; max-height: 86%; overflow-y: auto; background: #fff; color: var(--ink);
    border-radius: 22px 22px 0 0; padding: 20px 20px 28px; display: flex; flex-direction: column; gap: 10px;
  }
  .top { display: flex; align-items: center; justify-content: space-between; }
  h2 { margin: 0; font-weight: 800; font-size: 22px; }
  .close {
    width: 44px; height: 44px; border: none; border-radius: 50%; background: var(--sand); color: var(--ink);
    cursor: pointer; display: flex; align-items: center; justify-content: center;
  }
  label { font-size: 13px; color: var(--ink-2); }
  input {
    font: inherit; font-size: 15px; min-height: 48px; box-sizing: border-box; padding: 0 14px; border-radius: 12px;
    border: 1px solid var(--field); color: var(--ink); background: #fff;
  }
  .heading { font-size: 12px; font-weight: 600; color: var(--ink-2); margin-top: 4px; }
  .other-h { margin-top: 6px; }
  .note { margin: 0; font-size: 14px; color: var(--ink-2); }
  .error {
    margin: 0; padding: 10px 12px; border-radius: 12px; background: var(--robin-tint); color: var(--robin-dark);
    font-size: 14px; font-weight: 600;
  }
  .error a { text-decoration: underline; }
  .bird {
    display: flex; align-items: center; justify-content: space-between; gap: 8px; min-height: 48px; padding: 0 14px;
    font: inherit; font-size: 15px; font-weight: 400; border-radius: 12px; border: 1px solid var(--line);
    background: #fff; color: var(--ink); cursor: pointer; text-align: left;
  }
  .bird.on { font-weight: 600; border: 2px solid var(--robin); background: var(--robin-tint); }
  .latin { font-size: 12px; color: var(--ink-2); font-style: italic; }
  .others { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; }
  .other {
    display: flex; flex-direction: column; align-items: flex-start; gap: 2px; min-height: 56px; padding: 8px 10px;
    font: inherit; border-radius: 12px; border: 1px solid var(--line); background: #fff; color: var(--ink);
    cursor: pointer; text-align: left;
  }
  .label { display: flex; align-items: center; gap: 6px; font-size: 14px; font-weight: 600; }
  .dot { width: 8px; height: 8px; border-radius: 50%; flex: none; }
  .hint { font-size: 11px; color: var(--ink-2); }
  @media (min-width: 768px) {
    .backdrop { align-items: center; justify-content: center; }
    .sheet { width: 480px; max-width: calc(100vw - 32px); max-height: 80vh; border-radius: 22px; }
  }
</style>
