<script lang="ts">
  import { onMount, tick } from "svelte";
  import { getJSON, send, type Clip, type Today, type Visit } from "../lib/api";
  import { canEdit, changes, noteServerDay, showSaveFailure } from "../lib/session";
  import { loadTodayScroll, saveTodayScroll } from "../lib/listCache";
  import { arrival } from "../lib/router";
  import { plural, speciesLabel, timeOfDay, whenText } from "../lib/format";
  import { link } from "../lib/link";
  import Logo from "../components/Logo.svelte";
  import CameraStatus from "../components/CameraStatus.svelte";
  import NewSpeciesBanner from "../components/NewSpeciesBanner.svelte";
  import VisitCard from "../components/VisitCard.svelte";

  const REFRESH_MS = 30_000;

  let data = $state<Today | null>(null);
  let fetchedAt = $state(0);
  let retrying = $state(false);
  let unreachable = $state(false);
  let restoreY: number | null = null; // where Back left us; applied once, after the first render
  let lastY = 0;
  const onScroll = () => (lastY = window.scrollY);

  async function load() {
    try {
      data = await getJSON<Today>("/api/today");
      unreachable = false;
      fetchedAt = Date.now();
      noteServerDay(data.day);
      if (restoreY !== null) {
        const y = restoreY;
        restoreY = null;
        await tick();
        window.scrollTo(0, y);
      }
    } catch {
      // keep what is on screen; the next refresh tries again
      if (!data) unreachable = true;
    }
  }

  onMount(() => {
    window.addEventListener("scroll", onScroll, { passive: true });
    if (arrival.viaHistory) restoreY = loadTodayScroll();
    load();
    // A correction or an Undo changes what today shows.
    let firstChange = true;
    const stop = changes.subscribe(() => {
      if (firstChange) firstChange = false;
      else load();
    });
    const timer = setInterval(() => {
      if (document.visibilityState === "visible") load();
    }, REFRESH_MS);
    const onVisible = () => {
      if (document.visibilityState === "visible") load();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      stop();
      saveTodayScroll(lastY);
      window.removeEventListener("scroll", onScroll);
      clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  });

  const retryable = $derived(data?.failed.filter((f) => f.can_retry) ?? []);
  const isEmpty = $derived(!!data && data.visits.length === 0 && data.checking.length === 0);
  const problem = $derived(data?.camera.state === "problem");
  const problemText = $derived(
    data
      ? data.camera.last_seen_at
        ? `Camera not seen since ${whenText(data.camera.last_seen_at, data.day)}`
        : "Camera not seen yet"
      : "",
  );

  // A clip still being recognised, shaped like a visit so the same card can show it.
  function pendingVisit(clip: Clip): Visit {
    return {
      id: clip.id, started_at: clip.begin_at, ended_at: clip.end_at, category: "birds", species: null, subject: "",
      confidence: null, is_favourite: false, best_frame_url: null, clip_count: 1, duration_s: clip.duration_s,
      poster_url: clip.poster_url, preview_url: clip.preview_url, corrected: false, watched: false,
    };
  }

  function emptyText(d: Today): string {
    let text = "No visitors yet today.";
    if (d.last_visitor) {
      const who = d.last_visitor.name ? speciesLabel({ name: d.last_visitor.name, scientific: "" }) : "Unknown";
      const when = whenText(d.last_visitor.started_at, d.day);
      text += ` Last visitor: ${who}, ${when === timeOfDay(d.last_visitor.started_at) ? `today ${when}` : when}.`;
    }
    if (d.camera.last_seen_at) {
      const seen = whenText(d.camera.last_seen_at, d.day);
      text += ` The camera was last seen ${seen === timeOfDay(d.camera.last_seen_at) ? `at ${seen}` : seen}.`;
    }
    return text;
  }

  async function retryAll() {
    if (!data || retrying) return;
    retrying = true;
    const ids = retryable.map((f) => f.clip_id);
    try {
      for (const id of ids) await send("POST", `/api/retry/${id}`);
      data = { ...data, failed: data.failed.filter((f) => !ids.includes(f.clip_id)) };
    } catch (e) {
      showSaveFailure(e); // the row stays so it can be tried again
    } finally {
      retrying = false;
    }
    load();
  }
</script>

<div class="today">
  <header>
    <div class="brand"><Logo size={30} />Who Ate the Fat Ball?</div>
    {#if data}<span class="pill"><CameraStatus camera={data.camera} today={data.day} serverNow={data.now} {fetchedAt} short /></span>{/if}
  </header>

  {#if unreachable}
    <div class="empty">
      <div class="empty-text">Couldn't reach the app. Check the Wi-Fi and try again.</div>
      <button type="button" class="again" onclick={load}>Try again</button>
    </div>
  {/if}

  {#if data}
    {#if problem}
      <a class="notice" href="/status" use:link>
        <span class="dot"></span>
        <span class="notice-text">
          <span class="notice-head">{problemText}</span>
          <span class="notice-sub">It may need charging. Check App status.</span>
        </span>
      </a>
    {/if}

    {#if data.new_species}
      <NewSpeciesBanner species={data.new_species} />
    {/if}

    <div class="title">
      <h1>Today</h1>
      <div class="summary">
        {data.summary.visits === 0
          ? "No visits yet"
          : `${plural(data.summary.visits, "visit")} · ${data.summary.species} species`}
      </div>
    </div>

    {#if isEmpty}
      <div class="empty">
        <Logo size={56} />
        <div class="empty-head">Quiet so far</div>
        <div class="empty-text">{emptyText(data)}</div>
        <a class="yesterday" href="/birds" use:link>See yesterday’s visits</a>
      </div>
    {/if}

    {#if data.champion}
      <div class="champion">
        <span class="champ-photo">
          {#if data.champion.best_frame_url}
            <img src={data.champion.best_frame_url} alt="" />
          {:else}
            <span class="placeholder" data-placeholder></span>
          {/if}
        </span>
        <span class="champ-text">
          <span class="champ-head">Today's fat-ball champion</span>
          <span class="champ-name">{speciesLabel(data.champion)}</span>
          <span class="champ-sub">{plural(data.champion.count, "visit")} · first at {timeOfDay(data.champion.first_at)}</span>
        </span>
      </div>
    {/if}

    {#if data.checking.length > 0 || data.visits.length > 0}
    <div class="cards">
      {#each data.checking as clip (clip.id)}
        <VisitCard visit={pendingVisit(clip)} today={data.day} pending />
      {/each}

      {#each data.visits as visit (visit.id)}
        <VisitCard {visit} today={data.day} />
      {/each}
    </div>
    {/if}

    {#if $canEdit && retryable.length > 0}
      <div class="retry">
        <span>{plural(retryable.length, "clip")} couldn't be fetched</span>
        <button type="button" onclick={retryAll} disabled={retrying}>Retry</button>
      </div>
    {/if}
  {/if}
</div>

<style>
  .today { display: flex; flex-direction: column; gap: 14px; padding-bottom: 20px; }
  header { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 18px 0 0; }
  .brand { display: flex; align-items: center; gap: 8px; font-weight: 800; font-size: 16px; letter-spacing: -0.2px; }
  .pill { background: #fff; border-radius: 999px; padding: 6px 10px; }
  .notice {
    display: flex; align-items: center; gap: 12px; border-radius: 16px; padding: 12px 14px;
    background: #fff; border: 1.5px solid var(--robin); color: var(--ink);
  }
  .notice .dot { width: 10px; height: 10px; flex: none; border-radius: 50%; background: var(--robin); }
  .notice-text { flex: 1; display: flex; flex-direction: column; gap: 2px; }
  .notice-head { font-size: 15px; font-weight: 600; }
  .notice-sub { font-size: 13px; color: var(--ink-2); }
  .title { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; }
  h1 { margin: 0; font-weight: 800; font-size: 34px; letter-spacing: -0.8px; }
  .summary { font-size: 14px; color: var(--ink-2); }
  .empty {
    display: flex; flex-direction: column; align-items: center; gap: 10px; text-align: center;
    padding: 28px 20px; border-radius: 18px; background: #fff;
  }
  .empty-head { font-size: 18px; font-weight: 600; }
  .empty-text { font-size: 14px; color: var(--ink-2); max-width: 260px; }
  .yesterday {
    display: flex; align-items: center; min-height: 44px; padding: 0 16px; border-radius: 10px;
    border: 1px solid var(--line-strong); color: var(--robin-dark); font-size: 14px; font-weight: 600;
  }
  .champion { display: flex; align-items: center; gap: 14px; border-radius: 18px; padding: 12px; background: #fff; color: var(--ink); }
  .champ-photo { flex: none; width: 76px; height: 76px; border-radius: 14px; overflow: hidden; background: var(--sand); }
  .champ-text { flex: 1; display: flex; flex-direction: column; gap: 2px; }
  .champ-head { font-size: 12px; font-weight: 600; color: var(--robin-dark); }
  .champ-name { font-size: 20px; font-weight: 800; letter-spacing: -0.3px; }
  .champ-sub { font-size: 13px; color: var(--ink-2); }
  img, .placeholder { display: block; width: 100%; height: 100%; object-fit: cover; background: var(--sand); }
  .again {
    min-height: 44px; padding: 0 16px; border-radius: 10px; border: 1px solid var(--line-strong);
    background: #fff; color: var(--robin-dark); font: inherit; font-size: 14px; font-weight: 600; cursor: pointer;
  }
  .cards { display: flex; flex-direction: column; gap: 14px; }
  @media (min-width: 768px) {
    .brand { display: none; }
    .cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 16px; }
  }
  .retry {
    display: flex; align-items: center; justify-content: space-between; gap: 10px;
    font-size: 13px; color: var(--ink-2); padding: 0 4px;
  }
  .retry button {
    min-height: 44px; padding: 0 12px; border-radius: 10px; border: 1px solid var(--line-strong);
    background: #fff; color: var(--robin-dark); font: inherit; font-size: 13px; font-weight: 600; cursor: pointer;
  }
</style>
