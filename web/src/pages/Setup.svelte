<script lang="ts">
  import { onMount } from "svelte";
  import { ApiError, getJSON, send, type Status } from "../lib/api";

  let ip = $state("");
  let password = $state("");
  let editPin = $state("");
  let message = $state("");
  let saved = $state(false);
  let busy = $state(false);
  // Asked of the server: only requests from the Mac itself may change setup. Unknown until it answers.
  let local = $state<boolean | null>(null);

  onMount(() => {
    getJSON<Status>("/api/status").then(
      (s) => (local = s.local),
      () => (local = true), // can't tell; the server still refuses anyone else
    );
  });

  async function submit(e: Event) {
    e.preventDefault();
    if (busy) return;
    message = "";
    saved = false;
    const body: { ip?: string; password?: string; edit_pin?: string } = {};
    if (ip.trim()) body.ip = ip.trim();
    if (password) body.password = password;
    if (editPin) {
      if (!/^\d{4}$/.test(editPin)) {
        message = "The edit PIN is 4 digits";
        return;
      }
      body.edit_pin = editPin;
    }
    if (Object.keys(body).length === 0) {
      message = "Fill in at least one field";
      return;
    }
    busy = true;
    try {
      await send("PUT", "/api/setup", body);
      saved = true;
      password = "";
      editPin = "";
    } catch (err) {
      message =
        err instanceof ApiError && err.status === 403
          ? "Setup only works on the Mac itself."
          : "Couldn't save that. Try again.";
    } finally {
      busy = false;
    }
  }
</script>

<h1>Setup</h1>
{#if local === false}
  <p class="msg">Setup only works on the Mac itself.</p>
{:else if local}
<form onsubmit={submit}>
  <label for="ip">Camera address</label>
  <input id="ip" type="text" autocomplete="off" bind:value={ip} />
  <label for="pw">Camera password</label>
  <input id="pw" type="password" autocomplete="new-password" bind:value={password} />
  <span class="hint">Never shown again. Leave empty to keep the current one.</span>
  <label for="pin">Edit PIN</label>
  <input id="pin" type="password" inputmode="numeric" autocomplete="off" maxlength="4" bind:value={editPin} />
  <button type="submit" disabled={busy}>Save</button>
  {#if saved}<p class="ok" role="status">Saved</p>{/if}
  {#if message}<p class="msg" role="alert">{message}</p>{/if}
</form>
{/if}

<style>
  h1 { margin: 20px 0 16px; font-weight: 800; font-size: 34px; letter-spacing: -0.8px; }
  form { display: flex; flex-direction: column; gap: 8px; max-width: 360px; }
  label { margin-top: 6px; font-size: 13px; font-weight: 600; color: var(--ink-2); }
  input { min-height: 44px; box-sizing: border-box; padding: 0 12px; font: inherit; font-size: 16px; border: 1px solid var(--field); border-radius: 12px; background: #fff; color: var(--ink); }
  .hint { font-size: 12px; color: var(--ink-2); }
  button { margin-top: 10px; min-height: 44px; border: 0; border-radius: 12px; background: var(--robin); color: #fff; font: inherit; font-weight: 600; }
  button:disabled { opacity: 0.6; }
  .ok { margin: 0; color: var(--ok); font-weight: 600; }
  .msg { margin: 0; color: var(--robin-dark); font-weight: 500; }
</style>
