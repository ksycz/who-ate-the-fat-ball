<script lang="ts">
  import { onMount } from "svelte";
  import { route } from "./lib/router";
  import { loadSession } from "./lib/session";
  import NavPhone from "./components/NavPhone.svelte";
  import NavSide from "./components/NavSide.svelte";
  import Today from "./pages/Today.svelte";
  import Visit from "./pages/Visit.svelte";
  import Birds from "./pages/Birds.svelte";
  import OtherAnimals from "./pages/OtherAnimals.svelte";
  import Other from "./pages/Other.svelte";
  import Favourites from "./pages/Favourites.svelte";
  import More from "./pages/More.svelte";
  import Status from "./pages/Status.svelte";
  import Unlock from "./pages/Unlock.svelte";
  import Setup from "./pages/Setup.svelte";
  import NotFound from "./pages/NotFound.svelte";

  const pages = {
    today: Today,
    visit: Visit,
    birds: Birds,
    "other-animals": OtherAnimals,
    other: Other,
    favourites: Favourites,
    more: More,
    status: Status,
    unlock: Unlock,
    setup: Setup,
    notfound: NotFound,
  } as const;

  const Page = $derived(pages[$route.name]);

  onMount(() => {
    loadSession();
  });
</script>

<div class="shell">
  <NavSide />
  <main data-route={$route.name}>
    <Page />
  </main>
  <NavPhone />
</div>

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
  }
</style>
