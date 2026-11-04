<script lang="ts">
  import { onMount } from "svelte";
  import { route } from "./lib/router";
  import { loadSession } from "./lib/session";
  import NavPhone from "./components/NavPhone.svelte";
  import Toast from "./components/Toast.svelte";
  import NavSide from "./components/NavSide.svelte";
  import Species from "./pages/Species.svelte";
  import VisitList from "./pages/VisitList.svelte";
  import Today from "./pages/Today.svelte";
  import Videos from "./pages/Videos.svelte";
  import Stats from "./pages/Stats.svelte";
  import Visit from "./pages/Visit.svelte";
  import More from "./pages/More.svelte";
  import AppStatus from "./pages/AppStatus.svelte";
  import Unlock from "./pages/Unlock.svelte";
  import Setup from "./pages/Setup.svelte";
  import NotFound from "./pages/NotFound.svelte";

  const pages = {
    today: Today,
    videos: Videos,
    stats: Stats,
    visit: Visit,
    "birds-species": Species,
    more: More,
    status: AppStatus,
    unlock: Unlock,
    setup: Setup,
    notfound: NotFound,
  } as const;

  const lists = {
    birds: "birds",
    "other-animals": "other_animals",
    other: "other",
    favourites: "favourites",
  } as const;

  const listKind = $derived(
    $route.name === "birds" || $route.name === "other-animals" || $route.name === "other" || $route.name === "favourites"
      ? lists[$route.name]
      : null,
  );
  // Pages of visit cards use the full width on a big screen (a grid of cards, as in the Mac prototype).
  const roomy = $derived(
    listKind !== null || $route.name === "today" || $route.name === "videos" || $route.name === "stats" || $route.name === "birds-species" || $route.name === "species",
  );
  const Page = $derived(listKind || $route.name === "species" ? null : pages[$route.name as keyof typeof pages]);

  onMount(() => {
    loadSession();
  });
</script>

<div class="shell">
  <NavSide />
  <main data-route={$route.name} class:roomy class:feed={$route.name === "videos"}>
    {#if $route.name === "species"}
      {#key $route.params.scientific}<VisitList kind="birds" species={$route.params.scientific} />{/key}
    {:else if listKind}
      {#key listKind}<VisitList kind={listKind} />{/key}
    {:else if Page}
      <Page />
    {/if}
  </main>
  <NavPhone />
</div>
<Toast />

<style>
  .shell { display: flex; min-height: 100vh; }
  main {
    flex: 1;
    min-width: 0;
    box-sizing: border-box;
    max-width: 640px;
    margin: 0 auto;
    padding: 0 20px 96px;
  }
  /* The Videos feed is a dark page that runs edge to edge on a phone, with the bar's room kept below it. */
  main.feed { max-width: none; padding: 0 0 var(--nav-phone-h); background: var(--ink); }
  @media (min-width: 768px) {
    main.feed { padding: 28px 32px 40px; background: none; }
    main { max-width: 760px; padding: 28px 32px 40px; }
    main.roomy { max-width: 1240px; }
  }
</style>
