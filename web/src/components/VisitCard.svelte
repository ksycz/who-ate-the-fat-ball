<script lang="ts">
  import type { Visit } from "../lib/api";
  import { clipBadge, sureChip, timeOfDay, visitName, visitTime } from "../lib/format";
  import { link } from "../lib/link";
  import Chip from "./Chip.svelte";

  // pending: the clip is still being recognised, so there is no visit page to open yet.
  // selecting: select mode, where the card is a checkbox and its link is inert.
  let {
    visit,
    today,
    pending = false,
    selecting = false,
    selected = false,
    onselect,
  }: { visit: Visit; today: string; pending?: boolean; selecting?: boolean; selected?: boolean; onselect?: () => void } = $props();

  const image = $derived(visit.best_frame_url ?? visit.poster_url);
  // "% sure" only means something for a species the app picked; a correction or no species has none.
  const chip = $derived(!visit.corrected && visit.species ? sureChip(visit.confidence) : null);
</script>

{#snippet body()}
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
      <span class="name">{pending ? "Checking who it is…" : visitName(visit)}</span>
      <span class="time">{visitTime(visit.started_at, visit.ended_at, today)}</span>
      {#if visit.corrected}<span class="time">Corrected by you</span>{/if}
    </span>
    {#if pending}<Chip text="Checking…" pending />{:else if chip}<Chip text={chip} />{/if}
  </span>
{/snippet}

{#if selecting}
  <!-- The checkbox is the control; a tap anywhere else on the card toggles it too. -->
  <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
  <div
    class="card selecting"
    class:selected
    onclick={(e) => {
      if (!(e.target as HTMLElement).closest("label")) onselect?.();
    }}
  >
    {@render body()}
    <label class="pick">
      <input type="checkbox" checked={selected} onchange={() => onselect?.()} aria-label="Select {visitName(visit)} at {timeOfDay(visit.started_at)}" />
    </label>
  </div>
{:else if pending}
  <div class="card">{@render body()}</div>
{:else}
  <a class="card" href="/visit/{visit.id}" use:link>{@render body()}</a>
{/if}

<style>
  .card {
    display: flex;
    flex-direction: column;
    background: #fff;
    border-radius: 18px;
    overflow: hidden;
    color: var(--ink);
  }
  .card.selecting { position: relative; cursor: pointer; }
  .card.selected { outline: 3px solid var(--robin); outline-offset: -3px; }
  .pick {
    position: absolute; left: 8px; top: 8px; display: flex; align-items: center; justify-content: center;
    width: 44px; height: 44px; border-radius: 12px; background: rgba(255, 255, 255, 0.94); cursor: pointer;
  }
  .pick input { width: 22px; height: 22px; accent-color: var(--robin); }
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
  @media (min-width: 768px) {
    .photo { height: 140px; }
    .name { font-size: 15px; }
    .time { font-size: 12px; }
  }
</style>
