<script lang="ts">
  import { onMount } from "svelte";
  import { getJSON, type Status } from "../lib/api";
  import { cameraStatus, plural, whenText } from "../lib/format";
  import { noteServerDay, serverDay } from "../lib/session";
  import { link } from "../lib/link";
  import { tick } from "../lib/clock";

  let status = $state<Status | null>(null);
  let failed = $state(false);
  let fetchedAt = $state(0);

  onMount(() => {
    getJSON<Status>("/api/status").then(
      (s) => {
        status = s;
        fetchedAt = Date.now();
        noteServerDay(s.day);
      },
      () => (failed = true),
    );
  });

  const ERRORS: Record<string, string> = {
    wrong_password: "The camera rejected the password. Set it again in Setup.",
    account_locked: "The camera locked the login after wrong passwords. The app tries again in 10 minutes.",
    no_password: "The camera has no password. Set one in Setup.",
    low_disk: "The Mac is nearly out of space.",
    other_device:
      "A different device answered at the camera's address, so the app didn't send it the camera login. If you replaced the camera, enter its IP address again in Setup.",
  };
  const errorText = (code: string) => ERRORS[code] ?? `Something went wrong (${code}). The app keeps trying.`;

  const cam = $derived(
    status ? cameraStatus(status.camera, $serverDay ?? status.day, { serverNow: status.now, fetchedAt, nowMs: $tick }) : null,
  );
  const lastSeen = $derived(
    status?.camera.last_seen_at ? whenText(status.camera.last_seen_at, $serverDay ?? status.day) : "not yet",
  );
  const waiting = $derived(status ? status.queue.downloaded + status.queue.processing + status.recognition.pending : 0);
</script>

<h1>App status</h1>
{#if failed}
  <p class="note">Couldn't reach the app. Check the Wi-Fi and try again.</p>
{:else if status && cam}
  <section>
    <h2>Camera</h2>
    <p class="line"><span class="dot {cam.dot}"></span>{cam.dot === "ok" ? "Reachable" : cam.dot === "asleep" ? "Asleep" : "Not reachable"}</p>
    <p class="line">Last seen: {lastSeen}</p>
    {#if status.camera.last_error}<p class="warn">{errorText(status.camera.last_error)}</p>{/if}
  </section>
  <section>
    <h2>Processing</h2>
    <p class="line">{plural(waiting, "clip")} waiting</p>
    {#if status.queue.failed > 0}<p class="line">{status.queue.failed} failed</p>{/if}
  </section>
  <section>
    <h2>Mac</h2>
    <p class="line">{(status.disk.free_bytes / 1e9).toFixed(1)} GB free</p>
    {#if status.disk.low}<p class="warn">Disk nearly full</p>{/if}
  </section>
  {#if status.local}<a class="setup" href="/setup" use:link>Setup</a>{/if}
{/if}

<style>
  h1 { margin: 20px 0 16px; font-weight: 800; font-size: 34px; letter-spacing: -0.8px; }
  section { background: #fff; border-radius: 16px; padding: 14px 16px; margin-bottom: 14px; }
  h2 { margin: 0 0 6px; font-size: 13px; font-weight: 600; color: var(--ink-2); }
  .line { margin: 4px 0; font-size: 15px; display: flex; align-items: center; gap: 8px; }
  .warn { margin: 8px 0 2px; padding: 10px 12px; border-radius: 12px; background: var(--peach); color: var(--robin-dark); font-size: 14px; font-weight: 500; }
  .note { color: var(--ink-2); }
  .dot { width: 8px; height: 8px; border-radius: 50%; flex: none; }
  .ok { background: var(--ok); }
  .asleep { background: var(--dot-animals); }
  .problem { background: var(--robin); }
  .setup { display: inline-flex; align-items: center; min-height: 44px; padding: 0 18px; border-radius: 12px; background: var(--robin-tint); font-weight: 600; }
</style>
