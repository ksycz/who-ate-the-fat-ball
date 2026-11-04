<script lang="ts">
  import { onMount } from "svelte";
  import { getJSON, type Status } from "../lib/api";
  import { tick } from "../lib/clock";
  import { navigate } from "../lib/router";
  import { canEdit, changes, noteServerDay, serverDay } from "../lib/session";
  import { cameraStatus, plural } from "../lib/format";
  import { link } from "../lib/link";
  import Icon from "../components/Icon.svelte";
  import SortedInto from "../components/SortedInto.svelte";

  // The side menu already lists all of this, so More is a phone-only page. Decide before the first render
  // so the heading never flashes before the redirect.
  const wide = window.matchMedia("(min-width: 768px)").matches;

  let status = $state<Status | null>(null);
  let fetchedAt = $state(0);
  const cam = $derived(
    status ? cameraStatus(status.camera, $serverDay ?? status.day, { serverNow: status.now, fetchedAt, nowMs: $tick }) : null,
  );
  const waiting = $derived(status ? status.queue.downloaded + status.queue.processing + status.recognition.pending : 0);

  onMount(() => {
    if (wide) {
      navigate("/", { replace: true });
      return;
    }
    load();
    // The Sorted-into counts follow corrections and undos.
    let first = true;
    return changes.subscribe(() => {
      if (first) first = false;
      else load();
    });
  });

  function load() {
    getJSON<Status>("/api/status").then(
      (s) => {
        status = s;
        fetchedAt = Date.now();
        noteServerDay(s.day);
      },
      () => {},
    );
  }
</script>

{#if !wide}
<h1>More</h1>
<div class="list">
  <a class="row" href="/favourites" use:link>
    <span class="lead">
      <Icon name="Star" />
      Favourites
    </span>
    {#if status}<span class="count">{status.sorted.favourites}</span>{/if}
  </a>

  <SortedInto sorted={status?.sorted} big />

  <a class="row tall" href="/status" use:link>
    <span class="lead">
      <Icon name="Camera" />
      <span class="stack">
        <span>App status</span>
        {#if cam}<span class="sub"><span class="dot {cam.dot}"></span>{cam.text} · {plural(waiting, "clip")} waiting</span>{/if}
      </span>
    </span>
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M9 6l6 6-6 6"></path></svg>
  </a>

  {#if !$canEdit}
    <a class="row" href="/unlock" use:link>Unlock editing</a>
  {/if}
</div>
{/if}

<style>
  h1 { margin: 20px 0 16px; font-weight: 800; font-size: 34px; letter-spacing: -0.8px; }
  .list { display: flex; flex-direction: column; gap: 16px; }
  .row {
    display: flex; align-items: center; justify-content: space-between; min-height: 56px; padding: 0 16px;
    border-radius: 16px; background: #fff; color: var(--ink); font-size: 16px; font-weight: 600;
  }
  .row.tall { min-height: 64px; }
  .row :global(svg) { color: var(--olive); flex: none; }
  .lead { display: flex; align-items: center; gap: 12px; }
  .stack { display: flex; flex-direction: column; gap: 2px; }
  .sub { display: flex; align-items: center; gap: 6px; font-size: 12px; font-weight: 400; color: var(--ink-2); }
  .count { font-size: 13px; font-weight: 500; color: var(--ink-2); }
  .dot { width: 8px; height: 8px; border-radius: 50%; flex: none; }
  .ok { background: var(--ok); }
  .asleep { background: var(--dot-animals); }
  .problem { background: var(--robin); }
</style>
