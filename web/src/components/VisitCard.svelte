<script lang="ts">
  import type { Visit } from "../lib/api";
  import { clipBadge, sureChip, visitName, visitTime } from "../lib/format";
  import { link } from "../lib/link";
  import Chip from "./Chip.svelte";

  let { visit, today }: { visit: Visit; today: string } = $props();

  const image = $derived(visit.best_frame_url ?? visit.poster_url);
  const chip = $derived(sureChip(visit.confidence));
</script>

<a class="card" href="/visit/{visit.id}" use:link>
  <span class="photo">
    {#if image}
      <img src={image} alt="" loading="lazy" />
    {:else}
      <span class="placeholder" data-placeholder></span>
    {/if}
    <span class="badge">{clipBadge(visit.duration_s, visit.clip_count)}</span>
  </span>
  <span class="info">
    <span class="who">
      <span class="name">{visitName(visit)}</span>
      <span class="time">{visitTime(visit.started_at, visit.ended_at, today)}</span>
      {#if visit.corrected}<span class="time">Corrected by you</span>{/if}
    </span>
    {#if chip}<Chip text={chip} />{/if}
  </span>
</a>

<style>
  .card {
    display: flex;
    flex-direction: column;
    background: #fff;
    border-radius: 18px;
    overflow: hidden;
    color: var(--ink);
  }
  .photo {
    position: relative;
    display: block;
    height: 170px;
    background: var(--sand);
  }
  img, .placeholder {
    display: block;
    width: 100%;
    height: 100%;
    object-fit: cover;
    background: var(--sand);
  }
  .badge {
    position: absolute;
    left: 12px;
    bottom: 12px;
    font-size: 12px;
    font-weight: 600;
    border-radius: 999px;
    padding: 5px 10px;
    background: rgba(46, 33, 22, 0.78);
    color: #fff;
  }
  .info {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    padding: 12px 14px 14px;
  }
  .who { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
  .name { font-size: 17px; font-weight: 600; }
  .time { font-size: 13px; color: var(--ink-2); }
</style>
