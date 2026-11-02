<script lang="ts">
  import { tick } from "svelte";
  import { ApiError, getJSON, send, type Category, type Clip, type Visit } from "../lib/api";
  import { route, back } from "../lib/router";
  import { canEdit, noteServerDay, serverDay, showToast } from "../lib/session";
  import { speciesLabel, sureChip, timeOfDay, visitName, visitTime } from "../lib/format";
  import { link } from "../lib/link";
  import Chip from "../components/Chip.svelte";

  interface Guess {
    scientific: string;
    name: string | null;
    confidence: number;
  }
  type Detail = Visit & { clips: Clip[]; guesses: Guess[] };

  const CATEGORY_NAMES: Record<Category, string> = {
    birds: "Birds",
    other_animals: "Other animals",
    other: "Other",
  };

  let visit = $state<Detail | null>(null);
  let missing = $state(false);
  let failed = $state(false);
  let index = $state(0);
  let menuOpen = $state(false);
  let busy = $state(false);
  let pickerOpen = $state(false); // Task 7 hooks the picker in here
  let watchedSent = false;
  let player = $state<HTMLVideoElement | null>(null);
  let menuEl = $state<HTMLElement | null>(null);
  let dlButton = $state<HTMLButtonElement | null>(null);

  const id = $derived($route.params.id);

  $effect(() => {
    const current = id;
    visit = null;
    missing = false;
    failed = false;
    index = 0;
    menuOpen = false;
    watchedSent = false;
    getJSON<Detail>(`/api/visits/${current}`)
      .then((v) => {
        if (current === id) visit = v;
      })
      .catch((e) => {
        if (current !== id) return;
        if (e instanceof ApiError && e.status === 404) missing = true;
        else failed = true;
      });
  });

  const clip = $derived(visit?.clips[index] ?? null);
  const today = $derived($serverDay ?? "");

  $effect(() => {
    if ($serverDay === null) {
      getJSON<{ day: string }>("/api/status")
        .then((s) => noteServerDay(s.day))
        .catch(() => {
          // show times without a day prefix until it is known
        });
    }
  });
  const alternatives = $derived(visit?.guesses.slice(1, 3) ?? []);

  const percent = (g: Guess) => (sureChip(g.confidence) ?? "").replace(/ sure$/, "");
  const guessLabel = (g: Guess) => `${speciesLabel(g)} · ${percent(g)}`;

  async function play(next: number) {
    index = next;
    await tick();
    if (player) {
      try {
        await player.play();
      } catch {
        // the browser may refuse autoplay; the controls are still there
      }
    }
  }

  function onEnded() {
    if (visit && index + 1 < visit.clips.length) play(index + 1);
  }

  function onPlay() {
    if (watchedSent) return;
    watchedSent = true;
    send("POST", `/api/visits/${id}/watched`).catch(() => {
      // best effort
    });
  }

  async function reload(): Promise<Detail | null> {
    try {
      const fresh = await getJSON<Detail>(`/api/visits/${id}`);
      visit = fresh;
      return fresh;
    } catch {
      return null;
    }
  }

  async function pick(g: Guess) {
    if (!visit || busy) return;
    busy = true;
    const before = visit.category;
    try {
      const { undo_token } = await send<{ undo_token: string }>("PATCH", `/api/visits/${id}`, {
        species: g.scientific,
      });
      const fresh = await reload();
      const text =
        fresh && fresh.category !== before
          ? `Moved to ${CATEGORY_NAMES[fresh.category]}`
          : `Changed to ${speciesLabel(g)}`;
      showToast(text, undo_token);
    } catch {
      showToast("Couldn't save that. Try again.");
    } finally {
      busy = false;
    }
  }

  async function toggleFavourite() {
    if (!visit || busy) return;
    busy = true;
    const want = !visit.is_favourite;
    try {
      const { undo_token } = await send<{ undo_token: string }>("PATCH", `/api/visits/${id}`, {
        is_favourite: want,
      });
      visit = { ...visit, is_favourite: want };
      showToast(want ? "Added to Favourites" : "Removed from Favourites", undo_token);
    } catch {
      showToast("Couldn't save that. Try again.");
    } finally {
      busy = false;
    }
  }

  function onKey(e: KeyboardEvent) {
    if (e.key === "Escape" && menuOpen) {
      menuOpen = false;
      dlButton?.focus();
    }
  }
  function onOutside(e: MouseEvent) {
    if (menuOpen && menuEl && !menuEl.contains(e.target as Node)) menuOpen = false;
  }
</script>

<svelte:window onkeydown={onKey} onclick={onOutside} />

<div class="visit">
  <header>
    <button type="button" class="back" aria-label="Back" onclick={() => back("/")}>
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M15 6l-6 6 6 6"></path></svg>
    </button>
  </header>

  {#if missing}
    <div class="message">
      <p>This visit doesn't exist any more</p>
      <a class="go" href="/" use:link>Go to Today</a>
    </div>
  {:else if failed}
    <div class="message"><p>Couldn't load this visit. Try again in a moment.</p></div>
  {:else if visit}
    <div class="player">
      {#if clip?.web_url && clip.kind === "photo"}
        <img src={clip.web_url} alt="" />
      {:else if clip?.web_url}
        <!-- svelte-ignore a11y_media_has_caption -->
        <video
          bind:this={player}
          src={clip.web_url}
          poster={clip.poster_url ?? visit.poster_url ?? undefined}
          controls
          playsinline
          preload="metadata"
          onplay={onPlay}
          onended={onEnded}
        ></video>
      {:else}
        <div class="not-ready">Video not ready yet</div>
      {/if}
    </div>

    <div class="head">
      <div class="title-row">
        <h1>{visitName(visit)}</h1>
        {#if visit.corrected}
          <span class="corrected">Corrected by you</span>
        {/if}
      </div>
      <div class="meta-row">
        <div class="meta">
          {#if $serverDay !== null}{visitTime(visit.started_at, visit.ended_at, today)}{/if}
          {#if !visit.corrected && sureChip(visit.confidence)}
            <Chip text={sureChip(visit.confidence) ?? ""} />
          {/if}
        </div>
        {#if $canEdit}
          <button type="button" class="change" onclick={() => (pickerOpen = !pickerOpen)} aria-expanded={pickerOpen}>
            Not right? Change
          </button>
        {/if}
      </div>
      {#if alternatives.length > 0}
        <div class="maybe">
          <span>Or maybe</span>
          {#each alternatives as g (g.scientific)}
            {#if $canEdit}
              <button type="button" class="guess" disabled={busy} onclick={() => pick(g)}>{guessLabel(g)}</button>
            {:else}
              <span class="guess-text">{guessLabel(g)}</span>
            {/if}
          {/each}
        </div>
      {/if}
    </div>

    <div class="actions" class:single={!$canEdit}>
      {#if $canEdit}
        <button type="button" class="action" aria-pressed={visit.is_favourite} disabled={busy} onclick={toggleFavourite}>
          <svg width="18" height="18" viewBox="0 0 24 24" fill={visit.is_favourite ? "var(--robin)" : "none"} stroke="var(--robin)" stroke-width="2" stroke-linejoin="round" aria-hidden="true"><path d="M12 3l2.8 5.7 6.2.9-4.5 4.4 1 6.2L12 17.3 6.5 20.2l1-6.2L3 9.6l6.2-.9z"></path></svg>
          {visit.is_favourite ? "Favourite ✓" : "Favourite"}
        </button>
      {/if}
      <div class="dl" bind:this={menuEl}>
        <button type="button" class="action" bind:this={dlButton} aria-expanded={menuOpen} onclick={() => (menuOpen = !menuOpen)}>
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 4v11M7 10l5 5 5-5M5 20h14"></path></svg>
          Download ▾
        </button>
        {#if menuOpen}
          <div class="menu">
            {#if clip?.web_url}
              <a href={clip.web_url} download onclick={() => (menuOpen = false)}>Video (.mp4)</a>
            {/if}
            {#if visit.best_frame_url}
              <a href={visit.best_frame_url} download onclick={() => (menuOpen = false)}>Photo (.jpg)</a>
            {/if}
          </div>
        {/if}
      </div>
    </div>

    {#if visit.clips.length > 0}
      <section class="clips">
        <h2>{visit.clips.length} {visit.clips.length === 1 ? "clip" : "clips"} in this visit</h2>
        <div class="grid">
          {#each visit.clips as c, i (c.id)}
            <button
              type="button"
              class="clip"
              class:on={i === index}
              aria-current={i === index ? "true" : undefined}
              aria-label={`Clip ${i + 1}, ${timeOfDay(c.begin_at)}${i === index ? ", playing" : ""}`}
              onclick={() => play(i)}
            >
              <span class="thumb">
                {#if c.poster_url}<img src={c.poster_url} alt="" loading="lazy" />{/if}
              </span>
              <span class="label" aria-hidden="true">{timeOfDay(c.begin_at)}{i === index ? " · playing" : ""}</span>
            </button>
          {/each}
        </div>
      </section>
    {/if}
  {/if}
</div>

<style>
  .visit { display: flex; flex-direction: column; gap: 16px; padding-bottom: 20px; }
  header { padding: 14px 0 0; }
  .back {
    display: flex; align-items: center; justify-content: center; width: 44px; height: 44px; border-radius: 50%;
    border: none; background: #fff; color: var(--ink); cursor: pointer;
  }
  .player { border-radius: 18px; overflow: hidden; background: var(--sand); }
  video, .player img { display: block; width: 100%; max-height: 420px; background: var(--ink); object-fit: contain; }
  .not-ready {
    display: flex; align-items: center; justify-content: center; min-height: 200px; padding: 20px;
    font-size: 15px; color: var(--ink-2); text-align: center;
  }
  .head { display: flex; flex-direction: column; gap: 6px; }
  .title-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
  h1 { margin: 0; font-weight: 800; font-size: 28px; letter-spacing: -0.5px; }
  .corrected {
    font-size: 12px; font-weight: 600; color: var(--robin-dark); background: var(--robin-tint);
    border-radius: 999px; padding: 5px 9px;
  }
  .meta-row { display: flex; align-items: center; justify-content: space-between; gap: 10px; flex-wrap: wrap; }
  .meta { display: flex; align-items: center; gap: 8px; font-size: 14px; color: var(--ink-2); }
  .change {
    min-height: 44px; padding: 0 12px; border-radius: 10px; border: 1px solid var(--line-strong);
    background: #fff; color: var(--robin-dark); font: inherit; font-size: 14px; font-weight: 600; cursor: pointer;
  }
  .maybe { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; font-size: 13px; color: var(--ink-2); }
  .guess {
    min-height: 44px; padding: 0 12px; border-radius: 999px; border: 1px solid var(--line-strong);
    background: #fff; color: var(--ink); font: inherit; font-size: 13px; cursor: pointer;
  }
  .guess-text { font-size: 13px; color: var(--ink); }
  .actions { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
  .actions.single { grid-template-columns: minmax(0, 1fr); }
  .action {
    display: flex; align-items: center; justify-content: center; gap: 8px; width: 100%; box-sizing: border-box;
    min-height: 48px; font: inherit; font-size: 14px; font-weight: 600; border-radius: 12px;
    border: 1px solid var(--line-strong); background: #fff; color: var(--ink); cursor: pointer;
  }
  .action[aria-pressed="true"] { border-color: var(--robin); background: var(--robin-tint); color: var(--robin-dark); }
  .dl { position: relative; }
  .menu {
    position: absolute; z-index: 5; left: 0; right: 0; top: calc(100% + 6px); display: flex; flex-direction: column;
    border-radius: 12px; background: #fff; overflow: hidden; box-shadow: 0 6px 20px rgba(40, 30, 20, 0.12);
  }
  .menu a {
    display: flex; align-items: center; min-height: 48px; padding: 0 14px; font-size: 15px; color: var(--ink);
    border-bottom: 1px solid var(--line);
  }
  .menu a:last-child { border-bottom: none; }
  .clips { display: flex; flex-direction: column; gap: 10px; }
  h2 { margin: 0; font-size: 15px; font-weight: 600; }
  .grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; }
  .clip {
    display: flex; flex-direction: column; gap: 4px; padding: 0; min-height: 44px; border: none; background: none;
    font: inherit; cursor: pointer; text-align: left; color: var(--ink);
  }
  .thumb { display: block; height: 64px; border-radius: 10px; overflow: hidden; background: var(--sand); outline-offset: 2px; }
  .thumb img { display: block; width: 100%; height: 100%; object-fit: cover; }
  .clip.on .thumb { outline: 2px solid var(--robin); }
  .label { font-size: 12px; font-weight: 400; color: var(--ink-2); }
  .clip.on .label { font-weight: 600; color: var(--robin-dark); }
  .message { display: flex; flex-direction: column; align-items: center; gap: 12px; padding: 40px 20px; text-align: center; }
  .message p { margin: 0; font-size: 17px; font-weight: 600; }
  .go {
    display: flex; align-items: center; min-height: 44px; padding: 0 16px; border-radius: 10px;
    border: 1px solid var(--line-strong); background: #fff; font-size: 14px; font-weight: 600;
  }
</style>
