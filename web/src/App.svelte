<script lang="ts">
  import { onMount } from "svelte";
  import { route } from "./lib/router";
  import { loadSession } from "./lib/session";
  import NavPhone from "./components/NavPhone.svelte";
  import Toast from "./components/Toast.svelte";
  import NavSide from "./components/NavSide.svelte";
  import VisitList from "./pages/VisitList.svelte";
  import Today from "./pages/Today.svelte";
  import Visit from "./pages/Visit.svelte";
  import More from "./pages/More.svelte";
  import AppStatus from "./pages/AppStatus.svelte";
  import Unlock from "./pages/Unlock.svelte";
  import Setup from "./pages/Setup.svelte";
  import NotFound from "./pages/NotFound.svelte";

  const pages = {
    today: Today,
    visit: Visit,
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
  const roomy = $derived(listKind !== null || $route.name === "today");
  const Page = $derived(listKind ? null : pages[$route.name as keyof typeof pages]);

  onMount(() => {
    loadSession();
  });
</script>

<div class="shell">
  <NavSide />
  <main data-route={$route.name} class:roomy>
    {#if listKind}
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
  @media (min-width: 768px) {
    main { max-width: 760px; padding: 28px 32px 40px; }
    main.roomy { max-width: 1240px; }
  }
</style>
