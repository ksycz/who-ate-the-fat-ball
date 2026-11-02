<script lang="ts">
  import { route } from "../lib/router";
  import { link } from "../lib/link";
  import Icon from "./Icon.svelte";

  const items = [
    { label: "Today", href: "/", icon: "Today", names: ["today"] },
    { label: "Birds", href: "/birds", icon: "Birds", names: ["birds", "other-animals", "other"] },
    { label: "More", href: "/more", icon: "More", names: ["more", "favourites", "status", "unlock", "setup"] },
  ] as const;
</script>

<nav aria-label="Main">
  {#each items as item (item.label)}
    {@const on = (item.names as readonly string[]).includes($route.name)}
    <a href={item.href} use:link aria-current={on ? "page" : undefined} class:on>
      <span class="pill"><Icon name={item.icon} /></span>
      {item.label}
    </a>
  {/each}
</nav>

<style>
  nav {
    position: fixed;
    left: 12px;
    right: 12px;
    bottom: 14px;
    z-index: 5;
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 2px;
    padding: 8px 6px;
    border-radius: 24px;
    background: #fff;
    border: 1px solid var(--line);
    box-shadow: 0 6px 18px rgba(40, 30, 20, 0.12);
  }
  a {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 3px;
    min-height: 48px;
    font-size: 11px;
    font-weight: 500;
    color: var(--olive);
  }
  a.on { font-weight: 600; color: var(--robin-dark); }
  .pill {
    display: flex; align-items: center; justify-content: center;
    width: 52px; height: 30px; border-radius: 999px;
  }
  a.on .pill { background: var(--robin-tint); }
  @media (min-width: 768px) {
    nav { display: none; }
  }
</style>
