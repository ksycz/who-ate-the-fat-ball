<script lang="ts">
  import type { SpeciesSummary } from "../lib/api";
  import { speciesLabel, whenText } from "../lib/format";
  import { link } from "../lib/link";

  let { species, today }: { species: SpeciesSummary; today: string } = $props();

  // whenText gives a bare "08:47" for today; here it reads "today 08:47".
  const last = $derived.by(() => {
    const when = whenText(species.last_seen_at, today);
    return /^\d\d:\d\d$/.test(when) ? `today ${when}` : when;
  });
</script>

<a class="card" href={`/birds/species/${encodeURIComponent(species.scientific)}`} use:link>
  <span class="photo">
    {#if species.photo_url}<img src={species.photo_url} alt="" loading="lazy" />{/if}
    {#if species.is_new}<span class="new">New</span>{/if}
  </span>
  <span class="body">
    <span class="name">{speciesLabel(species)}</span>
    <span class="count">{species.visits}<span class="unit"> {species.visits === 1 ? "visit" : "visits"}</span></span>
    <span class="last">Last seen {last}</span>
  </span>
</a>

<style>
  .card {
    display: flex; flex-direction: column; overflow: hidden; border-radius: 18px; background: #fff;
    color: var(--ink); text-decoration: none; box-shadow: 0 1px 3px rgba(46, 33, 22, 0.08);
  }
  .photo { position: relative; display: block; height: 120px; background: var(--sand); }
  .photo img { width: 100%; height: 100%; object-fit: cover; display: block; }
  .new {
    position: absolute; left: 10px; top: 10px; padding: 3px 7px; border-radius: 6px;
    background: var(--robin); color: #fff; font-size: 11px; font-weight: 600;
  }
  .body { display: flex; flex-direction: column; gap: 2px; padding: 12px 14px 14px; }
  .name { font-size: 15px; font-weight: 600; }
  .count { font-size: 24px; font-weight: 800; }
  .unit { font-size: 12px; font-weight: 500; color: var(--ink-2); }
  .last { font-size: 12px; color: var(--ink-2); }
</style>
