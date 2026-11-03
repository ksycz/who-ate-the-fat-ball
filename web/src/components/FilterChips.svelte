<script lang="ts">
  let {
    options,
    value,
    onchange,
    tone = "light",
  }: {
    options: string[];
    value: string;
    onchange: (value: string) => void;
    tone?: "light" | "dark";
  } = $props();
</script>

<div class="chips" class:dark={tone === "dark"} role="group" aria-label="Show">
  {#each options as option (option)}
    <button type="button" class:on={option === value} aria-pressed={option === value} onclick={() => onchange(option)}>{option}</button>
  {/each}
</div>

<style>
  .chips { display: flex; flex-wrap: wrap; gap: 8px; }
  button {
    min-height: 44px; padding: 0 16px; border-radius: 999px; background: #fff; color: var(--ink-2);
    border: 1px solid var(--line-strong); font: inherit; font-size: 14px; font-weight: 400; cursor: pointer;
  }
  button.on { border: 1.5px solid var(--robin-dark); color: var(--robin-dark); font-weight: 600; }
  .dark button { background: transparent; color: #fff; border: 1px solid rgba(255, 255, 255, 0.45); }
  .dark button.on { border: 1.5px solid #fff; font-weight: 600; }
</style>
