<script lang="ts">
  import { onMount } from "svelte";
  import { rememberSpeciesName } from "../lib/listCache";
  import { speciesLabel } from "../lib/format";
  import { getJSON, type SpeciesSummary } from "../lib/api";
  import { changes, noteServerDay, period, serverDay, type Period } from "../lib/session";
  import BirdsSwitch from "../components/BirdsSwitch.svelte";
  import FilterChips from "../components/FilterChips.svelte";
  import SpeciesCard from "../components/SpeciesCard.svelte";

  const LABELS: Record<Period, string> = { week: "This week", month: "This month", all: "All time" };
  const OPTIONS = Object.values(LABELS);
  const SUBTITLE: Record<Period, string> = { week: "this week", month: "this month", all: "all time" };
  const EMPTY: Record<Period, string> = { week: "No birds this week", month: "No birds this month", all: "No birds yet" };

  let rows = $state<SpeciesSummary[]>([]);
  let loaded = $state(false);
  let failed = $state(false);
  let generation = 0; // a slow answer for a period the owner has left is dropped

  async function load() {
    const mine = ++generation;
    failed = false;
    loaded = false;
    rows = []; // the last period's cards don't stay under the new chip
    try {
      const got = await getJSON<SpeciesSummary[]>(`/api/species?period=${$period}`);
      if (mine !== generation) return;
      rows = got;
      for (const r of got) rememberSpeciesName(r.scientific, speciesLabel(r));
      loaded = true;
    } catch {
      if (mine === generation) failed = true;
    }
  }

  function choose(label: string) {
    const next = (Object.keys(LABELS) as Period[]).find((p) => LABELS[p] === label);
    if (!next || next === $period) return;
    period.set(next);
    load();
  }

  onMount(() => {
    load();
    if ($serverDay === null) {
      getJSON<{ day: string }>("/api/status").then((s) => noteServerDay(s.day)).catch(() => {});
    }
    let first = true;
    return changes.subscribe(() => {
      if (first) first = false;
      else load();
    });
  });
</script>

<div class="page">
  <div class="head">
    <h1>Birds</h1>
    {#if loaded}<p class="sub">{rows.length} species · {SUBTITLE[$period]}</p>{/if}
  </div>
  <BirdsSwitch view="species" />
  <FilterChips options={OPTIONS} value={LABELS[$period]} onchange={choose} />

  {#if failed}
    <p class="note">Couldn't load the birds. Check the Wi-Fi and try again.</p>
    <button type="button" class="retry" onclick={load}>Try again</button>
  {:else if loaded && rows.length === 0}
    <p class="empty">{EMPTY[$period]}</p>
  {/if}

  <div class="grid">
    {#each rows as species (species.scientific)}
      <SpeciesCard {species} today={$serverDay ?? ""} />
    {/each}
  </div>
</div>

<style>
  .page { display: flex; flex-direction: column; gap: 14px; padding: 18px 0 20px; }
  .head { display: flex; flex-direction: column; gap: 2px; }
  h1 { margin: 0; font-weight: 800; font-size: 34px; letter-spacing: -0.8px; }
  .sub { margin: 0; font-size: 14px; color: var(--ink-2); }
  .grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
  .empty {
    margin: 0; padding: 28px 20px; border-radius: 18px; background: #fff;
    text-align: center; font-size: 15px; color: var(--ink-2);
  }
  .note { margin: 0; font-size: 13px; color: var(--ink-2); }
  .retry {
    align-self: center; min-height: 44px; padding: 0 20px; border-radius: 10px;
    border: 1px solid var(--line-strong); background: #fff; color: var(--robin-dark);
    font: inherit; font-size: 14px; font-weight: 600; cursor: pointer;
  }
  @media (min-width: 768px) {
    .page { padding-top: 0; }
    .grid { grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 16px; }
  }
</style>
