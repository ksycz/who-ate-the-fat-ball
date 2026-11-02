<script lang="ts">
  import { onMount } from "svelte";
  import { getJSON, type Status } from "../lib/api";
  import { navigate } from "../lib/router";
  import { canEdit, noteServerDay, serverDay } from "../lib/session";
  import { cameraStatus } from "../lib/format";
  import { link } from "../lib/link";
  import SortedInto from "../components/SortedInto.svelte";

  let status = $state<Status | null>(null);
  const now = new Date();
  const cam = $derived(status ? cameraStatus(status.camera, now, $serverDay ?? status.day) : null);
  const waiting = $derived(status ? status.queue.downloaded + status.queue.processing + status.recognition.pending : 0);

  onMount(() => {
    // The side menu already lists all of this, so More is a phone-only page.
    if (window.matchMedia("(min-width: 768px)").matches) {
      navigate("/", { replace: true });
      return;
    }
    getJSON<Status>("/api/status").then(
      (s) => {
        status = s;
        noteServerDay(s.day);
      },
      () => {},
    );
  });
</script>

<h1>More</h1>
<div class="list">
  <a class="row" href="/favourites" use:link>
    <span class="lead">
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linejoin="round" aria-hidden="true"><path d="M12 3l2.8 5.7 6.2.9-4.5 4.4 1 6.2L12 17.3 6.5 20.2l1-6.2L3 9.6l6.2-.9z"></path></svg>
      Favourites
    </span>
    {#if status}<span class="count">{status.sorted.favourites}</span>{/if}
  </a>

  <SortedInto sorted={status?.sorted} big />

  <a class="row tall" href="/status" use:link>
    <span class="lead">
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 8h3l2-3h6l2 3h3v11H4z"></path><circle cx="12" cy="13" r="3.5"></circle></svg>
      <span class="stack">
        <span>App status</span>
        {#if cam}<span class="sub"><span class="dot {cam.dot}"></span>{cam.text} · {waiting} clips waiting</span>{/if}
      </span>
    </span>
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M9 6l6 6-6 6"></path></svg>
  </a>

  {#if !$canEdit}
    <a class="row" href="/unlock" use:link>Unlock editing</a>
  {/if}
</div>

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
