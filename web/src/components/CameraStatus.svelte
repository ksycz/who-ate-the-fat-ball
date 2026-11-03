<script lang="ts">
  import type { Camera } from "../lib/api";
  import { tick } from "../lib/clock";
  import { cameraStatus } from "../lib/format";

  // serverNow is the Mac's clock in the reply and fetchedAt is when this device got it; the minutes keep counting from there.
  let { camera, today, serverNow, fetchedAt, short = false }: {
    camera: Camera; today: string; serverNow: string; fetchedAt: number; short?: boolean;
  } = $props();

  const s = $derived(cameraStatus(camera, today, { serverNow, fetchedAt, nowMs: $tick }));
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
