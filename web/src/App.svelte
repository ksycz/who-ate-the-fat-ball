<script lang="ts">
  import { route } from "./lib/router";
  import Logo from "./components/Logo.svelte";
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
</script>

<main data-route={$route.name}>
  <header><Logo size={32} /></header>
  <Page />
  <p class="route">{$route.name}</p>
</main>

<style>
  main {
    max-width: 640px;
    margin: 0 auto;
    padding: 16px;
  }
  .route {
    font-size: 11px;
    color: var(--olive);
  }
</style>
