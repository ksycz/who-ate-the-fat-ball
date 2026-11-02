<script lang="ts">
  import { onMount } from "svelte";
  import { getJSON, type Status } from "../lib/api";
  import { route } from "../lib/router";
  import { canEdit } from "../lib/session";
  import { link } from "../lib/link";
  import Logo from "./Logo.svelte";
  import CameraStatus from "./CameraStatus.svelte";
  import Icon from "./Icon.svelte";

  let status = $state<Status | null>(null);
  let now = $state(new Date());

  async function load() {
    try {
      status = await getJSON<Status>("/api/status");
      now = new Date();
    } catch {
      // the menu still works without counts
    }
  }
  onMount(() => {
    load();
    const timer = setInterval(() => {
      if (document.visibilityState === "visible") load();
    }, 30_000);
    return () => clearInterval(timer);
  });

  const name = $derived($route.name);
  const sorted = $derived([
    { label: "Birds", href: "/birds", dot: "var(--robin)", count: status?.sorted.birds, names: ["birds"] },
    { label: "Other animals", href: "/other-animals", dot: "var(--dot-animals)", count: status?.sorted.other_animals, names: ["other-animals"] },
    { label: "Other", href: "/other", dot: "var(--dot-other)", count: status?.sorted.other, names: ["other"] },
  ]);
</script>

<nav aria-label="Main">
  <div class="brand"><Logo size={40} /><span>Who Ate the<br />Fat Ball?</span></div>

  <a class="item" href="/" use:link aria-current={name === "today" ? "page" : undefined} class:on={name === "today"}>
    <Icon name="Today" size={20} /><span class="label">Today</span>
  </a>
  <a class="item" href="/favourites" use:link aria-current={name === "favourites" ? "page" : undefined} class:on={name === "favourites"}>
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3l2.8 5.7 6.2.9-4.5 4.4 1 6.2L12 17.3 6.5 20.2l1-6.2L3 9.6l6.2-.9z"></path></svg>
    <span class="label">Favourites</span>
    {#if status}<span class="count">{status.sorted.favourites}</span>{/if}
  </a>

  <div class="sorted" role="group" aria-labelledby="sorted-h">
    <span id="sorted-h" class="sorted-head">Sorted into</span>
    {#each sorted as s (s.label)}
      {@const on = s.names.includes(name)}
      <a class="item" href={s.href} use:link aria-current={on ? "page" : undefined} class:on>
        <span class="swatch" style:background={s.dot}></span>
        <span class="label">{s.label}</span>
        {#if s.count !== undefined}<span class="count">{s.count}</span>{/if}
      </a>
    {/each}
  </div>

  <a class="item" href="/status" use:link aria-current={name === "status" ? "page" : undefined} class:on={name === "status"}>
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 8h3l2-3h6l2 3h3v11H4z"></path><circle cx="12" cy="13" r="3.5"></circle></svg>
    <span class="label">App status</span>
  </a>
  {#if !$canEdit}
    <a class="item" href="/unlock" use:link aria-current={name === "unlock" ? "page" : undefined} class:on={name === "unlock"}>
      <span class="label">Unlock editing</span>
    </a>
  {/if}

  <div class="camera">
    {#if status}<CameraStatus camera={status.camera} {now} />{/if}
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
  .sorted {
    margin: 12px 0; padding: 10px 8px; border-radius: 16px; background: var(--sand); border: 1px solid var(--line);
    display: flex; flex-direction: column; gap: 4px;
  }
  .sorted-head { padding: 0 6px 4px; font-size: 12px; font-weight: 600; color: var(--ink-2); }
  .swatch { width: 10px; height: 10px; border-radius: 50%; flex: none; box-shadow: 0 0 0 1px rgba(46, 33, 22, 0.45); }
  .camera { margin-top: auto; padding: 16px 10px 0; }
</style>
