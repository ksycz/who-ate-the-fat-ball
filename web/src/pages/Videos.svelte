<script lang="ts">
  import { onMount, tick } from "svelte";
  import { getJSON, send, type Visit } from "../lib/api";
  import { dayOf, speciesLabel, sureChip, visitName, visitTime } from "../lib/format";
  import { canEdit, changes, noteChanged, serverDay, showSaveFailure, showToast } from "../lib/session";
  import FilterChips from "../components/FilterChips.svelte";
  import Picker from "../components/Picker.svelte";

  type Item = Visit & { video_url: string; video_clip_id: number };
  interface Feed {
    items: Item[];
    next_cursor: string | null;
    total: number;
    filters: { scientific: string; name: string | null }[];
  }

  const PAGE = 24;
  const ALL = "All birds";
  const SWIPE_PX = 50;
  const CONTROLS_PX = 48; // the native controls bar along the bottom of the video keeps its own drags

  let items = $state<Item[]>([]);
  let cursor = $state<string | null>(null);
  let total = $state(0);
  let filters = $state<Feed["filters"]>([]);
  let species = $state<string | null>(null);
  let index = $state(0);
  let loaded = $state(false);
  let failed = $state(false);
  let loadingMore = $state(false);
  let busy = $state(false);
  let pickerOpen = $state(false);
  let generation = 0; // bumped when the feed restarts, so a slow older response is dropped
  let touched = new Set<number>(); // visits changed here: fetched again after an undo
  let seenChanges = $changes;
  let start: { x: number; y: number } | null = null;
  let changeButton = $state<HTMLButtonElement | null>(null);

  const item = $derived(items[index] ?? null);
  const today = $derived($serverDay ?? (item ? dayOf(item.started_at) : ""));
  const chipLabels = $derived([ALL, ...filters.map((f) => speciesLabel(f))]);
  const chipValue = $derived(
    species === null ? ALL : speciesLabel(filters.find((f) => f.scientific === species) ?? { name: null, scientific: species }),
  );
  const atEnd = $derived(index >= items.length - 1 && cursor === null);

  async function fetchFeed(after: string | null, sp: string | null): Promise<Feed> {
    const q = new URLSearchParams({ limit: String(PAGE) });
    if (after !== null) q.set("cursor", after);
    if (sp !== null) q.set("species", sp);
    return getJSON<Feed>(`/api/videos?${q}`);
  }

  async function restart(sp: string | null) {
    const mine = ++generation;
    species = sp;
    index = 0;
    items = [];
    cursor = null;
    loaded = false;
    failed = false;
    try {
      const feed = await fetchFeed(null, sp);
      if (mine !== generation) return;
      items = feed.items;
      cursor = feed.next_cursor;
      total = feed.total;
      filters = feed.filters;
      loaded = true;
    } catch {
      if (mine === generation) failed = true;
    }
  }

  onMount(() => {
    restart(null);
  });

  function chooseChip(label: string) {
    const f = filters.find((x) => speciesLabel(x) === label);
    const next = f ? f.scientific : null;
    if (next !== species) restart(next);
  }

  async function next() {
    if (index < items.length - 1) {
      index++;
    } else if (cursor !== null && !loadingMore) {
      loadingMore = true;
      const mine = generation;
      try {
        const feed = await fetchFeed(cursor, species);
        if (mine !== generation) return;
        items = [...items, ...feed.items];
        cursor = feed.next_cursor;
        total = feed.total;
        if (index < items.length - 1) index++;
      } catch {
        if (mine === generation) showToast("Couldn't load more videos. Try again in a moment.");
      } finally {
        loadingMore = false;
      }
    }
  }

  function previous() {
    if (index > 0) index--;
  }

  // Swipe left or up for the next clip, right or down for the previous one.
  function onDown(e: PointerEvent) {
    start = null;
    const target = e.target as Element | null;
    if (target?.closest("button, a, input, [role=dialog]")) return;
    if (target instanceof HTMLVideoElement && e.clientY > target.getBoundingClientRect().bottom - CONTROLS_PX) return;
    start = { x: e.clientX, y: e.clientY };
  }
  function onUp(e: PointerEvent) {
    if (!start) return;
    const dx = e.clientX - start.x;
    const dy = e.clientY - start.y;
    start = null;
    const d = Math.abs(dx) >= Math.abs(dy) ? dx : dy;
    if (Math.abs(d) <= SWIPE_PX) return;
    if (d < 0) next();
    else previous();
  }

  function onKey(e: KeyboardEvent) {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    if (pickerOpen || e.altKey || e.ctrlKey || e.metaKey || e.shiftKey) return;
    const t = e.target;
    if (t instanceof Element && t.closest("input, textarea, select, [contenteditable], [role=dialog]")) return;
    e.preventDefault();
    if (e.key === "ArrowRight") next();
    else previous();
  }

  // A visit changed here (the picker, or an Undo from the toast): fetch those visits again, keeping each in place.
  async function refresh() {
    const ids = [...touched];
    await Promise.all(
      ids.map(async (id) => {
        try {
          const fresh = await getJSON<Visit>(`/api/visits/${id}`);
          items = items.map((it) => (it.id === id ? { ...it, ...fresh } : it));
        } catch {
          // the old name stays until the next change
        }
      }),
    );
  }
  $effect(() => {
    if ($changes !== seenChanges) {
      seenChanges = $changes;
      refresh();
    }
  });

  async function closePicker() {
    pickerOpen = false;
    await tick();
    changeButton?.focus();
  }

  async function toggleFavourite() {
    if (!item || busy) return;
    busy = true;
    const id = item.id;
    const want = !item.is_favourite;
    try {
      const { undo_token } = await send<{ undo_token: string }>("PATCH", `/api/visits/${id}`, { is_favourite: want });
      items = items.map((it) => (it.id === id ? { ...it, is_favourite: want } : it));
      touched.add(id);
      showToast(want ? "Added to Favourites" : "Removed from Favourites", undo_token);
      noteChanged();
    } catch (e) {
      showSaveFailure(e);
    } finally {
      busy = false;
    }
  }

  // What the bottom bar says next to the time: the guess, or who changed it.
  const note = $derived.by(() => {
    if (!item) return null;
    if (item.category !== "birds") return "moved by you";
    if (item.corrected) return "corrected by you";
    return item.species ? sureChip(item.confidence) : null;
  });
  const name = $derived(item ? visitName(item) : "");
</script>

<svelte:window onkeydown={onKey} />

<div class="page">
  {#if failed}
    <div class="message">
      <p>Couldn't load the videos. Check the Wi-Fi and try again.</p>
      <button type="button" class="again" onclick={() => restart(species)}>Try again</button>
    </div>
  {:else}
    <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
    <section class="feed" aria-label="Videos feed" onpointerdown={onDown} onpointerup={onUp} onpointercancel={() => (start = null)}>
      {#if item}
        <!-- svelte-ignore a11y_media_has_caption -->
        <video src={item.video_url} poster={item.poster_url ?? item.best_frame_url ?? undefined} playsinline muted autoplay controls preload="metadata"></video>
      {:else if loaded}
        <p class="empty">{species === null ? "No bird videos yet. They will show up here as the feeder gets visitors." : "No videos of this bird yet."}</p>
      {/if}

      <header>
        <div class="title-row">
          <h1>Videos</h1>
          {#if item}<span class="position">{index + 1} of {total}</span>{/if}
        </div>
        {#if filters.length > 0}
          <FilterChips tone="dark" options={chipLabels} value={chipValue} onchange={chooseChip} />
        {/if}
      </header>

      {#if item}
        <div class="rail">
          {#if $canEdit}
            <button type="button" class="rail-btn" aria-pressed={item.is_favourite} disabled={busy} onclick={toggleFavourite}>
              <span class="disc">
                <svg width="26" height="26" viewBox="0 0 24 24" fill={item.is_favourite ? "var(--robin)" : "none"} stroke="#fff" stroke-width="2" stroke-linejoin="round" aria-hidden="true"><path d="M12 3l2.8 5.7 6.2.9-4.5 4.4 1 6.2L12 17.3 6.5 20.2l1-6.2L3 9.6l6.2-.9z"></path></svg>
              </span>
              {item.is_favourite ? "Saved" : "Favourite"}
            </button>
            <button type="button" class="rail-btn" aria-haspopup="dialog" bind:this={changeButton} onclick={() => (pickerOpen = true)}>
              <span class="disc">
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 20h4L19 9l-4-4L4 16z"></path></svg>
              </span>
              What is it?
            </button>
          {/if}
          <a class="rail-btn" href={item.video_url} download>
            <span class="disc">
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 4v11M7 10l5 5 5-5M5 20h14"></path></svg>
            </span>
            Download
          </a>
        </div>

        <div class="bar">
          <div class="who">
            <div class="name">{name}</div>
            <div class="when">
              {visitTime(item.started_at, item.ended_at, today)}
              {#if note}<span class="note" class:mine={item.corrected || item.category !== "birds"}>{note}</span>{/if}
            </div>
          </div>
          <div class="buttons">
            <button type="button" class="prev" disabled={index === 0} onclick={previous}>Previous</button>
            <button type="button" class="next" disabled={atEnd || loadingMore} onclick={next}>Next clip</button>
          </div>
        </div>
      {/if}
    </section>
  {/if}
</div>

{#if pickerOpen && item}
  <Picker visit={item} onclose={closePicker} onchanged={(v) => touched.add(v.id)} />
{/if}

<style>
  .page { background: var(--ink); color: #fff; height: calc(100dvh - var(--nav-phone-h)); min-height: 480px; display: flex; flex-direction: column; }
  .feed {
    position: relative; flex: 1; min-height: 0; overflow: hidden; touch-action: none; user-select: none;
    background: #000; width: 100%; margin: 0 auto;
  }
  video { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: contain; background: #000; }
  header {
    position: absolute; left: 0; right: 0; top: 0; padding: 16px 16px 12px; display: flex; flex-direction: column; gap: 10px;
    background: rgba(46, 33, 22, 0.6);
  }
  .title-row { display: flex; align-items: center; justify-content: space-between; }
  h1 { margin: 0; font-weight: 800; font-size: 22px; }
  .position { font-size: 13px; color: var(--sand); }
  .rail { position: absolute; right: 12px; bottom: 196px; display: flex; flex-direction: column; gap: 14px; align-items: center; }
  .rail-btn {
    display: flex; flex-direction: column; align-items: center; gap: 4px; border: none; background: none; color: #fff;
    font: inherit; font-size: 12px; font-weight: 600; cursor: pointer; min-width: 52px; min-height: 52px;
  }
  .rail-btn:disabled { opacity: 0.6; }
  .disc { display: flex; align-items: center; justify-content: center; width: 52px; height: 52px; border-radius: 50%; background: rgba(46, 33, 22, 0.55); }
  .rail a.rail-btn { color: #fff; }
  .bar {
    position: absolute; left: 0; right: 0; bottom: 0; padding: 14px 16px 16px; display: flex; flex-direction: column; gap: 10px;
    background: rgba(46, 33, 22, 0.72); pointer-events: none;
  }
  .bar > * { pointer-events: auto; }
  .name { font-weight: 800; font-size: 24px; }
  .when { display: flex; align-items: center; gap: 8px; font-size: 14px; color: var(--sand); flex-wrap: wrap; }
  .note { font-size: 12px; font-weight: 600; color: var(--chip-ink); background: var(--chip); border-radius: 999px; padding: 5px 9px; }
  .note.mine { color: var(--robin-dark); background: var(--robin-tint); }
  .buttons { display: flex; gap: 10px; }
  .buttons button { flex: 1; min-height: 48px; border-radius: 12px; font: inherit; font-size: 15px; font-weight: 600; cursor: pointer; color: #fff; }
  .prev { border: 1px solid rgba(255, 255, 255, 0.45); background: transparent; }
  .next { border: none; background: var(--robin); }
  .buttons button:disabled { opacity: 0.4; cursor: default; }
  .empty, .message { margin: 0; padding: 120px 24px 24px; text-align: center; font-size: 17px; font-weight: 600; }
  .message { display: flex; flex-direction: column; align-items: center; gap: 12px; }
  .message p { margin: 0; }
  .again {
    min-height: 44px; padding: 0 16px; border-radius: 10px; border: 1px solid rgba(255, 255, 255, 0.45);
    background: transparent; color: #fff; font: inherit; font-size: 14px; font-weight: 600; cursor: pointer;
  }
  @media (min-width: 768px) {
    .page { height: calc(100vh - 68px); border-radius: 22px; overflow: hidden; }
    .feed { max-width: 960px; }
  }
</style>
