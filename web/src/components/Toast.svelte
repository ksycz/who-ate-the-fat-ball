<script lang="ts">
  import { send } from "../lib/api";
  import { link } from "../lib/link";
  import { noteUndone, showToast, toast, type Toast } from "../lib/session";

  const SHOWN_MS = 8000;
  let busy = $state(false);

  // Each new toast gets its own 8 seconds.
  $effect(() => {
    const t = $toast;
    if (!t) return;
    const timer = setTimeout(() => {
      if ($toast === t) toast.set(null);
    }, SHOWN_MS);
    return () => clearTimeout(timer);
  });

  async function undo(t: Toast) {
    if (!t.undoToken || busy) return;
    busy = true;
    try {
      await send("POST", `/api/undo/${t.undoToken}`);
      toast.set(null);
      noteUndone();
    } catch {
      showToast("Couldn't undo that"); // unknown or expired token, or the Wi-Fi dropped
    } finally {
      busy = false;
    }
  }
</script>

{#if $toast}
  {@const t = $toast}
  <div class="toast" role="status">
    <span class="text">
      {t.text}{#if t.unlock}{" · "}<a href="/unlock" use:link>Unlock</a>{/if}
    </span>
    {#if t.undoToken}
      <button type="button" disabled={busy} onclick={() => undo(t)}>Undo</button>
    {/if}
  </div>
{/if}

<style>
  .toast {
    position: fixed; z-index: 20; left: 16px; right: 16px; bottom: 100px; box-sizing: border-box;
    display: flex; align-items: center; justify-content: space-between; gap: 10px;
    border-radius: 14px; padding: 6px 6px 6px 16px; background: var(--ink); color: #fff;
    font-size: 14px; box-shadow: 0 6px 18px rgba(40, 30, 20, 0.25);
  }
  .text { padding: 8px 0; }
  .text a { color: var(--peach); font-weight: 600; text-decoration: underline; }
  button {
    min-height: 44px; min-width: 44px; padding: 0 14px; border: none; border-radius: 10px; background: transparent;
    color: var(--peach); font: inherit; font-size: 14px; font-weight: 600; text-decoration: underline; cursor: pointer;
  }
  @media (min-width: 768px) {
    .toast { left: 50%; right: auto; bottom: 24px; transform: translateX(-50%); width: max-content; max-width: min(420px, calc(100vw - 32px)); }
  }
</style>
