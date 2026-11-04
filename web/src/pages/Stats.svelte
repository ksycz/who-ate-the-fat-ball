<script lang="ts">
  import { onMount } from "svelte";
  import { getJSON, type StatsSummary } from "../lib/api";
  import { speciesLabel } from "../lib/format";
  import Heatmap from "../components/Heatmap.svelte";

  let data = $state<StatsSummary | null>(null);
  let failed = $state(false);

  async function load() {
    failed = false;
    try {
      data = await getJSON<StatsSummary>("/api/stats?weeks=4");
    } catch {
      failed = true;
    }
  }
  onMount(load);

  // One bar per species, and one for the Unknown birds, so the bars add up to the Visits tile.
  const bars = $derived.by(() => {
    if (!data) return [];
    const out = data.per_species.map((s) => ({ key: s.scientific, label: speciesLabel(s), visits: s.visits }));
    if (data.unknown_visits > 0) out.push({ key: "unknown", label: "Unknown bird", visits: data.unknown_visits });
    return out.sort((a, b) => b.visits - a.visits); // stable: ties keep the Mac's order
  });
  const top = $derived(Math.max(1, ...bars.map((b) => b.visits)));
</script>

<header>
  <h1>Stats</h1>
  <div class="span">Last 4 weeks</div>
</header>

{#if failed}
  <div class="empty">
    <p>Couldn't reach the app. Check the Wi-Fi and try again.</p>
    <button type="button" class="again" onclick={load}>Try again</button>
  </div>
{:else if !data}
  <p class="empty">Loading…</p>
{:else}
  <div class="tiles">
    <div class="tile"><div class="label">Visits</div><div class="value">{data.visits}</div></div>
    <div class="tile"><div class="label">Species</div><div class="value">{data.species}</div></div>
    <div class="tile"><div class="label">Busiest</div><div class="value">{data.busiest ?? "—"}</div></div>
  </div>
  <div class="panels">
    <section aria-labelledby="busy-h">
      <h2 id="busy-h">Busiest times</h2>
      <Heatmap heatmap={data.heatmap} slots={data.slots} />
    </section>
    <section aria-labelledby="per-h">
      <h2 id="per-h">Visits per bird</h2>
      {#each bars as b (b.key)}
        <div class="bar">
          <div class="bar-line"><span>{b.label}</span><span class="n">{b.visits}</span></div>
          <div class="track"><div class="fill" style="width: {Math.max(2, Math.round((b.visits / top) * 100))}%"></div></div>
        </div>
      {/each}
    </section>
  </div>
{/if}

<style>
  header { display: flex; align-items: baseline; justify-content: space-between; margin: 20px 0 16px; }
  h1 { margin: 0; font-weight: 800; font-size: 34px; letter-spacing: -0.8px; }
  .span { font-size: 14px; color: var(--ink-2); }
  .tiles { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; margin-bottom: 18px; }
  .tile { background: #fff; border-radius: 14px; padding: 12px; display: flex; flex-direction: column; gap: 2px; }
  .label { font-size: 12px; color: var(--ink-2); }
  .value { font-weight: 800; font-size: 24px; }
  .panels { display: flex; flex-direction: column; gap: 18px; }
  section { background: #fff; border-radius: 18px; padding: 16px; display: flex; flex-direction: column; gap: 4px; }
  h2 { margin: 0 0 8px; font-size: 16px; font-weight: 600; }
  .bar { display: flex; flex-direction: column; gap: 4px; margin-bottom: 8px; }
  .bar-line { display: flex; justify-content: space-between; font-size: 13px; }
  .n { font-weight: 600; }
  .track { height: 10px; border-radius: 5px; background: var(--sand); }
  .fill { height: 10px; border-radius: 5px; background: var(--robin); }
  .empty { color: var(--ink-2); }
  .again { min-height: 44px; padding: 0 18px; border: 0; border-radius: 12px; background: var(--robin-tint); font: inherit; font-weight: 600; color: var(--robin-dark); cursor: pointer; }
  @media (min-width: 900px) {
    .panels { display: grid; grid-template-columns: minmax(0, 3fr) minmax(0, 2fr); align-items: start; }
  }
</style>
