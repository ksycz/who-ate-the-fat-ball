<script lang="ts">
  import { onMount, tick } from "svelte";
  import { ApiError, getJSON, type Category, type Today, type Visit } from "../lib/api";
  import { dayHeading, dayOf, speciesLabel, visitName } from "../lib/format";
  import { deleteEmptyClips, moveVisits, selection } from "../lib/select";
  import { changes, noteServerDay, serverDay, showToast } from "../lib/session";
  import { askZip, type ZipPlan, type ZipRequest } from "../lib/zip";
  import { loadList, loadOtherFilter, saveList, saveOtherFilter } from "../lib/listCache";
  import { arrival, back } from "../lib/router";
  import BirdsSwitch from "../components/BirdsSwitch.svelte";
  import DeleteConfirm from "../components/DeleteConfirm.svelte";
  import FilterChips from "../components/FilterChips.svelte";
  import NewSpeciesBanner from "../components/NewSpeciesBanner.svelte";
  import SelectBar from "../components/SelectBar.svelte";
  import VisitCard from "../components/VisitCard.svelte";
  import ZipConfirm from "../components/ZipConfirm.svelte";

  type Kind = "birds" | "other_animals" | "other" | "favourites";
  // species: a scientific name, to list only that species' visits (kind is birds).
  let { kind, species = null }: { kind: Kind; species?: string | null } = $props();

  type Filter = "all" | "dogs" | "empty";
  const FILTER_LABELS: Record<Filter, string> = { all: "All", dogs: "Only dogs", empty: "Empty clips" };
  const FILTER_EMPTY: Record<Filter, string> = {
    all: "Nothing here: no dogs, people or empty clips",
    dogs: "No dogs here",
    empty: "No empty clips",
  };
  const FILTER_OPTIONS = Object.values(FILTER_LABELS);

  const PAGE = 50;
  const TITLES: Record<Kind, string> = {
    birds: "Birds",
    other_animals: "Other animals",
    other: "Other",
    favourites: "Favourites",
  };
  const EMPTY: Record<Kind, string> = {
    birds: "No bird visits yet",
    other_animals: "No other animals yet",
    other: "Nothing here: no dogs, people or empty clips",
    favourites: "No favourites yet. Tap ☆ on a visit to keep it here.",
  };

  let visits = $state<Visit[]>([]);
  let cursor = $state<string | null>(null);
  let loaded = $state(false);
  let loading = $state(false);
  let failed = $state(false);
  let newSpecies = $state<Today["new_species"]>(null);
  let sentinel = $state<HTMLElement | null>(null);
  let filter = $state<Filter>("all"); // only used on Other
  let confirmingDelete = $state(false);
  let zipPlan = $state<ZipPlan | null>(null);
  let working = $state(false); // a move or a zip request is on its way
  let generation = 0; // bumped on every reload so a slow older response is dropped

  // Remembered lists are kept per filter: "other:empty".
  const cacheKey = () =>
    species !== null ? `species:${species}` : kind === "other" && filter !== "all" ? `other:${filter}` : kind;
  const title = $derived(species !== null ? (visits[0]?.species ? speciesLabel(visits[0].species) : species) : TITLES[kind]);

  function chooseFilter(label: string) {
    const next = (Object.keys(FILTER_LABELS) as Filter[]).find((f) => FILTER_LABELS[f] === label);
    if (!next || next === filter) return;
    filter = next;
    saveOtherFilter(next);
    selection.clear(); // picks belong to the list they were made on
    reload();
  }

  function url(after: string | null): string {
    const q = new URLSearchParams({ limit: String(PAGE) });
    if (kind === "favourites") q.set("favourite", "true");
    else q.set("category", kind);
    if (species !== null) q.set("species", species);
    if (kind === "other" && filter !== "all") q.set("only", filter);
    if (after !== null) q.set("cursor", after);
    return `/api/visits?${q}`;
  }

  async function loadPage(after: string | null) {
    if (loading) return;
    loading = true;
    failed = false;
    const mine = generation;
    try {
      const page = await getJSON<{ items: Visit[]; next_cursor: string | null }>(url(after));
      if (mine !== generation) return;
      visits = after === null ? page.items : [...visits, ...page.items];
      cursor = page.next_cursor;
      loaded = true;
    } catch {
      if (mine === generation) failed = true;
    } finally {
      if (mine === generation) loading = false;
    }
  }

  function reload() {
    generation++;
    loading = false;
    visits = [];
    cursor = null;
    loaded = false;
    loadPage(null);
  }

  const more = () => {
    if (cursor !== null && !loading) loadPage(cursor);
  };

  // Day groups; a day that spans two pages stays one group.
  const groups = $derived.by(() => {
    const out: { day: string; visits: Visit[] }[] = [];
    for (const v of visits) {
      const day = dayOf(v.started_at);
      const last = out[out.length - 1];
      if (last && last.day === day) last.visits.push(v);
      else out.push({ day, visits: [v] });
    }
    return out;
  });

  const picked = $derived([...$selection.ids]);

  async function moveSelected(category: Category) {
    if (working || picked.length === 0) return;
    working = true;
    const only = picked.length === 1 ? visits.find((v) => v.id === picked[0]) : undefined;
    await moveVisits(picked, category, only ? visitName(only) : undefined);
    working = false;
  }

  async function deleteSelected() {
    if (working || picked.length === 0) return;
    working = true;
    await deleteEmptyClips(picked); // on a failure the picks stay
    confirmingDelete = false;
    working = false;
  }

  // Ask the Mac how big the .zip is; the owner then confirms before anything downloads.
  async function planZip(body: ZipRequest) {
    if (working) return;
    working = true;
    try {
      zipPlan = await askZip(body);
    } catch (e) {
      showToast(
        e instanceof ApiError && (e.status === 422 || e.status === 404)
          ? e.detail
          : "Couldn't prepare the download. Check the Wi-Fi and try again.",
      );
    } finally {
      working = false;
    }
  }

  const zipDay = (day: string) =>
    planZip(kind === "favourites" ? { day, favourite: true } : { day, category: kind });

  let firstChange = true;
  let lastY = 0;
  const onScroll = () => (lastY = window.scrollY);

  onMount(() => {
    window.addEventListener("scroll", onScroll, { passive: true });
    if (kind === "other" && arrival.viaHistory) filter = loadOtherFilter() as Filter;
    else saveOtherFilter("all");
    const cached = arrival.viaHistory ? loadList(cacheKey()) : undefined;
    if (cached) {
      // Back from a visit: the same items and place as when we left.
      visits = cached.visits;
      cursor = cached.cursor;
      loaded = true;
      lastY = cached.scrollY;
      tick().then(() => window.scrollTo(0, cached.scrollY));
    } else {
      reload();
    }
    if ($serverDay === null) {
      getJSON<{ day: string }>("/api/status").then((s) => noteServerDay(s.day)).catch(() => {});
    }
    if (kind === "birds" && species === null) {
      getJSON<Today>("/api/today")
        .then((t) => {
          newSpecies = t.new_species;
          noteServerDay(t.day);
        })
        .catch(() => {});
    }
    // An Undo elsewhere changes what belongs on this list: start again from the top.
    const stop = changes.subscribe(() => {
      if (firstChange) firstChange = false;
      else reload();
    });
    return () => {
      stop();
      window.removeEventListener("scroll", onScroll);
      if (loaded) saveList(cacheKey(), { visits, cursor, scrollY: lastY });
    };
  });

  $effect(() => {
    if (!sentinel || typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) more();
      },
      { rootMargin: "400px" },
    );
    observer.observe(sentinel);
    return () => observer.disconnect();
  });
</script>

<div class="list" class:selecting={$selection.on}>
  {#if species !== null}
    <button type="button" class="back" aria-label="Back" onclick={() => back("/birds/species")}>
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M15 6l-6 6 6 6"></path></svg>
    </button>
  {/if}
  <div class="head">
    <h1>{title}</h1>
    {#if loaded && visits.length > 0}
      <div class="tools">
        {#if $selection.on}
          <button type="button" class="tool" onclick={() => selection.selectAll(visits.map((v) => v.id))}>Select all</button>
        {/if}
        <button
          type="button"
          class="tool"
          aria-pressed={$selection.on}
          onclick={() => ($selection.on ? selection.clear() : selection.enter())}
        >{$selection.on ? "Done" : "Select"}</button>
      </div>
    {/if}
  </div>

  {#if kind === "birds" && species === null}
    <BirdsSwitch view="all" />
  {/if}

  {#if kind === "other"}
    <FilterChips options={FILTER_OPTIONS} value={FILTER_LABELS[filter]} onchange={chooseFilter} />
  {/if}

  {#if $selection.on}
    <SelectBar
      {kind}
      {filter}
      count={picked.length}
      busy={working}
      onmove={moveSelected}
      onzip={() => planZip({ visit_ids: picked })}
      ondelete={() => (confirmingDelete = true)}
    />
  {/if}

  {#if kind === "birds" && species === null && newSpecies}
    <NewSpeciesBanner species={newSpecies} placement="birds" />
  {/if}

  {#if loaded && visits.length === 0}
    <p class="empty">{species !== null ? "No visits for this species" : kind === "other" ? FILTER_EMPTY[filter] : EMPTY[kind]}</p>
  {/if}

  <!-- Without the Mac's day (the status request failed) the headings and times fall back to plain dates. -->
  {#each groups as group (group.day)}
    <section>
      <div class="day">
        <h2>{dayHeading(group.day, $serverDay ?? "")}</h2>
        {#if species === null}
          <button type="button" class="day-zip" disabled={working} onclick={() => zipDay(group.day)}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 4v11M7 10l5 5 5-5M5 20h14"></path></svg>Download this day (.zip)
          </button>
        {/if}
      </div>
      <div class="cards">
        {#each group.visits as visit (visit.id)}
          <VisitCard
            {visit}
            today={$serverDay ?? ""}
            selecting={$selection.on}
            selected={$selection.ids.has(visit.id)}
            onselect={() => selection.toggle(visit.id)}
          />
        {/each}
      </div>
    </section>
  {/each}

  {#if failed}
    <div class="failed">
      <p class="note">Couldn't load visits. Check the Wi-Fi and try again.</p>
      <button type="button" class="more" onclick={() => loadPage(cursor)}>Try again</button>
    </div>
  {/if}

  {#if cursor !== null && !failed}
    <div class="sentinel" bind:this={sentinel}></div>
    <button type="button" class="more" onclick={more} disabled={loading}>Show more</button>
  {/if}
</div>

{#if confirmingDelete}
  <DeleteConfirm count={picked.length} ondelete={deleteSelected} ondone={() => (confirmingDelete = false)} />
{/if}

{#if zipPlan}
  <ZipConfirm info={zipPlan} ondone={() => (zipPlan = null)} />
{/if}

<style>
  .list { display: flex; flex-direction: column; gap: 14px; padding: 18px 0 20px; }
  .list.selecting { padding-bottom: 150px; } /* room for the bar over the last card */
  .back {
    display: flex; align-items: center; justify-content: center; width: 44px; height: 44px; border-radius: 50%;
    border: none; background: #fff; color: var(--ink); cursor: pointer;
  }
  .head { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
  h1 { margin: 0; font-weight: 800; font-size: 34px; letter-spacing: -0.8px; }
  .tools { display: flex; gap: 8px; }
  .tool {
    min-height: 44px; padding: 0 16px; border-radius: 12px; border: 1px solid var(--line-strong); background: #fff;
    color: var(--robin-dark); font: inherit; font-size: 14px; font-weight: 600; cursor: pointer;
  }
  .tool[aria-pressed="true"] { background: var(--ink); border-color: var(--ink); color: #fff; }
  section { display: flex; flex-direction: column; gap: 14px; }
  .day { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
  h2 { margin: 6px 0 0; font-weight: 600; font-size: 15px; color: var(--ink-2); }
  .day-zip { display: none; }
  .empty {
    margin: 0; padding: 28px 20px; border-radius: 18px; background: #fff;
    text-align: center; font-size: 15px; color: var(--ink-2);
  }
  .failed { display: flex; flex-direction: column; align-items: center; gap: 10px; }
  .note { margin: 0; font-size: 13px; color: var(--ink-2); }
  .sentinel { height: 1px; }
  .more {
    align-self: center; min-height: 44px; padding: 0 20px; border-radius: 10px;
    border: 1px solid var(--line-strong); background: #fff; color: var(--robin-dark);
    font: inherit; font-size: 14px; font-weight: 600; cursor: pointer;
  }
  .more:disabled { opacity: 0.6; cursor: default; }
  .cards { display: flex; flex-direction: column; gap: 14px; }
  @media (min-width: 768px) {
    .list { padding-top: 0; }
    .list.selecting { padding-bottom: 20px; }
    .day-zip {
      display: flex; align-items: center; gap: 6px; min-height: 44px; padding: 0 12px; border: none; border-radius: 10px;
      background: transparent; color: var(--robin-dark); font: inherit; font-size: 13px; font-weight: 600; cursor: pointer;
    }
    .day-zip:disabled { opacity: 0.6; cursor: default; }
    .cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 16px; }
  }
</style>
