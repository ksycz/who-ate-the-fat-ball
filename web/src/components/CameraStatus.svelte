<script lang="ts">
  import type { Camera } from "../lib/api";
  import { cameraStatus } from "../lib/format";

  let { camera, now, today, short = false }: { camera: Camera; now: Date; today: string; short?: boolean } = $props();

  const s = $derived(cameraStatus(camera, now, today));
  // The short form drops the "Check App status" hint; the problem notice carries it instead.
  const text = $derived(short && s.dot === "problem" ? "Camera not seen" : s.text);
</script>

<span class="status" role="status">
  <span class="dot {s.dot}"></span><span>{text}</span>
</span>

<style>
  .status {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-size: 12px;
    color: var(--ink-2);
  }
  .dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    flex: none;
  }
  .ok { background: var(--ok); }
  .asleep { background: var(--dot-other); }
  .problem { background: var(--robin); }
</style>
