<script lang="ts">
  import { ApiError, send } from "../lib/api";
  import { back } from "../lib/router";
  import { canEdit } from "../lib/session";

  let pin = $state("");
  let message = $state("");
  let busy = $state(false);

  async function submit(e: Event) {
    e.preventDefault();
    if (busy) return;
    busy = true;
    message = "";
    try {
      await send("POST", "/api/unlock", { pin });
      canEdit.set(true);
      back("/");
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) message = "That PIN isn't right";
      else if (err instanceof ApiError && err.status === 429) message = "Too many tries. Wait 15 minutes and try again.";
      else message = "Couldn't unlock. Check the Wi-Fi and try again.";
      pin = "";
    } finally {
      busy = false;
    }
  }
</script>

<h1>Unlock editing</h1>
<form onsubmit={submit}>
  <label for="pin">Edit PIN</label>
  <input id="pin" type="password" inputmode="numeric" autocomplete="one-time-code" maxlength="4" bind:value={pin} />
  <button type="submit" disabled={busy}>Unlock</button>
  {#if message}<p class="msg" role="alert">{message}</p>{/if}
</form>

<style>
  h1 { margin: 20px 0 16px; font-weight: 800; font-size: 34px; letter-spacing: -0.8px; }
  form { display: flex; flex-direction: column; gap: 10px; max-width: 320px; }
  label { font-size: 13px; font-weight: 600; color: var(--ink-2); }
  input { min-height: 44px; box-sizing: border-box; padding: 0 12px; font: inherit; font-size: 18px; letter-spacing: 4px; border: 1px solid var(--field); border-radius: 12px; background: #fff; color: var(--ink); }
  button { min-height: 44px; border: 0; border-radius: 12px; background: var(--robin); color: #fff; font: inherit; font-weight: 600; }
  button:disabled { opacity: 0.6; }
  .msg { margin: 0; color: var(--robin-dark); font-weight: 500; }
</style>
