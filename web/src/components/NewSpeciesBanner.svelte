<script lang="ts">
  import type { Today } from "../lib/api";
  import { speciesLabel, timeOfDay } from "../lib/format";
  import { link } from "../lib/link";
  import Logo from "./Logo.svelte";

  // "today": shown on the phone's Today page only. "birds": shown on the side layout's Birds page only.
  let { species, placement = "today" }: { species: NonNullable<Today["new_species"]>; placement?: "today" | "birds" } = $props();
</script>

<div class="slot" data-placement={placement}>
<div class="banner" role="status">
  <Logo size={36} variant="mark" />
  <span class="text">
    <span class="head">New species</span>
    <span class="line">{speciesLabel(species)} · {timeOfDay(species.started_at)}</span>
  </span>
  <a class="watch" href="/visit/{species.visit_id}" use:link>Watch</a>
</div>
</div>

<style>
  .slot[data-placement="birds"] { display: none; }
  @media (min-width: 768px) {
    .slot[data-placement="today"] { display: none; }
    .slot[data-placement="birds"] { display: block; }
  }
  .banner {
    display: flex;
    align-items: center;
    gap: 12px;
    border-radius: 16px;
    padding: 10px 10px 10px 12px;
    background: var(--robin);
    color: #fff;
  }
  .banner :global(svg) { flex: none; }
  .text { flex: 1; display: flex; flex-direction: column; gap: 1px; min-width: 0; }
  .head { font-size: 12px; font-weight: 500; letter-spacing: 0.3px; color: var(--peach); }
  .line { font-size: 15px; font-weight: 400; }
  .watch {
    flex: none;
    display: flex;
    align-items: center;
    min-height: 44px;
    padding: 0 16px;
    border-radius: 10px;
    background: #fff;
    color: var(--robin-dark);
    font-size: 14px;
    font-weight: 600;
  }
</style>
