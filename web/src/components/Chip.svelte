<script lang="ts">
  let { text, pending = false }: { text: string; pending?: boolean } = $props();
</script>

<span class="chip" class:pending>{text}</span>

<style>
  .chip {
    flex: none;
    font-size: 12px;
    font-weight: 600;
    border-radius: 999px;
    padding: 5px 9px;
    background: var(--chip);
    color: var(--chip-ink);
  }
  .pending {
    background: var(--sand);
    color: var(--ink-2);
  }
</style>
