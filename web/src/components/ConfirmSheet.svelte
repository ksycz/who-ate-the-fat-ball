<script lang="ts">
  import { onMount } from "svelte";

  // One confirm dialog: a sheet on the phone, a centred card on wider screens. Focus stays inside it (Tab
  // wraps), Esc or a tap on the backdrop cancels, and focus goes back to the opener if it is still there.
  let {
    title,
    action,
    danger = false,
    focus = "action",
    onconfirm,
    oncancel,
  }: {
    title: string;
    action: string; // the confirm button's label
    danger?: boolean; // the action can't be undone
    focus?: "action" | "cancel"; // which button has focus first
    onconfirm: () => void;
    oncancel: () => void;
  } = $props();

  const id = `confirm-${Math.random().toString(36).slice(2)}`;
  let dialog = $state<HTMLElement | null>(null);
  let cancelButton = $state<HTMLButtonElement | null>(null);
  let actionButton = $state<HTMLButtonElement | null>(null);

  onMount(() => {
    const opener = document.activeElement as HTMLElement | null;
    (focus === "cancel" ? cancelButton : actionButton)?.focus();
    return () => {
      if (opener?.isConnected) opener.focus(); // a gone opener (e.g. after a delete) is the page's to handle
    };
  });

  function onKey(e: KeyboardEvent) {
    if (e.key !== "Tab" || !dialog) return;
    const items = [...dialog.querySelectorAll<HTMLElement>("button:not([disabled])")];
    const first = items[0];
    const last = items[items.length - 1];
    const active = document.activeElement;
    if (e.shiftKey && (active === first || !dialog.contains(active))) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && (active === last || !dialog.contains(active))) {
      e.preventDefault();
      first.focus();
    }
  }
</script>

<svelte:window onkeydown={(e) => e.key === "Escape" && oncancel()} />

<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
<div class="backdrop" onclick={(e) => e.target === e.currentTarget && oncancel()}>
  <div class="sheet" role="dialog" aria-modal="true" aria-labelledby={id} tabindex="-1" bind:this={dialog} onkeydown={onKey}>
    <h2 {id}>{title}</h2>
    <div class="buttons">
      <button type="button" class="cancel" bind:this={cancelButton} onclick={oncancel}>Cancel</button>
      <button type="button" class="go" class:danger bind:this={actionButton} onclick={onconfirm}>{action}</button>
    </div>
  </div>
</div>

<style>
  .backdrop {
    position: fixed; inset: 0; z-index: 10; display: flex; flex-direction: column; justify-content: flex-end;
    background: rgba(46, 33, 22, 0.45);
  }
  .sheet {
    box-sizing: border-box; background: #fff; color: var(--ink); border-radius: 22px 22px 0 0;
    padding: 22px 20px 28px; display: flex; flex-direction: column; gap: 18px;
  }
  h2 { margin: 0; font-weight: 800; font-size: 20px; }
  .buttons { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
  button { min-height: 48px; border-radius: 12px; font: inherit; font-size: 15px; font-weight: 600; cursor: pointer; }
  .cancel { border: 1px solid var(--line-strong); background: #fff; color: var(--ink); }
  .go { border: none; background: var(--robin); color: #fff; }
  .go.danger { background: var(--robin-dark); }
  @media (min-width: 768px) {
    .backdrop { align-items: center; justify-content: center; }
    .sheet { width: 400px; max-width: calc(100vw - 32px); border-radius: 22px; }
  }
</style>
