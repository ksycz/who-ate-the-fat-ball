<script lang="ts">
  import { onMount } from "svelte";
  import { getJSON, type Status } from "../lib/api";
  import { route } from "../lib/router";
  import { canEdit, changes, noteServerDay } from "../lib/session";
  import { link } from "../lib/link";
  import Logo from "./Logo.svelte";
  import CameraStatus from "./CameraStatus.svelte";
  import Icon from "./Icon.svelte";
  import SortedInto from "./SortedInto.svelte";

  let status = $state<Status | null>(null);
  let fetchedAt = $state(0);

  async function load() {
    try {
      status = await getJSON<Status>("/api/status");
      noteServerDay(status.day);
      fetchedAt = Date.now();
    } catch {
      // the menu still works without counts
    }
  }
  onMount(() => {
    load();
    const timer = setInterval(() => {
      if (document.visibilityState === "visible") load();
    }, 30_000);
    // The counts follow corrections and undos.
    let first = true;
    const stop = changes.subscribe(() => {
      if (first) first = false;
      else load();
    });
    return () => {
      clearInterval(timer);
      stop();
    };
  });

  // The By species pages belong to Birds.
  const name = $derived($route.name === "birds-species" || $route.name === "species" ? "birds" : $route.name);
</script>

<nav aria-label="Main">
  <div class="brand"><Logo size={40} /><span>Who Ate the<br />Fat Ball?</span></div>

  <a class="item" href="/" use:link aria-current={name === "today" ? "page" : undefined} class:on={name === "today"}>
    <Icon name="Today" size={20} /><span class="label">Today</span>
  </a>
  <a class="item" href="/favourites" use:link aria-current={name === "favourites" ? "page" : undefined} class:on={name === "favourites"}>
    <Icon name="Star" size={20} />
    <span class="label">Favourites</span>
    {#if status}<span class="count">{status.sorted.favourites}</span>{/if}
  </a>

  <SortedInto sorted={status?.sorted} current={name} />

  <a class="item" href="/stats" use:link aria-current={name === "stats" ? "page" : undefined} class:on={name === "stats"}>
    <Icon name="Stats" size={20} /><span class="label">Stats</span>
  </a>
  <a class="item" href="/status" use:link aria-current={name === "status" ? "page" : undefined} class:on={name === "status"}>
    <Icon name="Camera" size={20} />
    <span class="label">App status</span>
  </a>
  {#if !$canEdit}
    <a class="item" href="/unlock" use:link aria-current={name === "unlock" ? "page" : undefined} class:on={name === "unlock"}>
      <span class="label">Unlock editing</span>
    </a>
  {/if}

  <div class="camera">
    {#if status}<CameraStatus camera={status.camera} today={status.day} serverNow={status.now} {fetchedAt} />{/if}
  </div>
</nav>

<style>
  nav {
    display: none;
    box-sizing: border-box;
    position: sticky;
    top: 0;
    height: 100vh;
    width: 260px;
    flex: none;
    padding: 24px 14px;
    flex-direction: column;
    gap: 4px;
    background: #fff;
    border-right: 1px solid var(--line);
    overflow-y: auto;
  }
  @media (min-width: 768px) {
    nav { display: flex; }
  }
  .brand { display: flex; align-items: center; gap: 10px; padding: 0 8px 20px; font-weight: 800; font-size: 17px; line-height: 1.15; }
  .item {
    display: flex; align-items: center; gap: 12px; min-height: 44px; padding: 0 10px; border-radius: 12px;
    font-size: 14px; font-weight: 500; color: var(--ink);
  }
  .item :global(svg) { color: var(--olive); flex: none; }
  .item.on { background: var(--robin-tint); font-weight: 600; color: var(--robin-dark); }
  .item.on :global(svg) { color: var(--robin-dark); }
  .label { flex: 1; }
  .count { font-size: 12px; color: var(--ink-2); }
  .camera { margin-top: auto; padding: 16px 10px 0; }
</style>
