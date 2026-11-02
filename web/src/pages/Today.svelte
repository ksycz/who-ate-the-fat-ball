<script lang="ts">
  import { onMount } from "svelte";
  import { getJSON, send, type Today } from "../lib/api";
  import { canEdit } from "../lib/session";
  import { clipBadge, speciesLabel, timeOfDay, visitTime, whenText } from "../lib/format";
  import { link } from "../lib/link";
  import Logo from "../components/Logo.svelte";
  import CameraStatus from "../components/CameraStatus.svelte";
  import NewSpeciesBanner from "../components/NewSpeciesBanner.svelte";
  import VisitCard from "../components/VisitCard.svelte";
  import Chip from "../components/Chip.svelte";

  const REFRESH_MS = 30_000;

  let data = $state<Today | null>(null);
  let now = $state(new Date());
  let retrying = $state(false);

  async function load() {
    try {
      data = await getJSON<Today>("/api/today");
      now = new Date();
    } catch {
      // keep what is on screen; the next refresh tries again
    }
  }

  onMount(() => {
    load();
    const timer = setInterval(() => {
      if (document.visibilityState === "visible") load();
    }, REFRESH_MS);
    const onVisible = () => {
      if (document.visibilityState === "visible") load();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  });

  const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

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
    } catch {
      // leave the row so it can be tried again
    } finally {
      retrying = false;
    }
    load();
  }
</script>

<div class="today">
  <header>
    <div class="brand"><Logo size={30} />Who Ate the Fat Ball?</div>
    {#if data}<span class="pill"><CameraStatus camera={data.camera} {now} short /></span>{/if}
  </header>

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
      <div class="banner-slot"><NewSpeciesBanner species={data.new_species} /></div>
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

    {#each data.checking as clip (clip.id)}
      <div class="card">
        <span class="photo">
          {#if clip.poster_url}
            <img src={clip.poster_url} alt="" loading="lazy" />
          {:else}
            <span class="placeholder" data-placeholder></span>
          {/if}
          <span class="badge">{clipBadge(clip.duration_s, 1)}</span>
        </span>
        <span class="info">
          <span class="who">
            <span class="name">Checking who it is…</span>
            <span class="time">{visitTime(clip.begin_at, clip.end_at, data.day)}</span>
          </span>
          <Chip text="Checking…" pending />
        </span>
      </div>
    {/each}

    {#each data.visits as visit (visit.id)}
      <VisitCard {visit} today={data.day} />
    {/each}

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
  .banner-slot { display: block; }
  .title { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; }
  h1 { margin: 0; font-weight: 800; font-size: 34px; letter-spacing: -0.8px; }
  .summary { font-size: 14px; color: var(--ink-2); }
  .empty {
    display: flex; flex-direction: column; align-items: center; gap: 10px; text-align: center;
    padding: 28px 20px; border-radius: 18px; background: #fff;
  }
  .empty-head { font-size: 18px; font-weight: 600; }
  .empty-text { font-size: 14px; color: var(--ink-2); max-width: 260px; }
  .champion { display: flex; align-items: center; gap: 14px; border-radius: 18px; padding: 12px; background: #fff; color: var(--ink); }
  .champ-photo { flex: none; width: 76px; height: 76px; border-radius: 14px; overflow: hidden; background: var(--sand); }
  .champ-text { flex: 1; display: flex; flex-direction: column; gap: 2px; }
  .champ-head { font-size: 12px; font-weight: 600; color: var(--robin-dark); }
  .champ-name { font-size: 20px; font-weight: 800; letter-spacing: -0.3px; }
  .champ-sub { font-size: 13px; color: var(--ink-2); }
  img, .placeholder { display: block; width: 100%; height: 100%; object-fit: cover; background: var(--sand); }
  .card { display: flex; flex-direction: column; background: #fff; border-radius: 18px; overflow: hidden; color: var(--ink); }
  .photo { position: relative; display: block; height: 170px; background: var(--sand); }
  .badge {
    position: absolute; left: 12px; bottom: 12px; font-size: 12px; font-weight: 600; border-radius: 999px;
    padding: 5px 10px; background: rgba(46, 33, 22, 0.78); color: #fff;
  }
  .info { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 12px 14px 14px; }
  .who { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
  .name { font-size: 17px; font-weight: 600; }
  .time { font-size: 13px; color: var(--ink-2); }
  .retry {
    display: flex; align-items: center; justify-content: space-between; gap: 10px;
    font-size: 13px; color: var(--ink-2); padding: 0 4px;
  }
  .retry button {
    min-height: 44px; padding: 0 12px; border-radius: 10px; border: 1px solid var(--line-strong);
    background: #fff; color: var(--robin-dark); font: inherit; font-size: 13px; font-weight: 600; cursor: pointer;
  }
  /* On the side layout the New species banner moves to the top of Birds (spec section 8). */
  @media (min-width: 768px) {
    .banner-slot { display: none; }
  }
</style>
