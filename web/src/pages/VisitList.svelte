<script lang="ts">
  import { onMount, tick } from "svelte";
  import { getJSON, type Today, type Visit } from "../lib/api";
  import { dayHeading, dayOf } from "../lib/format";
  import { changes, noteServerDay, serverDay } from "../lib/session";
  import { loadList, saveList } from "../lib/listCache";
  import { arrival } from "../lib/router";
  import NewSpeciesBanner from "../components/NewSpeciesBanner.svelte";
  import VisitCard from "../components/VisitCard.svelte";

  type Kind = "birds" | "other_animals" | "other" | "favourites";
  let { kind }: { kind: Kind } = $props();

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
  let generation = 0; // bumped on every reload so a slow older response is dropped

  function url(after: string | null): string {
    const q = new URLSearchParams({ limit: String(PAGE) });
    if (kind === "favourites") q.set("favourite", "true");
    else q.set("category", kind);
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

  let firstChange = true;
  let lastY = 0;
  const onScroll = () => (lastY = window.scrollY);

  onMount(() => {
    window.addEventListener("scroll", onScroll, { passive: true });
    const cached = arrival.viaHistory ? loadList(kind) : undefined;
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
    if (kind === "birds") {
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
      if (loaded) saveList(kind, { visits, cursor, scrollY: lastY });
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

<div class="list">
  <h1>{TITLES[kind]}</h1>

  {#if kind === "birds" && newSpecies}
    <NewSpeciesBanner species={newSpecies} placement="birds" />
  {/if}

  {#if loaded && visits.length === 0}
    <p class="empty">{EMPTY[kind]}</p>
  {/if}

  <!-- Without the Mac's day (the status request failed) the headings and times fall back to plain dates. -->
  {#each groups as group (group.day)}
    <section>
      <h2>{dayHeading(group.day, $serverDay ?? "")}</h2>
      <div class="cards">
        {#each group.visits as visit (visit.id)}
          <VisitCard {visit} today={$serverDay ?? ""} />
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

<style>
  .list { display: flex; flex-direction: column; gap: 14px; padding: 18px 0 20px; }
  h1 { margin: 0; font-weight: 800; font-size: 34px; letter-spacing: -0.8px; }
  section { display: flex; flex-direction: column; gap: 14px; }
  h2 { margin: 6px 0 0; font-weight: 600; font-size: 15px; color: var(--ink-2); }
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
    .cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 16px; }
  }
</style>
